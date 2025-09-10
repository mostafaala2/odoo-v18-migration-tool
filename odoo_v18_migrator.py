# -*- coding: utf-8 -*-
import os
import re
import sys
from lxml import etree
import logging

# Configure logging to show which files are being processed
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

# --- HELPERS FOR ATTRS/STATES CONVERSION (FROM ORIGINAL SCRIPT) ---

NEW_ATTRS = ['invisible', 'required', 'readonly', 'column_invisible']

def normalize_domain(domain):
    """
    Normalize Domain, taken from odoo/osv/expression.py -> just the part so that & operators are added where needed.
    """
    if len(domain) == 1:
        return domain
    result = []
    expected = 1
    op_arity = {'!': 1, '&': 2, '|': 2}
    for token in domain:
        if expected == 0:
            result[0:0] = ['&']
            expected = 1
        if isinstance(token, (list, tuple)):
            expected -= 1
            token = tuple(token)
        else:
            expected += op_arity.get(token, 0) - 1
        result.append(token)
    return result

def stringify_leaf(leaf):
    """Converts a domain leaf to a Pythonic string condition."""
    operator = str(leaf[1])
    left_operand = leaf[0]
    right_operand = leaf[2]

    if operator == '=?':
        if isinstance(right_operand, str):
            right_operand = f"'{right_operand}'"
        return f"({right_operand} in [None, False] or {left_operand} == {right_operand})"
    elif operator == '=':
        if right_operand is False or right_operand == []:
            return f"not {left_operand}"
        if right_operand is True:
            return str(left_operand)
        operator = '=='
    elif operator == '!=':
        if right_operand is False or right_operand == []:
            return str(left_operand)
        if right_operand is True:
            return f"not {left_operand}"
    elif 'like' in operator:
        if isinstance(right_operand, str) and re.search('[_%]', right_operand):
            raise ValueError("Script doesn't support 'like' domains with wildcards")
        case_insensitive = 'ilike' in operator
        op_map = {'=like': '==', '=ilike': '=='}
        if operator in op_map:
            operator = op_map[operator]
        else:
            operator = 'not in' if 'not' in operator else 'in'
        
        if isinstance(right_operand, str):
            right_operand = f"'{right_operand}'"

        condition = f"{right_operand} {operator} {left_operand}"
        if case_insensitive:
            condition = f"{right_operand}.lower() {operator} {left_operand}.lower()"
        return condition
        
    if isinstance(right_operand, str):
        right_operand = f"'{right_operand}'"

    return f"{left_operand} {operator} {right_operand}"

def stringify_attr(stack):
    """Recursively converts a domain list to a Pythonic string condition."""
    if stack in (True, False, 'True', 'False', 1, 0, '1', '0'):
        return str(stack)
    
    stack = normalize_domain(stack)
    result = []
    
    # Simple recursive parser for domain
    def _parse(domain):
        if not domain:
            return ""
        token = domain.pop(0)
        if token == '!':
            return f"(not ({_parse(domain)}))"
        if token in ('&', '|'):
            op = 'and' if token == '&' else 'or'
            return f"({_parse(domain)}) {op} ({_parse(domain)})"
        return stringify_leaf(token)
    
    # Invert stack to process correctly
    inverted_stack = stack[::-1]
    while inverted_stack:
        token = inverted_stack.pop(0)
        if token == '!':
             expr = result.pop()
             result.append(f'(not ({expr}))')
        elif token in ('&', '|'):
            op = 'and' if token == '&' else 'or'
            left = result.pop()
            right = result.pop()
            result.append(f'({left}) {op} ({right})')
        else:
            result.append(stringify_leaf(token))

    return result[0] if result else ""

def get_new_attrs(attrs_str):
    """Parses an `attrs` string and converts it to a dict of new attributes."""
    new_attrs = {}
    if not attrs_str or not attrs_str.strip().startswith('{'):
        return new_attrs
    try:
        attrs_dict = eval(attrs_str.strip())
        for attr, domain in attrs_dict.items():
            if attr in NEW_ATTRS:
                stringified_domain = stringify_attr(domain)
                new_attrs[attr] = stringified_domain
    except Exception as e:
        logging.warning(f"Could not evaluate attrs string: {attrs_str}. Error: {e}")
    return new_attrs

def get_combined_invisible_condition(invisible_attr, states_attr):
    """Merges a states attribute into an invisible attribute."""
    invisible_attr = invisible_attr.strip() if invisible_attr else ''
    states_attr = states_attr.strip() if states_attr else ''
    if not states_attr:
        return invisible_attr

    states_list = [f"'{s.strip()}'" for s in states_attr.split(',')]
    states_domain = f"state not in [{', '.join(states_list)}]"
    
    if invisible_attr and invisible_attr.lower() not in ('0', 'false'):
        return f"({invisible_attr}) or ({states_domain})"
    return states_domain


