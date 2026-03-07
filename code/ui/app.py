import msvcrt
import time

from .screen  import Screen
from .panel   import Panel
from .widgets import ScrollLog, TextEdit
from .keys    import TAB, CTRL_C, ALT_UP, ALT_DOWN, ALT_LEFT, ALT_RIGHT, K_UP, K_DOWN, K_PGUP, K_PGDN, read_key
from . import colors

# ====================================================================================================
# MARK: LAYOUT CONSTANTS
# ====================================================================================================

H_TOP    = 6    # ollama panel  - rows (including border)
H_BOTTOM = 3    # input panel   - rows (1 content line + 2 border)
FRAME_S  = 0.02 # ~50 fps when idle

# ====================================================================================================
# MARK: APP
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Three-panel terminal UI  -  pure stdlib, no pip required.
#
#   ┌─ Ollama ──────────────────────────────────────────┐   <- H_TOP rows
#   │  ps output / model status                         │
#   └────────────────────────────────────────────────────┘
#   ┌─ Chat ─────────────────────────────────────────────┐   <- fills remaining space
#   │  scrolling conversation log                        │
#   └────────────────────────────────────────────────────┘
#   ┌─ Input ────────────────────────────────────────────┐   <- H_BOTTOM rows
#   │ > _                                                │
#   └────────────────────────────────────────────────────┘
#
# Tab / Alt+Left / Alt+Right  cycles view-focus between Ollama and Chat.
# Up/Down/PgUp/PgDn scrolls the focused log panel.
# All printable keystrokes always route to the TextEdit.
# ----------------------------------------------------------------------------------------------------

class App:

    FOCUS_ORDER = ['ollama', 'chat']

    def __init__(self, on_submit=None):
        self.on_submit  = on_submit   # callable(text) - called on Enter
        self._focus_idx = 1           # start with Chat focused

        self.ollama_log = ScrollLog(max_lines=100)
        self.chat_log   = ScrollLog(max_lines=1000)
        self.input_edit = TextEdit(prompt='> ')

        self._screen  = Screen()
        self._panels  = {}            # name → Panel  (value objects, no OS resources)
        self._running = False

    # ====================================================================================================
    # MARK: PUBLIC API
    # ====================================================================================================

    def add_chat_line(self, text, attr=None):
        self.chat_log.add_line(text, attr if attr else colors.CHAT)

    def set_ollama_lines(self, lines):
        self.ollama_log.clear()
        for line in lines:
            self.ollama_log.add_line(line, colors.BLUE)

    def add_ollama_line(self, text, attr=None):
        self.ollama_log.add_line(text, attr if attr else colors.BLUE)

    # ====================================================================================================
    # MARK: LAYOUT
    # ====================================================================================================

    def _build_layout(self, h, w):
        h_center = max(h - H_TOP - H_BOTTOM, 3)
        focused  = self.FOCUS_ORDER[self._focus_idx]

        specs = {
            'ollama': ('Ollama', 0,              0, H_TOP,      w),
            'chat':   ('Chat',   H_TOP,           0, h_center,   w),
            'input':  ('Input',  H_TOP + h_center, 0, H_BOTTOM,   w),
        }

        for name, (title, y, x, ph, pw) in specs.items():
            if name in self._panels:
                self._panels[name].resize(y, x, ph, pw)
                self._panels[name].focused = (name == focused)
            else:
                self._panels[name] = Panel(title, y, x, ph, pw, focused=(name == focused))

    # ====================================================================================================
    # MARK: DRAW
    # ====================================================================================================

    def _draw(self):
        scr = self._screen
        scr.begin_frame()

        for panel in self._panels.values():
            panel.draw(scr)

        # Widgets draw into their panel's inner rect
        for name, widget in (('ollama', self.ollama_log),
                              ('chat',   self.chat_log)):
            iy, ix, ih, iw = self._panels[name].inner_rect()
            widget.draw(scr, iy, ix, ih, iw)

        iy, ix, ih, iw = self._panels['input'].inner_rect()
        self.input_edit.draw(scr, iy, ix, ih, iw)

        scr.render()

    # ====================================================================================================
    # MARK: FOCUS
    # ====================================================================================================

    def _cycle_focus(self, direction=1):
        self._focus_idx = (self._focus_idx + direction) % len(self.FOCUS_ORDER)
        focused_name    = self.FOCUS_ORDER[self._focus_idx]
        for name, panel in self._panels.items():
            panel.focused = (name == focused_name)

    def _focused_log(self):
        return self.ollama_log if self.FOCUS_ORDER[self._focus_idx] == 'ollama' else self.chat_log

    # ====================================================================================================
    # MARK: INPUT HANDLING
    # ====================================================================================================

    def _handle_key(self, key):
        if   key == CTRL_C:     self._running = False;         return
        if   key == TAB:        self._cycle_focus(+1);         return
        if   key == ALT_LEFT:   self._cycle_focus(-1);         return
        if   key == ALT_RIGHT:  self._cycle_focus(+1);         return
        if   key == ALT_UP:     self._focused_log().scroll_up();     return
        if   key == ALT_DOWN:   self._focused_log().scroll_down();   return
        if   key == K_UP:       self._focused_log().scroll_up();     return
        if   key == K_DOWN:     self._focused_log().scroll_down();   return
        if   key == K_PGUP:     self._focused_log().scroll_up(10);   return
        if   key == K_PGDN:     self._focused_log().scroll_down(10); return

        # Everything else goes to the text input
        submitted = self.input_edit.handle_key(key)
        if submitted:
            text = self.input_edit.value.strip()
            self.input_edit.clear()
            if text and self.on_submit:
                self.on_submit(text)

    # ====================================================================================================
    # MARK: RUN
    # ====================================================================================================

    def run(self):
        self._screen.enable()
        self._running = True
        try:
            # Initial layout build
            self._build_layout(self._screen.h or 24, self._screen.w or 80)

            while self._running:
                # begin_frame() also detects terminal resize
                resized = self._screen.begin_frame()
                if resized:
                    self._build_layout(self._screen.h, self._screen.w)

                # Re-draw every frame (diff render keeps it efficient)
                for panel in self._panels.values():
                    panel.draw(self._screen)

                for name, widget in (('ollama', self.ollama_log),
                                     ('chat',   self.chat_log)):
                    iy, ix, ih, iw = self._panels[name].inner_rect()
                    widget.draw(self._screen, iy, ix, ih, iw)

                iy, ix, ih, iw = self._panels['input'].inner_rect()
                self.input_edit.draw(self._screen, iy, ix, ih, iw)

                self._screen.render()

                # Non-blocking key poll
                if msvcrt.kbhit():
                    self._handle_key(read_key())
                else:
                    time.sleep(FRAME_S)

        finally:
            self._screen.disable()
