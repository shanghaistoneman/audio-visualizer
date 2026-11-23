"""基于当前 CPU 实测基准，预估视频生成耗时与文件大小。

基准值来自本机 i7-8750H 实测（640×360、24fps、环形特效）：
  渲染 9.82 ms/帧；MOV 4.51、WebM 19.29、H.264 6.76、遮罩双路 10.51 ms/帧。
运行时会在后台重新测量渲染与编码速度，得到当前机器的 cpu_factor。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, replace

from .audio import decode_audio, ffmpeg_path
from .demo import demo_features
from .effects import Renderer
from .encoder import MattePair, VideoWriter

REF_PIXELS = 640 * 360
REF_RENDER_MS = 9.82
REF_ENCODE_MS: dict[str, float] = {
    "mov": 4.51, "webm": 19.29, "mp4": 6.76, "mp4-matte": 10.51,
}
# 字节 / 像素 / 帧（由 8 秒 640×360 示例实测反推）
BPF: dict[str, float] = {
    "mov": 4.05 / 8,
    "webm": 0.653 / 8,
    "mp4": 0.071 / 8,
    "matte_main": 0.083 / 8,
    "matte_mask": 0.038 / 8,
}

MODE_RENDER = {
    "bottom": 0.55, "mirror": 0.75, "circle": 1.00, "dual_ring": 1.15,
    "spiral": 1.30, "waveform": 0.65, "tunnel": 0.90, "particles": 1.50,
}
MODE_SIZE = {
    "bottom": 0.75, "mirror": 0.90, "circle": 1.00, "dual_ring": 1.12,
    "spiral": 1.08, "waveform": 0.85, "tunnel": 1.00, "particles": 1.25,
}
GLOW_RENDER = {0.0: 0.55, 0.5: 0.95, 1.0: 1.00, 1.5: 1.02, 2.0: 1.04}
GLOW_SIZE = {0.0: 0.85, 0.5: 0.93, 1.0: 1.00, 1.5: 1.07, 2.0: 1.14}
BARS_RENDER = {32: 0.82, 64: 0.91, 96: 1.00, 128: 1.10, 192: 1.25}
BARS_SIZE = {32: 0.92, 64: 0.96, 96: 1.00, 128: 1.05, 192: 1.12}

SIZE_LIMIT = 200 * 1024 * 1024  # 200 MB
TIME_LIMIT = 600.0              # 10 分钟


@dataclass
class Estimate:
    size_bytes: int
    seconds: float
    frames: int
    files: int

    @property
    def size_warning(self) -> bool:
        return self.size_bytes > SIZE_LIMIT

    @property
    def time_warning(self) -> bool:
        return self.seconds > TIME_LIMIT


def format_size(n: float) -> str:
    if n < 1024:
        return f"{int(n)} B"
    if n < 1024 ** 2:
        return f"{n / 1024:.0f} KB"
    if n < 1024 ** 3:
        return f"{n / 1024 ** 2:.1f} MB"
    return f"{n / 1024 ** 3:.2f} GB"


def format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} 小时 {m} 分 {s} 秒"
    if m:
        return f"{m} 分 {s} 秒"
    return f"{s} 秒"


def probe_duration(path: str) -> float:
    """读取音频时长（秒）。先用 ffmpeg 头部信息，失败再完整解码。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(f"找不到音频文件: {path}")
    proc = subprocess.run(
        [ffmpeg_path(), "-hide_banner", "-nostdin", "-i", path],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    err = proc.stderr.decode("utf-8", "replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err)
    if m:
        dur = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if dur > 0:
            return dur
    # 有些文件头里没有 Duration（或显示 N/A），退回完整解码统计采样数
    try:
        samples, sr = decode_audio(path)
    except Exception as exc:  # noqa: BLE001
        tail = " | ".join(line.strip() for line in err.splitlines()[-3:] if line.strip())
        raise RuntimeError(f"ffmpeg 无法解码该音频：{tail or exc}") from exc
    dur = len(samples) / sr
    if dur <= 0:
        raise ValueError("音频文件没有可解码的采样数据")
    return dur


def estimate(
    *, duration: float, width: int, height: int, fps: int, mode: str,
    bars: int, glow: float, fmt: str, embed_audio: bool,
    render_ms: float | None = None,
    encode_ms: dict[str, float] | None = None,
    fft_size: int = 4096,
    workers: int | None = None,
) -> Estimate:
    """按当前参数与 CPU 基准预估输出大小与耗时。

    workers=0/None 表示自动，按 CPU 核心数折算并行收益；
    粒子效果含跨帧状态不并行，即使指定多进程也按单进程计。
    """
    render_ms = float(render_ms or REF_RENDER_MS)
    encode_ms = encode_ms or REF_ENCODE_MS
    ratio = max(0.05, (width * height) / REF_PIXELS)
    frames = max(1, int(round(max(0.0, duration) * fps)))

    render_per = (render_ms * ratio ** 0.88
                  * MODE_RENDER.get(mode, 1.0)
                  * BARS_RENDER.get(int(bars), 1.0)
                  * GLOW_RENDER.get(float(glow), 1.0))
    enc_key = ("mp4-matte" if fmt == "mp4-matte" else
               "webm" if fmt == "webm" else
               "mov" if fmt == "mov" else "mp4")
    encode_per = encode_ms.get(enc_key, REF_ENCODE_MS[enc_key]) * ratio ** 0.85
    cpu_factor = max(0.1, render_ms / REF_RENDER_MS)
    analysis = (0.4 + max(0.0, duration) * 0.02
                * (int(bars) / 96) * (fft_size / 4096)) * cpu_factor

    # 并行渲染折算：取得实际进程数（延迟导入避免循环依赖）。
    from .render import STATEFUL_MODES, resolve_workers
    n_workers = resolve_workers(workers)
    if mode in STATEFUL_MODES:
        n_workers = 1  # 跨帧状态效果始终单进程
    # 实测 6 核机器：6 进程约 2.0-2.3x，8 进程不再提升；
    # 用 0.62 的效率系数折减（IPC 开销 + 编码串行 + 调度开销），
    # 即有效加速 ≈ 1 + (n-1)*0.20，上限约 2.4x。
    render_parallel = 1.0 / (1.0 + (n_workers - 1) * 0.20) if n_workers > 1 else 1.0
    seconds = analysis + frames * (render_per * render_parallel + encode_per) / 1000.0

    # 文件大小：CRF 编码器在高分辨率下每像素码率略降，ProRes 近似恒定
    complexity = (MODE_SIZE.get(mode, 1.0)
                  * BARS_SIZE.get(int(bars), 1.0)
                  * GLOW_SIZE.get(float(glow), 1.0))
    crf_scale = 1.0 if fmt == "mov" else ratio ** -0.05
    bpf_key = "mp4" if enc_key == "mp4-matte" else enc_key
    size = frames * width * height * BPF[bpf_key] * crf_scale
    if fmt != "mov":
        size *= complexity
    if fmt == "mp4-matte":
        size += frames * width * height * BPF["matte_mask"] * crf_scale * complexity
    if embed_audio:
        size += max(0.0, duration) * 24_000  # AAC/Opus 192 kbps
    return Estimate(int(size), seconds, frames, 2 if fmt == "mp4-matte" else 1)


def _measure_render(repeats: int = 12) -> float:
    f = demo_features(96)
    renderer = Renderer(640, 360, "circle", "neon", 1.0)
    renderer.render(f)  # 预热
    started = time.perf_counter()
    for i in range(repeats):
        renderer.render(replace(f, time=2.4 + i / 24))
    return (time.perf_counter() - started) / repeats * 1000.0


def _measure_encode(repeats: int = 12) -> dict[str, float]:
    img = Renderer(640, 360, "circle", "neon", 1.0).render(demo_features(96))
    result: dict[str, float] = {}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        cases = [
            ("mov", "rgba", None, ".mov"),
            ("webm", "rgba", None, ".webm"),
            ("mp4", "rgb", (0, 255, 0), ".mp4"),
        ]
        for key, kind, bg, ext in cases:
            writer = VideoWriter(
                os.path.join(td, "t" + ext), 640, 360, 24, 8.0, kind,
                background=bg,
            )
            started = time.perf_counter()
            for _ in range(repeats):
                writer.write(img)
            writer.close()
            result[key] = (time.perf_counter() - started) / repeats * 1000.0
        writer = MattePair(
            os.path.join(td, "a.mp4"), os.path.join(td, "b.mp4"),
            640, 360, 24, 8.0, None, False, 20,
        )
        started = time.perf_counter()
        for _ in range(repeats):
            writer.write(img)
        writer.close()
        result["mp4-matte"] = (time.perf_counter() - started) / repeats * 1000.0
    return result


class Estimator:
    """后台测量当前机器性能，测量完成前使用参考基准值。"""

    def __init__(self, enabled: bool = True) -> None:
        self.ready = threading.Event()
        self.render_ms = REF_RENDER_MS
        self.encode_ms = dict(REF_ENCODE_MS)
        self.error: str | None = None
        if enabled:
            threading.Thread(target=self._run, daemon=True).start()
        else:
            self.ready.set()

    def _run(self) -> None:
        try:
            self.render_ms = max(0.5, _measure_render())
            self.encode_ms = _measure_encode()
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
        finally:
            self.ready.set()
