## Vertical Alignment
Code will be vertically aligned wherever possible.

## Comments and Documentation
No XML commenting ever.
No module-level docstrings - use the `# MARK: OVERVIEW` block instead (see File Section Structure).
Functions and code blocks are documented with normal comments.

## File Section Structure
Use `# MARK: <KEYWORD>` to label major sections.

Use one canonical major-section separator line:
`# ====================================================================================================`

For major sections, place the canonical separator both above and below the `# MARK:` line.

Use one canonical function separator line:
`# ----------------------------------------------------------------------------------------------------`

Do not use no-space variants such as `#MARK:` or `#====================================================================================================`.

Every module opens with a `# MARK: OVERVIEW` block. Structure:
```
# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# One-paragraph description of the module's purpose.
#
# Public API (if useful to list):
#   function_name(args)  -- short description
#
# Related modules:
#   - other_module.py   -- why it relates
# ====================================================================================================
```

## Imports
One symbol per import line - never `from X import A, B, C`.
Stdlib imports first, then a blank line, then project imports.

## Strings
Double quotes for all string literals. Never single quotes.

## Type Hints
Use `str | None` union syntax, not `Optional[str]`.

## No EM Dashes
The - character will be replaced with - in all cases.