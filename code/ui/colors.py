from .screen import ESC

# ====================================================================================================
# MARK: ANSI ATTRIBUTE STRINGS
# ====================================================================================================

# Each constant is a complete SGR sequence that resets then applies the desired style.
# Compose into a Cell attr field.  Empty string = terminal default (white on black expected).

# ----------------------------------------------------------------------------------------------------
# Greys  (bold = bright white, dim = dark grey)
# ----------------------------------------------------------------------------------------------------

NORMAL    = f'{ESC}[0;37m'          # white, no bold
DIM       = f'{ESC}[0;2;37m'        # dim white  →  dark grey

# ----------------------------------------------------------------------------------------------------
# Panel chrome
# ----------------------------------------------------------------------------------------------------

BORDER    = f'{ESC}[0;2;37m'        # unfocused border  - dark grey
BORDER_HI = f'{ESC}[0;1;37m'        # focused border    - bright white bold
TITLE     = f'{ESC}[0;1;36m'        # panel title       - bold cyan  (anaglyph blue)
TITLE_HI  = f'{ESC}[0;1;37m'        # focused title     - bold white

# ----------------------------------------------------------------------------------------------------
# Content
# ----------------------------------------------------------------------------------------------------

CHAT      = f'{ESC}[0;37m'          # chat body text    - white
PROMPT    = f'{ESC}[0;1;36m'        # input prompt "> " - bold cyan
INPUT     = f'{ESC}[0;1;37m'        # typed input text  - bright white
CARET     = f'{ESC}[0;7m'           # cursor block      - reverse video

# ----------------------------------------------------------------------------------------------------
# Anaglyph accents
# ----------------------------------------------------------------------------------------------------

RED       = f'{ESC}[0;1;31m'        # bold red   - skills, warnings, values
BLUE      = f'{ESC}[0;36m'          # cyan       - anaglyph blue, labels, keys
MAGENTA   = f'{ESC}[0;1;35m'        # magenta    - planner output

# ----------------------------------------------------------------------------------------------------
# Timeline
# ----------------------------------------------------------------------------------------------------

TIMELINE_NOW  = f'{ESC}[0;1;33m'   # bold yellow  - current-minute marker (► HH:MM)
TIMELINE_TASK = f'{ESC}[0;1;32m'   # bold green   - minute slot that has a scheduled task
TIMELINE_TICK = f'{ESC}[0;2;37m'   # dim white    - empty minute tick