# --- REGEX PATTERNS AND REPLACEMENTS ---

# For __manifest__.py files
MANIFEST_REPLACEMENTS = [
    (re.compile(r"'version'\s*:\s*'[\d\.]+'"), r"'version': '18.0.1.0.0'")
]

# For Python files
PYTHON_REPLACEMENTS = {
    'user_has_groups': 'env.user.has_group',
    'check_access_rights(': 'check_access(',
    'check_access_rule(': 'check_access(',
    '_filter_access_rule(': '_filter_access(',
    '_filter_access_rule_python(': '_filter_access(',
    'def _name_search(': 'def _search_display_name(',
    '_check_recursion(': '_has_cycle(',
}

PYTHON_REGEX_REPLACEMENTS = [
    # Replace 'tree' with 'list' in view definitions and modes
    (re.compile(r"(['\"])view_mode\1\s*:\s*(['\"])([^'\"]*?)tree"), r"\1view_mode\1: \2\3list"),
    # Catches view definitions like: (False, 'tree'), (view.id, 'tree')
    (re.compile(r"(\(\s*[\w\.]*\s*,\s*['\"])tree(['\"]\))"), r"\1list\2"),
]

# For JS files
JS_REGEX_REPLACEMENTS = [
    # Replace 'tree' with 'list' in JS view definitions
    (re.compile(r"((?:view_mode|viewType)\s*:\s*['\"][^'\"]*?)tree"), r"\1list"),
]

# For XML files (simple replacements)
XML_SIMPLE_REPLACEMENTS = [
    (re.compile(r'<div class="oe_chatter">.*?</div>', re.DOTALL), r'<chatter />'),
    (re.compile(r'group_operator='), r'aggregator='),
    (re.compile(r"(['\"])active_id\1\s*:\s*active_id"), r"\1id\1: id"),
    (re.compile(r"(['\"])active_model\1\s*:\s*active_model"), r"\1active_model\1: 'REPLACE_WITH_MODEL_NAME'  <!-- TODO: Hard-code model name -->"),
    (re.compile(r"(['\"])active_ids\1"), r"<!-- TODO v18: active_ids is removed. Refactor this logic. -->\1active_ids\1"),
    (re.compile(r'(<field name="view_mode"[^>]*>.*?)tree'), r'\1list'),
    (re.compile(r'view_type="tree"'), r'view_type="list"'),
]


def update_manifest_file(file_path):
    """Bumps the version in a manifest file."""
    try:
        with open(file_path, 'r+', encoding='utf-8') as f:
            content = f.read()
            original_content = content
            for pattern, replacement in MANIFEST_REPLACEMENTS:
                content, count = pattern.subn(replacement, content)
                if count > 0:
                    logging.info(f"Updated version in {file_path}")

            if content != original_content:
                f.seek(0)
                f.write(content)
                f.truncate()
    except Exception as e:
        logging.error(f"Could not process manifest file {file_path}: {e}")


def update_python_file(file_path):
    """Applies common code replacements for Python files."""
    try:
        with open(file_path, 'r+', encoding='utf-8') as f:
            content = f.read()
            original_content = content
            for old, new in PYTHON_REPLACEMENTS.items():
                if old in content:
                    content = content.replace(old, new)
                    logging.info(f"Replaced '{old}' with '{new}' in {file_path}")
            for pattern, replacement in PYTHON_REGEX_REPLACEMENTS:
                content, count = pattern.subn(replacement, content)
                if count > 0:
                    logging.info(f"Replaced 'tree' with 'list' via regex in {file_path}")
            if content != original_content:
                f.seek(0)
                f.write(content)
                f.truncate()
    except Exception as e:
        logging.error(f"Could not process Python file {file_path}: {e}")


def update_js_file(file_path):
    """Applies 'tree' -> 'list' replacements for JS files."""
    try:
        with open(file_path, 'r+', encoding='utf-8') as f:
            content = f.read()
            original_content = content
            for pattern, replacement in JS_REGEX_REPLACEMENTS:
                content, count = pattern.subn(replacement, content)
                if count > 0:
                    logging.info(f"Replaced 'tree' with 'list' in JS file {file_path}")
            if content != original_content:
                f.seek(0)
                f.write(content)
                f.truncate()
    except Exception as e:
        logging.error(f"Could not process JS file {file_path}: {e}")


