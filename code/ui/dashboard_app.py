# ====================================================================================================
# MARK: OVERVIEW
# ====================================================================================================
# DashboardApp: combined scheduler timeline + live log + chat terminal dashboard.
#
# Layout (example 120×40 terminal):
#
#   ┌─ Ollama ─────────────────────────────────────────────────────────────────────┐  H_TOP rows
#   │  host: http://localhost:11434                                                │
#   │  NAME            SIZE          PROCESSOR     UNTIL                          │
#   │  gpt-oss:20b     16.4 GB       100% GPU      2026-...                       │
#   ├─ Timeline ──────┬─ [Log]  Chat ─────────────────────────────────────────────┤  fills middle
#   │  HH:MM tasks    │  Tab cycles Log ↔ Chat                                    │
#   │  ►HH:MM  NOW    │  Up/Down/PgUp/PgDn scrolls active tab                     │
#   │  HH:MM future   │                                                            │
#   ├─────────────────┴────────────────────────────────────────────────────────────┤
#   │  > chat input                                                                │  H_BOTTOM rows
#   └──────────────────────────────────────────────────────────────────────────────┘
#
# Keys:
#   Tab             toggle active main-area tab: Log ↔ Chat
#   Up/Down         scroll the active tab one line
#   PgUp/PgDn       scroll the active tab ten lines
#   Ctrl+C          graceful shutdown (sets shutdown_event, then exits the loop)
#   Any printable   routed to the chat input bar
#   Enter           submit the typed input (calls on_submit callback)
#
# Thread safety:
#   The public API methods (add_chat_line, add_log_line, set_ollama_lines,
#   set_active_tab, stop) may be called from any thread.  They modify only
#   ScrollLog instances; Python's GIL, combined with the slice-copy used in
#   ScrollLog.draw(), makes this safe without an explicit lock.
#
# Related modules:
#   - main.py         run_dashboard_mode constructs this app and starts background threads
#   - widgets.py      TimelineWidget, ScrollLog, TextEdit
#   - scheduler.py    task schedule data passed in at construction time
# ====================================================================================================


# ====================================================================================================
# MARK: IMPORTS
# ====================================================================================================
import time
from datetime import datetime

from .screen  import Screen
from .panel   import Panel
from .widgets import ScrollLog, TextEdit, TimelineWidget
from .keys    import TAB, CTRL_C, K_UP, K_DOWN, K_PGUP, K_PGDN, kbhit, read_key
from . import colors


# ====================================================================================================
# MARK: LAYOUT CONSTANTS
# ====================================================================================================
W_TIMELINE = 20    # left timeline column total width, including its border
H_TOP      = 5     # ollama ps bar total height, including border (3 inner content rows)
H_BOTTOM   = 3     # chat input bar total height, including border
FRAME_S    = 0.02  # target frame interval (~50 fps)


