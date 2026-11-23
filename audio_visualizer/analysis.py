"""离线频谱分析：STFT -> 对数频段 -> 自适应归一化 + 节拍检测。

整个过程在后台一次性完成，不依赖浏览器、录音或实时播放。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FrameFeatures:
    """一帧视频所需的全部音频特征。"""

    bars: np.ndarray       # 归一化频段能量, shape=(bars,), 0..1
    wave: np.ndarray       # 波形采样, shape=(wave_points,), -1..1
    level: float           # 整体音量 0..1
    bass: float            # 低频 0..1
    mid: float             # 中频 0..1
    treble: float          # 高频 0..1
    pulse: float           # 节拍脉冲包络 0..1
    beat: bool             # 本帧是否检测到节拍
    time: float            # 时间秒


class SpectrumAnalyzer:
    def __init__(
        self,
        samples: np.ndarray,
        sample_rate: int,
        fps: int = 30,
        bars: int = 96,
        fft_size: int = 4096,
        attack: float = 0.62,
        release: float = 0.16,
    ) -> None:
        if bars < 8:
            raise ValueError("bars 至少为 8")
        self.samples = np.asarray(samples, dtype=np.float32)
        self.sr = int(sample_rate)
        self.fps = int(fps)
        self.bars = int(bars)
        self.fft_size = int(fft_size)
        self.attack = float(attack)
        self.release = float(release)
        self.hop = max(1, self.sr // self.fps)
        self.n_frames = max(1, int(round(len(self.samples) / self.hop)))
        self.duration = len(self.samples) / self.sr

    def _band_edges(self) -> np.ndarray:
        """对数频率刻度，比线性刻度更符合听感与画面分布。"""
        nyquist = self.sr / 2.0
        edges_hz = np.geomspace(20.0, min(20000.0, nyquist * 0.96), self.bars + 1)
        edges = np.floor(edges_hz * self.fft_size / self.sr).astype(np.int32)
        edges = np.clip(edges, 1, self.fft_size // 2)
        for i in range(1, len(edges)):
            if edges[i] <= edges[i - 1]:
                edges[i] = edges[i - 1] + 1
            if edges[i] > self.fft_size // 2:
                edges[i] = self.fft_size // 2
        return edges

    def analyze(self) -> list[FrameFeatures]:
        sr, n_fft, hop = self.sr, self.fft_size, self.hop
        bars = self.bars
        window = np.hanning(n_fft).astype(np.float32)
        edges = self._band_edges()
        raw = np.zeros((self.n_frames, bars), dtype=np.float32)
        waves = np.zeros((self.n_frames, 128), dtype=np.float32)
        wave_step = max(1, n_fft // 128)

        for t in range(self.n_frames):
            start = t * hop
            seg = self.samples[start:start + n_fft]
            if seg.size < n_fft:
                seg = np.pad(seg, (0, n_fft - seg.size))
            spec = np.abs(np.fft.rfft(seg * window))
            for b in range(bars):
                lo, hi = int(edges[b]), int(edges[b + 1])
                raw[t, b] = spec[lo:hi].mean()
            waves[t] = seg[::wave_step][:128]

        # 逐频段自适应归一化：用分位数估计本底噪声与峰值，弱音也有细节，强音不过曝
        db = 20.0 * np.log10(raw + 1e-7)
        floor = np.percentile(db, 25.0, axis=0)
        peak = np.percentile(db, 99.5, axis=0)
        peak = np.maximum(peak, floor + 12.0)
        norm = np.clip((db - floor) / (peak - floor), 0.0, 1.0).astype(np.float32)

        # 频域轻微平滑，避免相邻柱剧烈锯齿
        kernel = np.array([0.2, 0.6, 0.2], dtype=np.float32)
        extended = np.pad(norm, ((0, 0), (1, 1)), mode="edge")
        norm = (
            extended[:, :-2] * kernel[0]
            + extended[:, 1:-1] * kernel[1]
            + extended[:, 2:] * kernel[2]
        )

        # 时域 attack/release 平滑：起音快、回落慢，画面更有冲击感
        smoothed = np.zeros_like(norm)
        prev = np.zeros(bars, dtype=np.float32)
        for t in range(self.n_frames):
            cur = norm[t]
            a = np.where(cur > prev, self.attack, self.release).astype(np.float32)
            prev = prev + a * (cur - prev)
            smoothed[t] = prev

        # 节拍检测：低频能量相对滑动均值突增
        low_count = max(4, bars // 8)
        energy = raw[:, :low_count].mean(axis=1)
        energy = energy / (energy.max() + 1e-9)
        mean = float(energy[0])
        beats = np.zeros(self.n_frames, dtype=bool)
        pulse = np.zeros(self.n_frames, dtype=np.float32)
        last_beat = -999
        for t, e in enumerate(energy):
            mean = mean * 0.97 + float(e) * 0.03
            if t > 3 and e > mean * 1.35 and e > 0.06 and (t - last_beat) >= max(3, self.fps // 6):
                beats[t] = True
                pulse[t] = 1.0
                last_beat = t
            if t:
                pulse[t] = max(pulse[t], pulse[t - 1] * 0.86)

        features: list[FrameFeatures] = []
        low_end = max(2, bars // 5)
        high_start = int(bars * 0.6)
        for t in range(self.n_frames):
            f = smoothed[t]
            features.append(
                FrameFeatures(
                    bars=f,
                    wave=waves[t],
                    level=float(f.mean()),
                    bass=float(f[:low_end].mean()),
                    mid=float(f[low_end:high_start].mean()),
                    treble=float(f[high_start:].mean()),
                    pulse=float(pulse[t]),
                    beat=bool(beats[t]),
                    time=t / self.fps,
                )
            )
        return features