def update_xml_file(file_path):
    """Applies complex view and attribute replacements for XML files."""
    try:
        with open(file_path, 'r+', encoding='utf-8') as f:
            content = f.read()
            original_content = content

            # Apply simple regex-based replacements first
            for pattern, replacement in XML_SIMPLE_REPLACEMENTS:
                content, count = pattern.subn(replacement, content)
                if count > 0:
                    logging.info(f"Applied simple XML replacement in {file_path}")

            # Use lxml for complex structural changes
            if ('attrs' in original_content or 'states' in original_content or 
                'app_settings_block' in original_content or 'o_settings_container' in original_content or
                '<tree' in original_content):
                logging.info(f"Found complex structure in {file_path}. Processing with lxml...")
                parser = etree.XMLParser(recover=True, strip_cdata=False)
                tree = etree.fromstring(content.encode('utf-8'), parser=parser)
                lxml_changed = False

                # Convert attrs and states before other structural changes
                for tag in tree.xpath("//*[@attrs]"):
                    attrs_str = tag.attrib.pop('attrs')
                    new_attrs = get_new_attrs(attrs_str)
                    for attr, value in new_attrs.items():
                        tag.set(attr, value)
                        lxml_changed = True
                    logging.info(f"Converted 'attrs' on tag <{tag.tag}> in {file_path}")

                for tag in tree.xpath("//*[@states]"):
                    states_str = tag.attrib.pop('states')
                    current_invisible = tag.get('invisible')
                    new_invisible = get_combined_invisible_condition(current_invisible, states_str)
                    tag.set('invisible', new_invisible)
                    lxml_changed = True
                    logging.info(f"Merged 'states' into 'invisible' on tag <{tag.tag}> in {file_path}")

                for tree_tag in tree.xpath("//tree"):
                    tree_tag.tag = 'list'
                    lxml_changed = True
                    logging.info(f"Converted <tree> to <list> tag in {file_path}")

                for div in tree.xpath("//div[contains(@class, 'app_settings_block')]"):
                    div.tag = 'app'
                    div.attrib.pop('class', None)
                    lxml_changed = True

                for div in tree.xpath("//div[contains(@class, 'o_settings_container')]"):
                    div.tag = 'block'
                    div.attrib.pop('class', None)
                    h2 = div.find('h2')
                    if h2 is not None and h2.text:
                        div.set('title', h2.text.strip())
                        div.remove(h2)
                    lxml_changed = True

                for div in tree.xpath("//div[contains(@class, 'o_setting_box')]"):
                    div.tag = 'setting'
                    div.attrib.pop('class', None)
                    lxml_changed = True

                for pane in tree.xpath("//div[contains(@class, 'o_setting_left_pane') or contains(@class, 'o_setting_right_pane')]"):
                    parent = pane.getparent()
                    for child in reversed(pane):
                        parent.insert(parent.index(pane), child)
                    parent.remove(pane)
                    lxml_changed = True
                
                if lxml_changed:
                    content = etree.tostring(tree, pretty_print=True, xml_declaration=True, encoding='utf-8').decode('utf-8')

            if content != original_content:
                f.seek(0)
                f.write(content)
                f.truncate()

    except etree.XMLSyntaxError as e:
        logging.warning(f"Could not parse XML file {file_path}. It might be invalid. Skipping lxml part. Error: {e}")
    except Exception as e:
        logging.error(f"Could not process XML file {file_path}: {e}")


def migrate_module(root_dir):
    """Walks through the directory and applies migrations."""
    if not os.path.isdir(root_dir):
        logging.error(f"Directory not found: {root_dir}")
        return

    logging.info(f"--- Starting Odoo v18 migration for modules in '{root_dir}' ---")
    logging.warning("IMPORTANT: This script will modify files in-place. Make sure you have a backup or are using version control (like Git).")

    for subdir, _, files in os.walk(root_dir):
        for filename in files:
            file_path = os.path.join(subdir, filename)
            if filename == '__manifest__.py':
                update_manifest_file(file_path)
            elif filename.endswith('.py'):
                update_python_file(file_path)
            elif filename.endswith('.js'):
                update_js_file(file_path)
            elif filename.endswith('.xml'):
                update_xml_file(file_path)

    logging.info("--- Migration script finished. ---")
    logging.info("Please review the changes and manually handle any 'TODO' comments added to the code.")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python odoo_v18_migrator.py <path_to_your_odoo_modules_directory>")
        print("مثال: python odoo_v18_migrator.py /path/to/my/custom_addons")
        sys.exit(1)
    
    target_directory = sys.argv[1]
    migrate_module(target_directory)


