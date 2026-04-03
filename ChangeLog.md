
# Version 0.4 #
- Named chat sessions: `/session name|list|resume|resumecopy|park|delete|info` commands.
- Session files promoted to `controldata/chatsessions/named/session_<slug>.json`; rename preserves old file as a frozen checkpoint.
- `/session resumecopy <old> <new>`: copy a session as a clean jumping-off point without touching the source.
- Deleting the active session automatically parks to a new unnamed chat.
- Tab completion in the UI: Tab key opens a dropdown for command names, sub-commands, and dynamic arguments (session names, test files, task names, models).
- `GET /completions` endpoint supplies live named-session and task lists to the tab-complete dropdown.
- Chat panel title displays the active session name; updated live via SSE events.
- Anaglyph title colour fix: MINI in blue (left lens), AGENT in red (right lens).
- `/deletelogs` cutoff fixes: off-by-one on date folders; stray chatsession root files now culled alongside logs and test results.
- DESIGN.md expanded: feature descriptions, named-session section, full SSE event list, correct session-ID claims.

# Version 0.3+dev #
- Added DESIGN.md to serve as a requirements document align to.
- New Sandbox button.
- Endless Chat: Chat session control and compaction of older context map elements.

# Version 0.3 #
- Web Navigate skill and adjustments to consolidate with other web skills.
- Adding Web UI, removing other modes for simplicity.
- Delegate skill
- /testtrend test result analysis
- Multiple rounds of robustness/maturity fixes
- WebUI logfile navigation

# Version 0.2 #
- Addition of WebResearch skill, to better navigate web search and analysis prompts.
- Move from blocking to queueing pending prompts.
- First end to end test runs, around 100 prompts.

# Version 0.1 - Initial baseline #
- A running framework with web search and python execution skills.
- README documentation for general and developer audiences.