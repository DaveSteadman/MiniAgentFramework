import sys

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
# (never appear as raw chars - we synthesise them from platform escape sequences)
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
# MARK: PLATFORM IMPLEMENTATIONS
# ====================================================================================================

if sys.platform == 'win32':
    import msvcrt

    # Windows msvcrt extended-key scan codes (getwch second byte).
    # Both \x00 and \xe0 prefixes are handled.
    _SCAN_NORMAL = {
        'H': K_UP,    'P': K_DOWN,   'K': K_LEFT,  'M': K_RIGHT,
        'G': K_HOME,  'O': K_END,    'I': K_PGUP,  'Q': K_PGDN,
        'S': K_DELETE,
        ';': K_F1,
    }

    # Alt+arrow scan codes (prefixed by \x00)
    _SCAN_ALT = {
        '\x98': ALT_UP,
        '\xa0': ALT_DOWN,
        '\x9b': ALT_LEFT,
        '\x9d': ALT_RIGHT,
    }

    def kbhit() -> bool:
        """Return True if a key is waiting (non-blocking)."""
        return msvcrt.kbhit()

    def read_key() -> str:
        """Read one logical key event (blocks until a key is available).
        Returns a single printable/control char, or a K_* / ALT_* constant.
        """
        ch = msvcrt.getwch()
        if ch in ('\x00', '\xe0'):
            scan = msvcrt.getwch()
            if ch == '\x00':
                alt = _SCAN_ALT.get(scan)
                if alt:
                    return alt
            return _SCAN_NORMAL.get(scan, scan)
        return ch

else:
    import os
    import select

    # ANSI escape sequences emitted by Linux/macOS terminals for special keys.
    # Matched against the bytes following the leading \x1b.
    _UNIX_ESCAPE_MAP = {
        '[A':    K_UP,
        '[B':    K_DOWN,
        '[C':    K_RIGHT,
        '[D':    K_LEFT,
        '[H':    K_HOME,
        '[F':    K_END,
        '[5~':   K_PGUP,
        '[6~':   K_PGDN,
        '[3~':   K_DELETE,
        'OP':    K_F1,
        '[11~':  K_F1,
        '[1;3A': ALT_UP,
        '[1;3B': ALT_DOWN,
        '[1;3C': ALT_RIGHT,
        '[1;3D': ALT_LEFT,
    }

    def _read_escape_tail() -> str:
        """Drain an escape sequence, reading with 50 ms inter-char timeout."""
        buf = ''
        fd = sys.stdin.fileno()
        while True:
            r, _, _ = select.select([fd], [], [], 0.05)
            if not r:
                break
            buf += os.read(fd, 1).decode('utf-8', errors='replace')
        return buf

    def kbhit() -> bool:
        """Return True if a key is waiting (non-blocking)."""
        r, _, _ = select.select([sys.stdin.fileno()], [], [], 0)
        return bool(r)

    def read_key() -> str:
        """Read one logical key event (blocks until a key is available).
        Returns a single printable/control char, or a K_* / ALT_* constant.
        """
        ch = os.read(sys.stdin.fileno(), 1).decode('utf-8', errors='replace')
        if ch != ESC:
            return ch
        tail = _read_escape_tail()
        if not tail:
            return ESC  # lone Escape keypress
        return _UNIX_ESCAPE_MAP.get(tail, ESC)
