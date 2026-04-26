"""Root launcher for MiniAgentFramework.

Keeps startup consistent with the other repos so MiniAgentFramework can be started with:

    python ./main.py
"""

from __future__ import annotations

import runpy
from pathlib import Path


if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).parent / 'code' / 'main.py'), run_name='__main__')