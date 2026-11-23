"""ffmpeg rawvideo 管道编码器：逐帧后台写入，不需要录屏。"""
from __future__ import annotations

import subprocess
import tempfile
from typing import Sequence

from PIL import Image

from .audio import ffmpeg_path

# kind: rgba=真透明，rgb=合成到背景色，matte=黑白遮罩（白=不透明）
FORMATS: dict[str, dict] = {
    "mov": {"label": "MOV · ProRes 4444（真透明，剪辑推荐）", "kind": "rgba", "ext": ".mov"},
    "webm": {"label": "WebM · VP9（真透明，体积小）", "kind": "rgba", "ext": ".webm"},
    "mp4-matte": {"label": "MP4 + 黑白遮罩（两段 MP4，可还原透明）", "kind": "matte", "ext": ".mp4"},
    "mp4-green": {"label": "MP4 · H.264（绿幕背景，可色度键抠像）", "kind": "rgb", "ext": ".mp4"},
    "mp4-black": {"label": "MP4 · H.264（黑幕背景）", "kind": "rgb", "ext": ".mp4"},
}

BACKGROUND: dict[str, tuple[int, int, int]] = {
    "mp4-green": (0, 255, 0),
    "mp4-black": (0, 0, 0),
}


class VideoWriter:
    """把 RGBA 帧直接送入 ffmpeg 编码。"""

    def __init__(
        self,
        path: str,
        width: int,
        height: int,
        fps: int,
        duration: float,
        kind: str = "rgba",
        audio_path: str | None = None,
        embed_audio: bool = False,
        background: tuple[int, int, int] | None = None,
        crf: int = 20,
    ) -> None:
        self.path = path
        self.w = int(width)
        self.h = int(height)
        self.kind = kind
        self.background = background
        pix_in = "rgba" if kind == "rgba" else "rgb24"
        cmd: list[str] = [
            ffmpeg_path(), "-y", "-v", "error", "-nostdin",
            "-f", "rawvideo", "-pix_fmt", pix_in,
            "-s", f"{self.w}x{self.h}", "-r", str(fps), "-i", "-",
        ]
        use_audio = bool(embed_audio and audio_path and kind != "matte")
        if use_audio:
            cmd += ["-i", audio_path]

        if kind == "rgba":
            # 判断扩展名：.webm 用 VP9+alpha，否则 ProRes 4444
            if path.lower().endswith(".webm"):
                cmd += [
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                    "-b:v", "0", "-crf", str(min(50, max(12, crf + 10))),
                    "-deadline", "good", "-cpu-used", "4",
                    "-auto-alt-ref", "0", "-row-mt", "1",
                ]
            else:
                cmd += [
                    "-c:v", "prores_ks", "-profile:v", "4444",
                    "-pix_fmt", "yuva444p10le", "-qscale:v", "4",
                    "-vendor", "apl0",
                ]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", "medium",
                "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-movflags", "+faststart",
            ]

        cmd += ["-map", "0:v:0"]
        if use_audio:
            cmd += ["-map", "1:a:0"]
            if path.lower().endswith(".webm"):
                cmd += ["-c:a", "libopus", "-b:a", "192k"]
            else:
                cmd += ["-c:a", "aac", "-b:a", "192k"]
        else:
            cmd += ["-an"]
        cmd += ["-t", f"{duration:.4f}", path]

        self.cmd = cmd
        self._stderr_file = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_file,
            bufsize=self.w * self.h * 4,
        )
        self.closed = False

    def write(self, frame: Image.Image) -> None:
        if self.closed:
            raise RuntimeError("编码器已关闭")
        if self.kind == "rgba":
            data = frame.tobytes()
        elif self.kind == "matte":
            # 稍微提升亮度，让接近不透明的像素达到纯白，方便亮度键抠像
            matte = frame.getchannel("A").point(lambda x: min(255, int(x * 1.03)))
            data = matte.convert("RGB").tobytes()
        else:
            if self.background is not None:
                bg = Image.new("RGBA", (self.w, self.h), self.background + (255,))
                frame = Image.alpha_composite(bg, frame)
            data = frame.convert("RGB").tobytes()
        try:
            assert self.proc.stdin is not None
            self.proc.stdin.write(data)
        except BrokenPipeError as exc:
            raise RuntimeError(self._error_text("ffmpeg 提前退出")) from exc

    def _error_text(self, title: str) -> str:
        self._stderr_file.seek(0)
        tail = self._stderr_file.read().decode("utf-8", "replace")[-1200:]
        return f"{title}: {tail}"

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        assert self.proc.stdin is not None
        try:
            self.proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = self.proc.wait()
        if rc != 0:
            raise RuntimeError(self._error_text(f"ffmpeg 编码失败（退出码 {rc}）"))
        self._stderr_file.close()


class MattePair:
    """同时写出主 MP4 和黑白遮罩 MP4。"""

    def __init__(
        self, main_path: str, matte_path: str, width: int, height: int,
        fps: int, duration: float, audio_path: str | None, embed_audio: bool, crf: int,
    ) -> None:
        self.main = VideoWriter(
            main_path, width, height, fps, duration, "rgb",
            audio_path=audio_path, embed_audio=embed_audio,
            background=(0, 0, 0), crf=crf,
        )
        self.matte = VideoWriter(
            matte_path, width, height, fps, duration, "matte", crf=crf,
        )

    def write(self, frame: Image.Image) -> None:
        self.main.write(frame)
        self.matte.write(frame)

    def close(self) -> None:
        self.main.close()
        self.matte.close()


def output_paths(fmt: str, base: str) -> Sequence[str]:
    if fmt == "mp4-matte":
        return [base + ".mp4", base + "_matte.mp4"]
    return [base + FORMATS[fmt]["ext"]]
