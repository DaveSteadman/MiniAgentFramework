import os
import sys
import io
import ctypes
import ctypes.wintypes

# ====================================================================================================
# MARK: WINDOWS CONSOLE SETUP
# ====================================================================================================

# Flags for SetConsoleMode
_ENABLE_PROCESSED_OUTPUT            = 0x0001
_ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
_ENABLE_PROCESSED_INPUT             = 0x0001
_ENABLE_ECHO_INPUT                  = 0x0004
_ENABLE_LINE_INPUT                  = 0x0002

_k32 = ctypes.windll.kernel32

# ----------------------------------------------------------------------------------------------------

def _get_handle(std_id):
    return _k32.GetStdHandle(ctypes.wintypes.DWORD(std_id))

def _get_mode(handle):
    mode = ctypes.wintypes.DWORD(0)
    _k32.GetConsoleMode(handle, ctypes.byref(mode))
    return mode.value

def _set_mode(handle, mode):
    _k32.SetConsoleMode(handle, ctypes.wintypes.DWORD(mode))

# ====================================================================================================
# MARK: ANSI HELPERS
# ====================================================================================================

ESC = '\x1b'

def _move(row, col):   return f'{ESC}[{row + 1};{col + 1}H'
def _hide_cursor():    return f'{ESC}[?25l'
def _show_cursor():    return f'{ESC}[?25h'
def _clear_screen():   return f'{ESC}[2J{ESC}[H'
def _reset():          return f'{ESC}[0m'

# ====================================================================================================
# MARK: CELL
# ====================================================================================================

class Cell:
    __slots__ = ('char', 'attr')
    def __init__(self, char, attr):
        self.char = char
        self.attr = attr
    def __eq__(self, other):
        return self.char == other.char and self.attr == other.attr

_BLANK = Cell(' ', '')

# ====================================================================================================
# MARK: SCREEN
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Virtual character buffer with diff-based ANSI rendering.
#
# Usage per frame:
#   resized = screen.begin_frame()
#   screen.put_str(y, x, text, attr, clip_w)
#   screen.render()
#
# All drawing coordinates are 0-based (row, col).
# ----------------------------------------------------------------------------------------------------

class Screen:

    def __init__(self):
        self._h      = 0
        self._w      = 0
        self._buf    = []
        self._prev   = []
        self._stdout_handle = None
        self._stdin_handle  = None
        self._orig_out_mode = 0
        self._orig_in_mode  = 0

    # ----------------------------------------------------------------------------------------------------

    @property
    def h(self): return self._h

    @property
    def w(self): return self._w

    # ----------------------------------------------------------------------------------------------------
    # Enable VT processing, hide cursor, enter raw-ish terminal state.
    # Call once at startup before the render loop.
    # ----------------------------------------------------------------------------------------------------

    def enable(self):
        STD_OUTPUT_HANDLE = ctypes.wintypes.DWORD(-11)
        STD_INPUT_HANDLE  = ctypes.wintypes.DWORD(-10)

        self._stdout_handle = _get_handle(-11)
        self._stdin_handle  = _get_handle(-10)
        self._orig_out_mode = _get_mode(self._stdout_handle)
        self._orig_in_mode  = _get_mode(self._stdin_handle)

        # Enable VT escape code processing on stdout
        out_mode = self._orig_out_mode | _ENABLE_PROCESSED_OUTPUT | _ENABLE_VIRTUAL_TERMINAL_PROCESSING
        _set_mode(self._stdout_handle, out_mode)

        # Disable line-buffering + echo on stdin so we get chars immediately
        in_mode = self._orig_in_mode & ~(_ENABLE_ECHO_INPUT | _ENABLE_LINE_INPUT)
        _set_mode(self._stdin_handle, in_mode)

        sys.stdout.write(_hide_cursor() + _clear_screen())
        sys.stdout.flush()

    # ----------------------------------------------------------------------------------------------------
    # Restore terminal to its original state.  Call on exit / exception.
    # ----------------------------------------------------------------------------------------------------

    def disable(self):
        if self._stdout_handle:
            _set_mode(self._stdout_handle, self._orig_out_mode)
        if self._stdin_handle:
            _set_mode(self._stdin_handle, self._orig_in_mode)
        sys.stdout.write(_show_cursor() + _reset() + '\n')
        sys.stdout.flush()

    # ----------------------------------------------------------------------------------------------------
    # Call at the start of each frame.
    # Detects terminal resize, rebuilds buffers, clears the write buffer.
    # Returns True if a resize occurred this frame.
    # ----------------------------------------------------------------------------------------------------

    def begin_frame(self):
        size = os.get_terminal_size()
        h, w = size.lines, size.columns

        resized = (h != self._h or w != self._w)
        if resized:
            self._h = h;  self._w = w
            self._buf  = [[Cell(' ', '') for _ in range(w)] for _ in range(h)]
            # Mark prev as dirty so everything redraws on resize
            self._prev = [[Cell('\x00', '\x00') for _ in range(w)] for _ in range(h)]

        # Clear write buffer to blank
        for row in self._buf:
            for i in range(self._w):
                row[i] = _BLANK

        return resized

    # ----------------------------------------------------------------------------------------------------

    def put(self, y, x, char, attr=''):
        if 0 <= y < self._h and 0 <= x < self._w:
            self._buf[y][x] = Cell(char, attr)

    def put_str(self, y, x, text, attr='', clip_w=None):
        max_x = (x + clip_w) if clip_w else self._w
        for i, ch in enumerate(text):
            cx = x + i
            if cx >= max_x:
                break
            self.put(y, cx, ch, attr)

    def fill_row(self, y, x, width, char=' ', attr=''):
        for i in range(width):
            self.put(y, x + i, char, attr)

    # ----------------------------------------------------------------------------------------------------
    # Diff render: output only cells that differ from the previous frame.
    # ----------------------------------------------------------------------------------------------------

    def render(self):
        out        = io.StringIO()
        last_r     = -1
        last_c     = -1
        last_attr  = None

        for row in range(self._h):
            for col in range(self._w):
                cell = self._buf[row][col]
                prev = self._prev[row][col]
                if cell == prev:
                    continue

                # Emit cursor move unless it's the next sequential column
                if row != last_r or col != last_c + 1:
                    out.write(_move(row, col))
                last_r = row;  last_c = col

                # Emit attr change
                if cell.attr != last_attr:
                    if cell.attr:
                        out.write(f'{ESC}[0m{cell.attr}')
                    else:
                        out.write(f'{ESC}[0m')
                    last_attr = cell.attr

                out.write(cell.char)
                self._prev[row][col] = Cell(cell.char, cell.attr)

        if last_attr is not None:
            out.write(f'{ESC}[0m')

        content = out.getvalue()
        if content:
            sys.stdout.write(content)
            sys.stdout.flush()