# ====================================================================================================
# MARK: DASHBOARD APP
# ====================================================================================================
class DashboardApp:

    TAB_LOG  = 'Log'
    TAB_CHAT = 'Chat'

    # ----------------------------------------------------------------------------------------------------
    def __init__(self, tasks=None, last_run=None, on_submit=None, shutdown_event=None, task_queue=None, chat_history_entries=None):
        """
        tasks                list of enabled task dicts from task_schedule.json
        last_run             mutable dict {task_name: datetime|None} shared with the scheduler thread
        on_submit            callable(text: str) invoked when the user presses Enter in the input bar
        shutdown_event       threading.Event; when set the UI loop exits cleanly on the next frame
        task_queue           TaskQueue singleton from scheduler; used to show running indicator
        chat_history_entries mutable list[str] of prior inputs (oldest-first); shared with caller
        """
        self.tasks          = tasks or []
        self.last_run       = last_run or {}
        self.run_history: list = []    # (task_name, datetime) for each run completed this session
        self.on_submit      = on_submit
        self.shutdown_event = shutdown_event
        self._task_queue    = task_queue

        self.ollama_log = ScrollLog(max_lines=50)
        self.chat_log   = ScrollLog(max_lines=2000)
        self.runlog_log = ScrollLog(max_lines=2000)
        self.input_edit = TextEdit(prompt='> ', history=chat_history_entries)
        self._timeline  = TimelineWidget()
        self._active_tab = self.TAB_LOG        # start on Log so scheduler output is visible

        self._screen  = Screen()
        self._panels: dict[str, Panel] = {}
        self._running = False

    # ====================================================================================================
    # MARK: PUBLIC API  (safe to call from background threads)
    # ====================================================================================================

    def add_chat_line(self, text: str, attr=None) -> None:
        self.chat_log.add_line(text, attr if attr else colors.CHAT)

    def add_log_line(self, text: str, attr=None) -> None:
        self.runlog_log.add_line(text, attr if attr else colors.DIM)

    def set_ollama_lines(self, lines: list[str]) -> None:
        self.ollama_log.clear()
        for line in lines:
            self.ollama_log.add_line(line, colors.BLUE)

    def set_active_tab(self, tab_name: str) -> None:
        if tab_name in (self.TAB_LOG, self.TAB_CHAT):
            self._active_tab = tab_name
            if 'main' in self._panels:
                self._panels['main'].title = self._main_title()

    def record_run(self, name: str, when: datetime) -> None:
        self.run_history.append((name, when))

    def stop(self) -> None:
        self._running = False

    # ====================================================================================================
    # MARK: LAYOUT
    # ====================================================================================================

    def _build_layout(self, h: int, w: int) -> None:
        h_mid  = max(h - H_TOP - H_BOTTOM, 3)
        w_main = max(w - W_TIMELINE, 10)

        specs = {
            'ollama':   ('Ollama',           0,             0,           H_TOP,    w       ),
            'timeline': ('Timeline',         H_TOP,         0,           h_mid,    W_TIMELINE),
            'main':     (self._main_title(), H_TOP,         W_TIMELINE,  h_mid,    w_main  ),
            'input':    ('Input',            H_TOP + h_mid, 0,           H_BOTTOM, w       ),
        }

        for name, (title, py, px, ph, pw) in specs.items():
            if name in self._panels:
                self._panels[name].resize(py, px, ph, pw)
                self._panels[name].title = title
            else:
                self._panels[name] = Panel(title, py, px, ph, pw)

        self._panels['main'].scroll_hint = True

    # ----------------------------------------------------------------------------------------------------

    def _main_title(self) -> str:
        return '  '.join(
            f'[{t}]' if t == self._active_tab else t
            for t in (self.TAB_LOG, self.TAB_CHAT)
        )

    # ====================================================================================================
    # MARK: INPUT HANDLING
    # ====================================================================================================

    def _handle_key(self, key: str) -> None:
        if key == CTRL_C:
            self._running = False
            if self.shutdown_event:
                self.shutdown_event.set()
            return

        if key == TAB:
            self._active_tab = (
                self.TAB_CHAT if self._active_tab == self.TAB_LOG else self.TAB_LOG
            )
            if 'main' in self._panels:
                self._panels['main'].title = self._main_title()
            return

        active_log = self.runlog_log if self._active_tab == self.TAB_LOG else self.chat_log
        if key == K_UP:
            # In Chat tab K_UP/K_DOWN cycle the input-bar history; in Log tab they scroll.
            if self._active_tab == self.TAB_CHAT:
                self.input_edit.handle_key(key)
            else:
                active_log.scroll_up()
            return
        if key == K_DOWN:
            if self._active_tab == self.TAB_CHAT:
                self.input_edit.handle_key(key)
            else:
                active_log.scroll_down()
            return
        if key == K_PGUP: active_log.scroll_up(10);   return
        if key == K_PGDN: active_log.scroll_down(10); return

        submitted = self.input_edit.handle_key(key)
        if submitted:
            text = self.input_edit.value.strip()
            self.input_edit.clear()
            if text and self.on_submit:
                self.on_submit(text)

    # ====================================================================================================
    # MARK: RUN LOOP
    # ====================================================================================================

    def run(self) -> None:
        self._screen.enable()
        self._running = True
        try:
            self._build_layout(self._screen.h or 24, self._screen.w or 80)

            while self._running:
                now     = datetime.now()
                now_min = now.replace(second=0, microsecond=0)
                mins_next = TimelineWidget._minutes_to_next(self.tasks, self.last_run, now_min)

                resized = self._screen.begin_frame()
                if resized:
                    self._build_layout(self._screen.h, self._screen.w)

                # ---- draw panels ----
                for panel in self._panels.values():
                    panel.draw(self._screen)

                # Ollama ps bar
                iy, ix, ih, iw = self._panels['ollama'].inner_rect()
                self.ollama_log.draw(self._screen, iy, ix, ih, iw)

                # Vertical timeline
                iy, ix, ih, iw = self._panels['timeline'].inner_rect()

                # Build queue display lines (bottom of the timeline column, expands/contracts).
                if self._task_queue:
                    qs            = self._task_queue.get_state()
                    active_item   = qs.get("active")
                    pending_items = qs.get("pending", [])
                else:
                    active_item   = None
                    pending_items = []

                queue_lines: list[tuple[str, str]] = []
                if active_item:
                    name = active_item.get("name", "?")
                    queue_lines.append((f"\u25b6 {name}", colors.TIMELINE_NOW))
                for item in pending_items:
                    name = item.get("name", "?")
                    queue_lines.append((f"  \u00b7 {name}", colors.TIMELINE_TASK))

                # When there are queue items, reserve an extra row for the separator line.
                sep_rows    = 1 if queue_lines else 0
                queue_rows  = len(queue_lines)
                timeline_h  = max(ih - queue_rows - sep_rows, 1)
                self._timeline.draw(self._screen, iy, ix, timeline_h, iw,
                                    self.tasks, self.last_run, now, running=False,
                                    run_history=self.run_history)
                if sep_rows:
                    sep_row   = iy + timeline_h
                    label     = " Queue "
                    fill_l    = max(iw - len(label), 0)
                    sep_text  = ("\u2500" * (fill_l // 2) + label + "\u2500" * (fill_l - fill_l // 2))[:iw]
                    self._screen.put_str(sep_row, ix, sep_text.ljust(iw)[:iw], colors.TIMELINE_TICK, clip_w=iw)
                for i, (line, attr) in enumerate(queue_lines):
                    self._screen.put_str(iy + timeline_h + sep_rows + i, ix, line.ljust(iw)[:iw], attr, clip_w=iw)

                # Main area (active tab)
                iy, ix, ih, iw = self._panels['main'].inner_rect()
                active_log = self.runlog_log if self._active_tab == self.TAB_LOG else self.chat_log
                active_log.draw(self._screen, iy, ix, ih, iw)

                # Input bar
                iy, ix, ih, iw = self._panels['input'].inner_rect()
                self.input_edit.draw(self._screen, iy, ix, ih, iw)

                self._screen.render()
                # ---- end draw ----

                if kbhit():
                    self._handle_key(read_key())
                else:
                    time.sleep(FRAME_S)

                # Honour an externally-set shutdown (e.g. from SIGINT handler)
                if self.shutdown_event and self.shutdown_event.is_set():
                    self._running = False

        finally:
            self._screen.disable()
