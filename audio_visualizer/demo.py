"""内置合成演示音频，供参数示例图与界面实时预览使用。

这样即使用户还没选择音频文件，也能立刻看到各参数组合的效果。
"""
from __future__ import annotations

from dataclasses import replace
from functools import lru_cache

import numpy as np

from .analysis import FrameFeatures, SpectrumAnalyzer
from .effects import Renderer
from PIL import Image


@lru_cache(maxsize=1)
def demo_samples() -> tuple[np.ndarray, int]:
    sr = 44100
    duration = 5.0
    t = np.arange(int(sr * duration)) / sr
    rng = np.random.default_rng(11)
    # 低幅宽带噪声作为底噪，让环形/双环等效果能呈现完整的一圈
    noise = 0.075 * rng.standard_normal(len(t))
    chord = 0.30 * (
        np.sin(2 * np.pi * 220 * t)
        + 0.65 * np.sin(2 * np.pi * 330 * t)
        + 0.45 * np.sin(2 * np.pi * 440 * t)
    )
    sweep = 0.22 * np.sin(2 * np.pi * (120 + 850 * t / duration) * t)
    kick = np.zeros_like(t)
    for beat in np.arange(0.0, duration, 0.5):
        i = int(beat * sr)
        n = min(len(t) - i, int(0.18 * sr))
        env = np.exp(-np.linspace(0, 14, n))
        kick[i:i + n] += 0.58 * env * np.sin(2 * np.pi * 62 * np.linspace(0, 0.18, n))
    hat = np.zeros_like(t)
    for beat in np.arange(0.25, duration, 0.25):
        i = int(beat * sr)
        n = min(len(t) - i, int(0.05 * sr))
        hat[i:i + n] += 0.11 * rng.standard_normal(n) * np.exp(-np.linspace(0, 8, n))
    samples = np.clip(chord + sweep + kick + hat + noise, -1.0, 1.0).astype(np.float32)
    return samples, sr


@lru_cache(maxsize=16)
def demo_features(bars: int, fps: int = 24, fft_size: int = 4096, at_sec: float = 2.4) -> FrameFeatures:
    """返回合成音频在指定时间的单帧特征。"""
    samples, sr = demo_samples()
    analyzer = SpectrumAnalyzer(samples, sr, fps=fps, bars=bars, fft_size=fft_size)
    features = analyzer.analyze()
    idx = min(len(features) - 1, max(0, int(at_sec * fps)))
    feat = features[idx]

    # 合成一段“视觉友好”的频谱：保留真实分析得到的节拍/波形，但让各频段都有可见能量，
    # 这样环形、双环、隧道等效果在示例图里能呈现完整形状。
    x = np.linspace(0.0, 1.0, bars)
    base = 0.16 + 0.10 * (1.0 - x)
    bumps = (
        0.55 * np.exp(-((x - 0.12) / 0.05) ** 2)
        + 0.42 * np.exp(-((x - 0.35) / 0.07) ** 2)
        + 0.34 * np.exp(-((x - 0.62) / 0.09) ** 2)
    )
    ripple = 0.10 * (0.5 + 0.5 * np.sin(x * 38 + at_sec * 3.0))
    nice = np.clip(base + bumps + ripple, 0.0, 1.0)
    mixed = np.clip(0.78 * nice + 0.22 * feat.bars, 0.0, 1.0).astype(np.float32)
    low_end = max(2, bars // 5)
    high_start = int(bars * 0.6)
    return replace(
        feat,
        bars=mixed,
        level=float(mixed.mean()),
        bass=float(mixed[:low_end].mean()),
        mid=float(mixed[low_end:high_start].mean()),
        treble=float(mixed[high_start:].mean()),
    )


def render_demo_preview(
    mode: str,
    theme: str,
    bars: int,
    glow: float,
    width: int = 480,
    height: int = 270,
) -> Image.Image:
    """按指定参数渲染一张示例效果图（RGBA，背景透明）。"""
    feat = demo_features(int(bars))
    renderer = Renderer(width, height, mode, theme, float(glow))
    return renderer.render(feat)
