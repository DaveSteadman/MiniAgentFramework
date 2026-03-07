from . import colors

# ====================================================================================================
# MARK: SCROLL LOG
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Append-only scrolling log of text lines, each with its own ANSI color attribute string.
# Normally pinned to the bottom (latest entry visible).  Scroll up with scroll_up/down.
# ----------------------------------------------------------------------------------------------------

class ScrollLog:

    def __init__(self, max_lines=500):
        self._lines  = []       # list of (text, attr)
        self._max    = max_lines
        self._scroll = 0        # 0 = bottom; positive = scrolled up N rows

    # ----------------------------------------------------------------------------------------------------

    def add_line(self, text, attr=None):
        if attr is None:
            attr = colors.CHAT
        self._lines.append((str(text), attr))
        if len(self._lines) > self._max:
            self._lines.pop(0)

    def clear(self):
        self._lines  = []
        self._scroll = 0

    def scroll_up(self, n=1):   self._scroll = min(self._scroll + n, max(0, len(self._lines) - 1))
    def scroll_down(self, n=1): self._scroll = max(self._scroll - n, 0)
    def scroll_to_bottom(self): self._scroll = 0

    # ----------------------------------------------------------------------------------------------------
    # Draw into the shared Screen buffer at the given inner rect coordinates.
    # ----------------------------------------------------------------------------------------------------

    def draw(self, screen, y, x, h, w):
        if not self._lines or h <= 0 or w <= 0:
            return

        total   = len(self._lines)
        end     = total - self._scroll
        start   = max(0, end - h)
        visible = self._lines[start:end]

        for row, (text, attr) in enumerate(visible):
            screen.put_str(y + row, x, text, attr, clip_w=w)

        # Scroll indicator in top-right when not at bottom
        if self._scroll > 0:
            indicator = f'\u2191{self._scroll}'[:4]
            screen.put_str(y, x + w - len(indicator), indicator, colors.BLUE)


# ====================================================================================================
# MARK: TEXT EDIT
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Single-line text input with a visible cursor block.
# Call handle_key(key) from the app event loop; returns True if Enter was pressed.
# ----------------------------------------------------------------------------------------------------

class TextEdit:

    def __init__(self, prompt='> ', max_len=1024):
        self._buf    = []       # list of chars
        self._cursor = 0
        self._prompt = prompt
        self._max    = max_len
        self.locked   = False   # when True input is suppressed
        self.lock_msg = ''     # message shown in the bar while locked

    # ----------------------------------------------------------------------------------------------------

    @property
    def value(self):
        return ''.join(self._buf)

    def clear(self):
        self._buf    = []
        self._cursor = 0

    # ----------------------------------------------------------------------------------------------------
    # Process a key token (string from keys.read_key()).
    # Returns True when Enter is pressed.
    # ----------------------------------------------------------------------------------------------------

    def handle_key(self, key):
        if self.locked:
            return False

        from . import keys

        if key == keys.ENTER:                   return True

        if key == keys.BACKSPACE:
            if self._cursor > 0:
                self._cursor -= 1
                del self._buf[self._cursor]

        elif key == keys.K_DELETE:
            if self._cursor < len(self._buf):
                del self._buf[self._cursor]

        elif key == keys.K_LEFT:  self._cursor = max(0,               self._cursor - 1)
        elif key == keys.K_RIGHT: self._cursor = min(len(self._buf),  self._cursor + 1)
        elif key == keys.K_HOME:  self._cursor = 0
        elif key == keys.K_END:   self._cursor = len(self._buf)

        elif isinstance(key, str) and len(key) == 1 and 32 <= ord(key) <= 126:
            if len(self._buf) < self._max:
                self._buf.insert(self._cursor, key)
                self._cursor += 1

        return False

    # ----------------------------------------------------------------------------------------------------
    # Draw into the shared Screen buffer at the given inner rect coordinates (single row).
    # ----------------------------------------------------------------------------------------------------

    def draw(self, screen, y, x, h, w):
        if self.locked:
            msg = self.lock_msg or '  [chat locked]'
            screen.put_str(y, x, msg[:w].ljust(w), colors.DIM, clip_w=w)
            return

        prompt = self._prompt
        text   = self.value
        px     = len(prompt)
        avail  = max(w - px, 1)
        cpos   = self._cursor

        # Pan view so cursor stays visible
        start = max(0, cpos - avail + 1)
        view  = text[start:start + avail]
        vcur  = cpos - start

        screen.put_str(y, x,       prompt,            colors.PROMPT,  clip_w=w)
        screen.put_str(y, x + px,  view.ljust(avail), colors.INPUT,   clip_w=avail)

        # Cursor block overwrites the character at the cursor position
        cur_ch = view[vcur] if vcur < len(view) else ' '
        screen.put(y, x + px + vcur, cur_ch, colors.CARET)


