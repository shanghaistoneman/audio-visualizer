"""界面下拉选项：中文名称 + 对文件大小/耗时的影响提示。"""
from __future__ import annotations

from .effects import BAR_OPTIONS, GLOW_OPTIONS, MODE_NAMES, MODES, THEMES
from .encoder import FORMATS

# 分辨率显示文本 -> (宽, 高)
SIZES: dict[str, tuple[int, int]] = {
    "1920 × 1080（横屏高清·文件大、耗时极长）": (1920, 1080),
    "1280 × 720（横屏流畅·文件中等、耗时中等）": (1280, 720),
    "1080 × 1920（竖屏短视频·文件大、耗时长）": (1080, 1920),
    "720 × 1280（竖屏流畅·文件中等、耗时中等）": (720, 1280),
    "1080 × 1080（方形·文件较大、耗时较长）": (1080, 1080),
    "640 × 640（手机/快速预览·文件小、耗时短）": (640, 640),
}

_MODE_IMPACT: dict[str, str] = {
    "bottom": "文件小、耗时短",
    "mirror": "文件中等、耗时短",
    "circle": "文件中等、耗时中等",
    "dual_ring": "文件较大、耗时中等",
    "spiral": "文件较大、耗时较长",
    "waveform": "文件小、耗时短",
    "tunnel": "文件中等、耗时中等",
    "particles": "文件大、耗时长",
}

MODE_OPTIONS: list[str] = [
    f"{MODE_NAMES[k]}（{_MODE_IMPACT[k]}）" for k in MODES
]
MODE_BY_LABEL: dict[str, str] = {
    f"{MODE_NAMES[k]}（{_MODE_IMPACT[k]}）": k for k in MODES
}
MODE_LABEL_BY_KEY: dict[str, str] = {v: k for k, v in MODE_BY_LABEL.items()}

_THEME_IMPACT = "大小无影响、耗时无影响"
THEME_OPTIONS: list[str] = [f"{name}（{_THEME_IMPACT}）" for name in THEMES.values()]
THEME_BY_LABEL: dict[str, str] = {
    f"{name}（{_THEME_IMPACT}）": key for key, name in THEMES.items()
}
THEME_LABEL_BY_KEY: dict[str, str] = {v: k for k, v in THEME_BY_LABEL.items()}

FPS_VALUES: dict[str, str] = {
    "24（文件小、耗时短）": "24",
    "30（文件中等、耗时中等）": "30",
    "60（文件大、耗时长）": "60",
}
FPS_OPTIONS: list[str] = list(FPS_VALUES)
FPS_LABEL_BY_VALUE: dict[str, str] = {v: k for k, v in FPS_VALUES.items()}

_BARS_IMPACT = {
    32: "文件略小、耗时略短",
    64: "文件小、耗时短",
    96: "文件中等、耗时中等",
    128: "文件略大、耗时略长",
    192: "文件大、耗时长",
}
BARS_VALUES: dict[str, str] = {
    f"{b}（{_BARS_IMPACT[b]}）": str(b) for b in BAR_OPTIONS
}
BARS_OPTIONS: list[str] = list(BARS_VALUES)
BARS_LABEL_BY_VALUE: dict[str, str] = {v: k for k, v in BARS_VALUES.items()}

_GLOW_IMPACT = {
    0.0: "文件小、耗时短",
    0.5: "文件略大、耗时略长",
    1.0: "文件中等、耗时中等",
    1.5: "文件较大、耗时较长",
    2.0: "文件大、耗时长",
}
GLOW_VALUES: dict[str, str] = {
    f"{g}（{_GLOW_IMPACT[g]}）": str(g) for g in GLOW_OPTIONS
}
GLOW_OPTIONS: list[str] = list(GLOW_VALUES)
GLOW_LABEL_BY_VALUE: dict[str, str] = {v: k for k, v in GLOW_VALUES.items()}

_FORMAT_IMPACT = {
    "mov": "文件极大、耗时短",
    "webm": "文件小、耗时长",
    "mp4-matte": "文件较大、耗时较长",
    "mp4-green": "文件小、耗时短",
    "mp4-black": "文件小、耗时短",
}
FORMAT_OPTIONS: list[str] = [
    f"{info['label']}（{_FORMAT_IMPACT[key]}）" for key, info in FORMATS.items()
]
FORMAT_BY_LABEL: dict[str, str] = {
    f"{info['label']}（{_FORMAT_IMPACT[key]}）": key for key, info in FORMATS.items()
}
FORMAT_LABEL_BY_KEY: dict[str, str] = {v: k for k, v in FORMAT_BY_LABEL.items()}

# 并行进程数：显示文本 -> 内部值（0=自动按 CPU 核心数）
_WORKERS_IMPACT = {
    0: "自动（推荐，按 CPU 核心数）",
    1: "单进程（最稳，慢）",
    2: "2 进程",
    4: "4 进程",
    6: "6 进程",
    8: "8 进程",
}
WORKERS_VALUES: dict[str, str] = {
    text: str(value) for value, text in _WORKERS_IMPACT.items()
}
WORKERS_OPTIONS: list[str] = list(WORKERS_VALUES)
WORKERS_LABEL_BY_VALUE: dict[str, str] = {
    v: k for k, v in WORKERS_VALUES.items()
}


def label_for_mode(key: str) -> str:
    return MODE_NAMES.get(key, key)


def label_for_theme(key: str) -> str:
    return THEMES.get(key, key)
