import msvcrt

# ====================================================================================================
# MARK: NAMED KEY CONSTANTS
# ====================================================================================================

# Printable range handled by: 32 <= ord(ch) <= 126
# Control characters
ENTER     = '\r'
BACKSPACE = '\x08'
ESC       = '\x1b'
TAB       = '\t'
CTRL_C    = '\x03'

# Extended key tokens returned by read_key()
# (never appear as raw msvcrt chars - we synthesise them)
K_UP      = 'KEY_UP'
K_DOWN    = 'KEY_DOWN'
K_LEFT    = 'KEY_LEFT'
K_RIGHT   = 'KEY_RIGHT'
K_HOME    = 'KEY_HOME'
K_END     = 'KEY_END'
K_PGUP    = 'KEY_PGUP'
K_PGDN    = 'KEY_PGDN'
K_DELETE  = 'KEY_DELETE'
K_F1      = 'KEY_F1'

ALT_UP    = 'ALT_UP'
ALT_DOWN  = 'ALT_DOWN'
ALT_LEFT  = 'ALT_LEFT'
ALT_RIGHT = 'ALT_RIGHT'

# ====================================================================================================
# MARK: KEY READING
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Windows msvcrt extended-key scan codes (getwch second byte).
# Both \x00 and \xe0 prefixes are handled.
# ----------------------------------------------------------------------------------------------------

_SCAN_NORMAL = {
    'H': K_UP,    'P': K_DOWN,   'K': K_LEFT,  'M': K_RIGHT,
    'G': K_HOME,  'O': K_END,    'I': K_PGUP,  'Q': K_PGDN,
    'S': K_DELETE,
    ';': K_F1,
}

# Alt+arrow scan codes  (prefixed by \x00)
_SCAN_ALT = {
    '\x98': ALT_UP,
    '\xa0': ALT_DOWN,
    '\x9b': ALT_LEFT,
    '\x9d': ALT_RIGHT,
}

# ----------------------------------------------------------------------------------------------------
# Read one logical key event.
# Returns a string: either a single printable/control char, or a K_* / ALT_* constant.
# Blocks until a key is available.  Check msvcrt.kbhit() first for non-blocking use.
# ----------------------------------------------------------------------------------------------------

def read_key():
    ch = msvcrt.getwch()

    # Extended key prefix
    if ch in ('\x00', '\xe0'):
        scan = msvcrt.getwch()
        if ch == '\x00':
            alt = _SCAN_ALT.get(scan)
            if alt:
                return alt
        return _SCAN_NORMAL.get(scan, scan)

    return ch
