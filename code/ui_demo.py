"""
Standalone demo for the retro ASCII UI framework.
Run from the code/ directory:  python ui_demo.py
"""

import sys
import os
import threading
import time

from ui.app import App
from ui     import colors

# ====================================================================================================
# MARK: DEMO CONTENT
# ====================================================================================================

OLLAMA_SAMPLE = [
    'NAME                    ID              SIZE    PROCESSOR    UNTIL',
    'llama3.2:latest         a80c4f17acd5    2.0 GB  100% GPU     4 minutes from now',
    'phi4:latest             ac896e5b8b34    9.1 GB  100% GPU     4 minutes from now',
]

CHAT_SAMPLE = [
    ('system',  'MiniAgentFramework v0.1 ready.',           None),
    ('user',    'What skills are available?',               None),
    ('agent',   'Skills: DateTime, FileAccess, Memory, SystemInfo, WebExtract, WebSearch', None),
    ('user',    'Search the web for Python curses tutorial', None),
    ('planner', '[plan]  1:WebSearch  2:WebExtract',        None),
    ('skill',   '[WebSearch]  querying: Python curses tutorial', None),
    ('skill',   '[WebExtract] extracting top result...',    None),
    ('agent',   'Here is a summary of the curses tutorial...', None),
]

# ====================================================================================================
# MARK: DEMO FEED
# ====================================================================================================

# ----------------------------------------------------------------------------------------------------
# Feeds sample lines to the UI on a background thread to simulate live agent output.
# ----------------------------------------------------------------------------------------------------

def _feed_demo(app):
    time.sleep(0.3)

    # Populate ollama panel
    app.set_ollama_lines(OLLAMA_SAMPLE)

    # Feed chat lines with a small delay between each
    role_attrs = {
        'system':  colors.DIM,
        'user':    colors.INPUT,
        'agent':   colors.NORMAL,
        'planner': colors.BLUE,
        'skill':   colors.RED,
    }

    for role, text, _ in CHAT_SAMPLE:
        attr = role_attrs.get(role, colors.NORMAL)
        prefix = {
            'system':  '  ',
            'user':    'You  \u25b6 ',
            'agent':   'Agent\u25b6 ',
            'planner': 'Plan \u25b6 ',
            'skill':   'Skill\u25b6 ',
        }.get(role, '  ')
        app.add_chat_line(prefix + text, attr)
        time.sleep(0.25)

    app.add_chat_line('')
    app.add_chat_line('  [demo complete - type a message, Tab to shift panel focus, Ctrl+C to quit]',
                      colors.DIM)


# ====================================================================================================
# MARK: ENTRY
# ====================================================================================================

def main():
    def on_submit(text):
        app.add_chat_line('You  \u25b6 ' + text, colors.INPUT)
        app.add_chat_line('Agent\u25b6 (demo) echo: ' + text, colors.NORMAL)

    app = App(on_submit=on_submit)

    feeder = threading.Thread(target=_feed_demo, args=(app,), daemon=True)
    feeder.start()

    app.run()


if __name__ == '__main__':
    main()
