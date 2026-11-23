"""PyInstaller 打包入口：带参数走命令行，无参数打开图形界面。"""
from __future__ import annotations

import multiprocessing
import sys

from audio_visualizer.cli import main as cli_main


if __name__ == "__main__":
    # 冻结环境下 spawn 子进程会重新执行本 exe；freeze_support 负责
    # 识别多进程启动参数并把子进程交给 worker，避免重复打开 GUI。
    multiprocessing.freeze_support()
    if len(sys.argv) > 1:
        raise SystemExit(cli_main())
    from audio_visualizer.gui import main as gui_main

    gui_main()