# ====================================================================================================
# MARK: LABEL
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Static or dynamically-updated single line of text.
# ----------------------------------------------------------------------------------------------------

class Label:

    def __init__(self, text='', attr=None):
        self._text = text
        self._attr = attr if attr is not None else colors.NORMAL

    def set(self, text):
        self._text = text

    def draw(self, screen, y, x, h, w):
        screen.put_str(y, x, self._text, self._attr, clip_w=w)


# ====================================================================================================
# MARK: TIMELINE WIDGET
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Vertical minute-resolution timeline centred on the current time.
#
# The NOW row sits at h//2 and is marked with ►.  Past minutes appear above it;
# future minutes below.  Any task whose schedule fires at a given minute is
# annotated on that row and draws in a distinct highlight colour.
# ----------------------------------------------------------------------------------------------------

class TimelineWidget:

    _PREFIX_W = 7   # ►/space (1) + HH:MM (5) + space (1)

    def draw(self, screen, y, x, h, w, tasks, last_run, now, running=False):
        from datetime import timedelta

        now_min = now.replace(second=0, microsecond=0)
        now_row = h // 2

        task_shown = False

        for row_offset in range(h):
            minute_offset = row_offset - now_row
            slot_dt       = now_min + timedelta(minutes=minute_offset)
            draw_row      = y + row_offset

            hhmm      = slot_dt.strftime("%H:%M")
            task_name = self._task_at(tasks, last_run, slot_dt, now_min)
            abbrev    = task_name[:max(0, w - self._PREFIX_W)] if task_name else ""

            if task_name:
                task_shown = True

            if minute_offset == 0:
                text = ("\u25ba" + hhmm + (f" {abbrev}" if abbrev else ""))[:w]
                screen.put_str(draw_row, x, text.ljust(w)[:w], colors.TIMELINE_NOW,  clip_w=w)
            else:
                text = (" "     + hhmm + (f" {abbrev}" if abbrev else ""))[:w]
                attr = colors.TIMELINE_TASK if task_name else colors.TIMELINE_TICK
                screen.put_str(draw_row, x, text.ljust(w)[:w], attr, clip_w=w)

        # Overwrite the bottom row with status when no task is visible in the window.
        if not task_shown and h > 0:
            if running:
                label = " \u25b6 running"
                screen.put_str(y + h - 1, x, label.ljust(w)[:w], colors.TIMELINE_NOW, clip_w=w)
            else:
                mins = self._minutes_to_next(tasks, last_run, now_min)
                if mins is not None:
                    label = f" next:{mins}m" if mins > 0 else " next:now"
                    screen.put_str(y + h - 1, x, label.ljust(w)[:w], colors.TIMELINE_TASK, clip_w=w)

    # ----------------------------------------------------------------------------------------------------

    @staticmethod
    def _minutes_to_next(tasks, last_run, now_min):
        """Return whole minutes from now_min to the nearest upcoming task firing, or None."""
        from datetime import timedelta
        min_diff = None
        for task in tasks:
            sched = task.get("schedule", {})
            stype = sched.get("type", "")
            name  = task.get("name", "")

            if stype == "daily":
                raw = sched.get("time", "00:00")
                try:
                    hh, mm = map(int, raw.split(":"))
                except ValueError:
                    continue
                candidate = now_min.replace(hour=hh, minute=mm)
                if candidate <= now_min:
                    candidate += timedelta(days=1)
                diff = int((candidate - now_min).total_seconds() / 60)

            elif stype == "interval":
                interval_m = sched.get("minutes", 60)
                lr = last_run.get(name)
                if lr is None:
                    diff = 0
                else:
                    next_fire = lr.replace(second=0, microsecond=0) + timedelta(minutes=interval_m)
                    diff = max(0, int((next_fire - now_min).total_seconds() / 60))

            else:
                continue

            if min_diff is None or diff < min_diff:
                min_diff = diff

        return min_diff

    @staticmethod
    def _task_at(tasks, last_run, slot_dt, now_min):
        """Return the name of the first task whose schedule fires at slot_dt, else ''."""
        from datetime import timedelta

        for task in tasks:
            sched = task.get("schedule", {})
            stype = sched.get("type", "")
            name  = task.get("name", "")

            if stype == "daily":
                raw = sched.get("time", "00:00")
                try:
                    hh, mm = map(int, raw.split(":"))
                except ValueError:
                    continue
                if slot_dt.hour == hh and slot_dt.minute == mm:
                    return name

            elif stype == "interval":
                interval_m = sched.get("minutes", 60)
                lr         = last_run.get(name)
                if lr is None:
                    # Fires immediately on startup → mark at NOW
                    if slot_dt == now_min:
                        return name
                else:
                    next_fire = lr.replace(second=0, microsecond=0) + timedelta(minutes=interval_m)
                    if slot_dt == next_fire:
                        return name

        return ""
