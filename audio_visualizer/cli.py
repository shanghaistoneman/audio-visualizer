"""命令行入口：python -m audio_visualizer.cli 音乐.mp3 --mode circle ..."""
from __future__ import annotations

import argparse
import os
import sys
import time

from .effects import BAR_OPTIONS, GLOW_OPTIONS, MODES, THEMES
from .encoder import FORMATS
from .render import RenderConfig, generate, preview_frame

PRESETS = {
    "quality": dict(width=1920, height=1080, fps=30, glow=1.0, crf=18),
    "balanced": dict(width=1280, height=720, fps=30, glow=1.5, crf=20),
    "fast": dict(width=1280, height=720, fps=24, glow=0.0, crf=23),
    "mobile": dict(width=640, height=640, fps=24, glow=0.5, crf=26),
}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="音频频谱视频生成器：离线渲染透明背景的动感 MV 素材，无需录屏。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  python -m audio_visualizer.cli 音乐.mp3 --mode circle --format mov\n"
            "  python -m audio_visualizer.cli 音乐.wav --mode particles --format mp4-matte --no-audio\n"
            "  python -m audio_visualizer.cli 音乐.mp3 --preset fast --format webm --preview 12\n\n"
            "透明通道说明: H.264 MP4 不支持 alpha。需要真正透明请用 mov(ProRes 4444) 或 webm(VP9)；\n"
            "mp4-matte 会同时输出主视频与黑白遮罩，可在剪辑软件中用亮度键还原透明。\n"
        ),
    )
    p.add_argument("input", nargs="?", help="输入音频文件（mp3/wav/flac/m4a…）")
    p.add_argument("-o", "--output-dir", default="output", help="输出目录（默认 output）")
    p.add_argument("--name", help="输出文件名（不含扩展名）")
    p.add_argument("--mode", choices=list(MODES), default="mirror", help="视觉效果（默认中央镜像扩散）")
    p.add_argument("--theme", choices=list(THEMES), default="neon", help="配色方案")
    p.add_argument("--format", dest="fmt", choices=list(FORMATS), default="mp4-black", help="输出格式（默认 MP4 黑幕）")
    p.add_argument("--preset", choices=list(PRESETS), default="balanced", help="画质预设")
    p.add_argument("--width", type=int, help="视频宽度（覆盖预设）")
    p.add_argument("--height", type=int, help="视频高度（覆盖预设）")
    p.add_argument("--fps", type=int, help="帧率（覆盖预设）")
    p.add_argument("--bars", type=int, choices=BAR_OPTIONS, default=192,
                   help=f"频谱柱数量，可选 {', '.join(map(str, BAR_OPTIONS))}（默认 192）")
    p.add_argument("--fft", type=int, default=4096, choices=[1024, 2048, 4096], help="FFT 窗口（默认 4096，覆盖 20Hz-20kHz）")
    p.add_argument("--glow", type=float, choices=GLOW_OPTIONS,
                   help=f"发光强度，可选 {', '.join(map(str, GLOW_OPTIONS))}（覆盖预设）")
    p.add_argument("--crf", type=int, help="H.264/VP9 质量 18-28（覆盖预设）")
    p.add_argument("--workers", type=int, default=0,
                   help="并行进程数：0=按 CPU 核心数自动（默认），1=单进程，N=指定；粒子爆破始终单进程")
    p.add_argument("--no-audio", action="store_true", help="不嵌入原音频")
    p.add_argument("--preview", type=float, metavar="SEC", help="只渲染指定秒数的一帧 PNG")
    p.add_argument("--list", action="store_true", help="列出所有效果与格式")
    return p


def config_from_args(args: argparse.Namespace) -> RenderConfig:
    preset = PRESETS[args.preset]
    return RenderConfig(
        input_path=args.input or "",
        output_dir=args.output_dir,
        mode=args.mode,
        theme=args.theme,
        fmt=args.fmt,
        width=args.width or preset["width"],
        height=args.height or preset["height"],
        fps=args.fps or preset["fps"],
        bars=args.bars,
        fft_size=args.fft,
        glow=preset["glow"] if args.glow is None else args.glow,
        crf=preset["crf"] if args.crf is None else args.crf,
        embed_audio=not args.no_audio,
        workers=args.workers,
        output_stem=args.name,
    )


def main(argv: list[str] | None = None) -> int:
    # Windows 中文控制台默认 GBK，无法编码效果名里的 emoji（如 ✨），
    # 直接 print 会 UnicodeEncodeError 崩溃。用替换策略输出，不影响文件结果。
    try:
        sys.stdout.reconfigure(errors="replace")
        sys.stderr.reconfigure(errors="replace")
    except (AttributeError, ValueError):  # 某些环境 stdout 不支持 reconfigure
        pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.list:
        print("效果:")
        for k, v in MODES.items():
            print(f"  {k:12s} {v}")
        print("格式:")
        for k, v in FORMATS.items():
            print(f"  {k:12s} {v['label']}")
        return 0
    if not args.input:
        parser.error("请指定输入音频文件")
    if not os.path.isfile(args.input):
        parser.error(f"找不到音频文件: {args.input}")

    cfg = config_from_args(args)
    if args.preview is not None:
        out = preview_frame(cfg, args.preview)
        print("预览图:", out)
        return 0

    last = [0.0]

    def progress(done: int, total: int, stage: str) -> None:
        now = time.time()
        if now - last[0] > 0.8 or done >= total:
            last[0] = now
            pct = int(done / max(1, total) * 100)
            print(f"\r[{pct:3d}%] {stage} ({done}/{total})", end="", flush=True)

    print(f"输入: {args.input}")
    print(f"设置: {MODES[cfg.mode]} / {cfg.width}x{cfg.height}@{cfg.fps}fps / {FORMATS[cfg.fmt]['label']}")
    try:
        paths = generate(cfg, progress=progress)
    except KeyboardInterrupt:
        print("\n已中断")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"\n生成失败: {exc}", file=sys.stderr)
        return 1
    print("\n生成完成:")
    for p in paths:
        print("  " + os.path.abspath(p))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
