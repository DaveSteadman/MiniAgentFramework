# Copilot Instructions

Code standards for this project:

## Emoji
- Emoji are permitted only in the web UI layer: `index.html`, `style.css`, `app.js`.
- No emoji in Python files, Markdown docs, JSON config/data, or log output.
- In the UI, emoji are accent characters only - labels, panel headers, status indicators. Never in data payloads or API response strings.

## Formatting
- No em dashes (—) anywhere. Use a plain hyphen-minus (-) instead.
- No typographic/curly quotes anywhere - not in .py, .md, or .json files. Use only straight ASCII quotes (" and '). This applies to all generated and edited content including skill.md files, comments, and documentation.
- Double quotes for all string literals. Never single quotes.
- One symbol per import line - never `from X import A, B, C`.
- Stdlib imports first, blank line, then project imports.

## Type hints
- Use `str | None` union syntax, not `Optional[str]`.

## Documentation
- No XML commenting.
- No module-level docstrings - use `# MARK: OVERVIEW` block instead.
- Functions documented with inline comments, not docstrings - unless the function is a public API entry point where a short docstring aids tool/IDE discovery.

## File structure
- Every module opens with a `# MARK: OVERVIEW` block.
- Major sections separated with `# ====================================================================================================`.
- Functions separated with `# ----------------------------------------------------------------------------------------------------`.
- Section labels use `# MARK: <KEYWORD>` exactly - no `#MARK:` without space.

## Vertical alignment
- Align assignment operators and dict values vertically where it aids readability.
