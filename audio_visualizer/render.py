"""渲染流程编排：解码 -> 分析 -> 逐帧生成 -> 编码输出。

逐帧渲染支持多进程并行：无跨帧状态的效果由进程池并行出帧，主进程按序编码；
含跨帧状态的效果（粒子爆破）自动回退单进程，保证画面与串行结果一致。
进程数按 CPU 核心数自适应，也可用 workers 参数覆盖。
"""
from __future__ import annotations

import multiprocessing as mp
import os
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Callable

from PIL import Image

from .analysis import SpectrumAnalyzer
from .audio import decode_audio
from .effects import Renderer
from .encoder import BACKGROUND, MattePair, VideoWriter, output_paths

ProgressFn = Callable[[int, int, str], None]

# 含跨帧状态的效果：粒子位置与随机数序列依赖前一帧，不能并行拆分。
STATEFUL_MODES = frozenset({"particles"})

# worker 进程内的 Renderer 实例（由 initializer 创建，跨帧复用避免反复初始化）。
_WORKER_RENDERER: Renderer | None = None


def _init_worker(width: int, height: int, mode: str, theme: str, glow: float) -> None:
    """进程池 initializer：每个 worker 进程持有自己的 Renderer。"""
    global _WORKER_RENDERER
    _WORKER_RENDERER = Renderer(width, height, mode, theme, glow)


def _render_frame(features) -> Image.Image:
    """进程池 worker：渲染单帧。必须是模块顶层函数才能被 pickle。"""
    if _WORKER_RENDERER is None:
        raise RuntimeError("渲染 worker 未初始化")
    return _WORKER_RENDERER.render(features)


