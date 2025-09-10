Odoo v18 Migration Script
A comprehensive Python script to automate the migration of custom Odoo modules to Odoo version 18. This tool is designed to handle many of the common breaking changes introduced in v18, significantly speeding up the upgrade process for developers.

Description
Migrating Odoo modules manually can be a repetitive and time-consuming task. This script acts as a powerful assistant by scanning your module's source code and automatically applying fixes for the most common deprecations and syntax changes. It intelligently modifies Python (.py), XML (.xml), JavaScript (.js), and manifest (__manifest__.py) files.

Key Features
The script automates the following changes:

manifest.py
Version Bump: Automatically sets the module version to 18.0.1.0.0.

Python Files (.py)
Method Renaming: Replaces deprecated methods with their new equivalents:

user_has_groups -> env.user.has_group

_name_search -> _search_display_name

_check_recursion -> _has_cycle

check_access_rights / check_access_rule -> check_access

_filter_access_rule / _filter_access_rule_python -> _filter_access

View Type Update: Changes 'tree' to 'list' in view mode definitions.

XML Files (.xml)
attrs and states Conversion: Intelligently parses legacy attrs and states attributes and converts them into direct conditional attributes (e.g., invisible="...", readonly="...").

View Conversion:

Replaces all <tree> view tags with <list> tags, while preserving XML-IDs.

Updates view_type="tree" to view_type="list".

Chatter and Settings Views:

Converts <div class="oe_chatter">...</div> to the simple <chatter /> component.

Modernizes the structure of Settings views (res.config.settings) to use the new <app>, <block>, and <setting> tags.

Attribute & Context Updates:

Renames group_operator to aggregator.

Replaces active_id with id in view contexts and adds TODO comments for active_model and active_ids which require manual review.

JavaScript Files (.js)
View Type Update: Changes 'tree' to 'list' in JavaScript view definitions (view_mode or viewType).

Prerequisites
Before running the script, make sure you have:

Python 3.6 or higher.

The lxml library. Install it via pip:

pip install lxml

How to Use
⚠️ Step 0: Backup Your Code!
This is the most important step. The script modifies your files in-place. Ensure your project is under version control (like Git) and that you have committed all your changes before proceeding.

Save the Script: Save the code as odoo_v18_migrator.py in a convenient location.

Run from Terminal: Open your terminal or command prompt and execute the script, passing the path to the directory containing the Odoo modules you want to migrate.

Syntax:

python odoo_v18_migrator.py <path_to_your_modules_directory>

Example:

python odoo_v18_migrator.py /home/user/odoo/custom_addons

Review Changes: After the script finishes, it will have logged all its actions. Use git diff to carefully review every change made to your files. Pay special attention to any <!-- TODO --> comments the script may have added, as these indicate areas that require manual intervention.
