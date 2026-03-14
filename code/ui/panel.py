from . import colors

# ====================================================================================================
# MARK: BOX CHARACTERS
# ====================================================================================================

# Single-line box drawing
TL = '\u250c';  TR = '\u2510'
BL = '\u2514';  BR = '\u2518'
H  = '\u2500';  V  = '\u2502'

# ====================================================================================================
# MARK: PANEL
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# A bordered panel occupying a region of the terminal.
# Owns its curses window; call resize() to rebuild after terminal resize.
# The inner content area is one cell inside the border on all sides.
# ----------------------------------------------------------------------------------------------------

class Panel:

    def __init__(self, title, y, x, h, w, focused=False):
        self.title       = title
        self.focused     = focused
        self.scroll_hint = False   # when True, show PgUp/PgDn on the bottom border
        self.y = y;  self.x = x
        self.h = max(h, 3)
        self.w = max(w, 4)

    # ----------------------------------------------------------------------------------------------------

    def resize(self, y, x, h, w):
        self.y = y;  self.x = x
        self.h = max(h, 3)
        self.w = max(w, 4)

    # ----------------------------------------------------------------------------------------------------
    # Return the (y, x, h, w) of the inner content area.
    # ----------------------------------------------------------------------------------------------------

    def inner_rect(self):
        return (self.y + 1, self.x + 1, max(self.h - 2, 1), max(self.w - 2, 1))

    # ----------------------------------------------------------------------------------------------------
    # Draw border and title into the shared Screen buffer.
    # ----------------------------------------------------------------------------------------------------

    def draw(self, screen):
        ba = colors.BORDER_HI if self.focused else colors.BORDER
        ta = colors.TITLE_HI  if self.focused else colors.TITLE

        y, x, h, w = self.y, self.x, self.h, self.w

        # Top border
        screen.put(y, x, TL, ba)
        screen.put_str(y, x + 1, H * (w - 2), ba)
        screen.put(y, x + w - 1, TR, ba)

        # Sides
        for row in range(1, h - 1):
            screen.put(y + row, x,         V, ba)
            screen.put(y + row, x + w - 1, V, ba)

        # Bottom border
        screen.put(y + h - 1, x,         BL, ba)
        screen.put_str(y + h - 1, x + 1, H * (w - 2), ba)
        screen.put(y + h - 1, x + w - 1, BR, ba)

        # Title centred on top border
        if self.title:
            label     = f' {self.title} '
            max_title = w - 4
            if len(label) > max_title:
                label = label[:max_title]
            col = x + (w - len(label)) // 2
            screen.put_str(y, col, label, ta)

        # PgUp on top-right / PgDn on bottom-right border corners
        if self.scroll_hint and w >= 18:
            screen.put_str(y,         x + w - 7, ' PgUp ', ba)
            screen.put_str(y + h - 1, x + w - 7, ' PgDn ', ba)
