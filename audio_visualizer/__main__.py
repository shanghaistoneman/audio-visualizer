"""python -m audio_visualizer：带参数走命令行，无参数直接打开界面。"""
from __future__ import annotations

import sys

from .cli import main


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(main())
    from .gui import main as gui_main

    gui_main()
