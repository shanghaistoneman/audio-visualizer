"""音频解码：用 ffmpeg 把 mp3/wav/flac/m4a 等解码为单声道 float32 PCM。"""
from __future__ import annotations

import os
import subprocess
import sys
from functools import lru_cache

import numpy as np


@lru_cache(maxsize=1)
def ffmpeg_path() -> str:
    """优先环境变量 FFMPEG_PATH，其次打包内置二进制，最后 imageio-ffmpeg。"""
    env = os.environ.get("FFMPEG_PATH")
    if env and os.path.isfile(env):
        return env
    # PyInstaller 单文件模式：ffmpeg.exe 被放到解压临时目录的根下
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        bundled = os.path.join(base, "ffmpeg.exe")
        if os.path.isfile(bundled):
            return bundled
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "未找到 ffmpeg。请执行: pip install imageio-ffmpeg，"
            "或设置环境变量 FFMPEG_PATH 指向 ffmpeg 可执行文件。"
        ) from exc


def decode_audio(path: str, sample_rate: int = 44100) -> tuple[np.ndarray, int]:
    """解码为单声道 float32 采样；返回 (samples, sample_rate)。"""
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    cmd = [
        ffmpeg_path(), "-v", "error", "-nostdin", "-i", path,
        "-vn", "-ac", "1", "-ar", str(sample_rate),
        "-f", "f32le", "-c:a", "pcm_f32le", "-",
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 解码音频失败: " + proc.stderr.decode("utf-8", "replace")[-800:])
    samples = np.frombuffer(proc.stdout, dtype="<f4").astype(np.float32)
    if samples.size == 0:
        raise ValueError("音频文件没有可解码的采样数据")
    return samples, sample_rate