def resolve_workers(requested: int | None = None) -> int:
    """根据请求值与 CPU 核心数决定实际并行进程数。

    自动策略（requested <= 0 / None）：
    - 少核（<=4 逻辑核）：留 1 核给编码与系统，避免抢满。
    - 多核：多数 CPU 逻辑核为物理核的 2 倍（超线程），渲染是 CPU 密集
      任务，超线程收益很小，故按逻辑核的一半估算物理核心量级；实测
      6 物理核机器上 6 进程比 8 进程更快（后者 IPC 开销反噬）。
    - 上限 8：再多的进程只会增加逐帧 RGBA 图像的 IPC 传输成本。

    手动指定：1 表示强制单进程，上限 32。
    """
    if requested is None or requested <= 0:
        cpu = os.cpu_count() or 1
        if cpu <= 4:
            return max(1, cpu - 1)
        return max(2, min(cpu // 2, 8))
    return max(1, min(int(requested), 32))


@dataclass
class RenderConfig:
    input_path: str
    output_dir: str
    mode: str = "mirror"
    theme: str = "neon"
    fmt: str = "mp4-black"
    width: int = 1280
    height: int = 720
    fps: int = 30
    bars: int = 192
    fft_size: int = 4096
    glow: float = 1.5
    embed_audio: bool = True
    crf: int = 20
    workers: int = 0  # 0=按 CPU 核心数自动；1=强制单进程；N=指定进程数
    output_stem: str | None = None
    sample_rate: int = field(default=44100, repr=False)

    @property
    def stem(self) -> str:
        if self.output_stem:
            return os.path.join(self.output_dir, self.output_stem)
        name = os.path.splitext(os.path.basename(self.input_path))[0]
        return os.path.join(self.output_dir, f"{name}_{self.mode}")


@lru_cache(maxsize=3)
def _cached_analysis(path: str, mtime: float, size: int, sr: int, fps: int, bars: int, fft: int):
    """同一音频重复预览/生成时复用分析结果。"""
    samples, rate = decode_audio(path, sr)
    return SpectrumAnalyzer(samples, rate, fps=fps, bars=bars, fft_size=fft).analyze()


def _analyze(cfg: RenderConfig):
    st = os.stat(cfg.input_path)
    return _cached_analysis(
        cfg.input_path, st.st_mtime, st.st_size,
        cfg.sample_rate, cfg.fps, cfg.bars, cfg.fft_size,
    )


def _report(fn: ProgressFn | None, done: int, total: int, stage: str) -> None:
    if fn:
        fn(done, total, stage)


def _cleanup(paths: list[str]) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.remove(p)
        except OSError:
            pass


def generate(
    cfg: RenderConfig,
    progress: ProgressFn | None = None,
    cancel: threading.Event | None = None,
) -> list[str]:
    """生成视频，返回输出文件路径列表。取消时删除半成品。"""
    os.makedirs(cfg.output_dir, exist_ok=True)
    paths = list(output_paths(cfg.fmt, cfg.stem))
    _report(progress, 0, 1, "正在解码音频并分析频谱…")
    features = _analyze(cfg)
    duration = len(features) / cfg.fps

    renderer = Renderer(cfg.width, cfg.height, cfg.mode, cfg.theme, cfg.glow)
    total = len(features)
    workers = resolve_workers(cfg.workers)
    # 有跨帧状态或进程数=1 或帧数太少时走单进程，避免 IPC 反噬
    parallel = workers > 1 and cfg.mode not in STATEFUL_MODES and total >= workers * 4

    writer: VideoWriter | MattePair
    if cfg.fmt == "mp4-matte":
        writer = MattePair(
            paths[0], paths[1], cfg.width, cfg.height, cfg.fps, duration,
            cfg.input_path, cfg.embed_audio, cfg.crf,
        )
    else:
        kind = "rgba" if cfg.fmt in ("mov", "webm") else "rgb"
        writer = VideoWriter(
            paths[0], cfg.width, cfg.height, cfg.fps, duration, kind,
            audio_path=cfg.input_path, embed_audio=cfg.embed_audio,
            background=BACKGROUND.get(cfg.fmt), crf=cfg.crf,
        )

    cancelled = False
    pool = None
    try:
        if parallel:
            try:
                # Windows 冻结环境（PyInstaller）只能用 spawn 启动方式；
                # 显式指定避免不同平台默认值不一致。
                ctx = mp.get_context("spawn")
                pool = ctx.Pool(
                    processes=workers,
                    initializer=_init_worker,
                    initargs=(cfg.width, cfg.height, cfg.mode, cfg.theme, cfg.glow),
                )
            except Exception:  # noqa: BLE001 - 进程池创建失败则回退单进程
                parallel = False

        if parallel and pool is not None:
            # 分批 imap：保序返回、有界内存（不会把全部帧结果堆在内存里）。
            # chunksize=1 让帧均匀分发，进度反馈更平滑。
            batch = max(workers * 2, 8)
            done = 0
            for start in range(0, total, batch):
                stop = min(start + batch, total)
                for frame in pool.imap(
                    _render_frame, features[start:stop], chunksize=1
                ):
                    if cancel is not None and cancel.is_set():
                        cancelled = True
                        break
                    writer.write(frame)
                    done += 1
                    if done % 3 == 0 or done == total:
                        _report(progress, done, total, "正在渲染画面…")
                if cancelled:
                    break
        else:
            for i, feat in enumerate(features):
                if cancel is not None and cancel.is_set():
                    cancelled = True
                    break
                writer.write(renderer.render(feat))
                if i % 3 == 0 or i == total - 1:
                    _report(progress, i + 1, total, "正在渲染画面…")
    finally:
        if pool is not None:
            if cancelled:
                pool.terminate()
            else:
                pool.close()
            pool.join()
        writer.close()

    if cancelled:
        _cleanup(paths)
        _report(progress, 0, total, "已取消")
        return []
    _report(progress, total, total, "完成")
    return paths


def preview_frame(cfg: RenderConfig, time_sec: float) -> str:
    """渲染指定时间的单帧 PNG，用于快速试效果。"""
    os.makedirs(cfg.output_dir, exist_ok=True)
    features = _analyze(cfg)
    idx = min(len(features) - 1, max(0, int(time_sec * cfg.fps)))
    renderer = Renderer(cfg.width, cfg.height, cfg.mode, cfg.theme, cfg.glow)
    out = os.path.join(
        cfg.output_dir,
        f"{os.path.splitext(os.path.basename(cfg.input_path))[0]}_{cfg.mode}_预览_{idx}.png",
    )
    renderer.render(features[idx]).save(out)
    return out


def open_folder(path: str) -> None:
    """跨平台打开输出目录。"""
    import platform
    import subprocess

    p = os.path.abspath(path)
    system = platform.system()
    if system == "Windows":
        os.startfile(p)  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])
