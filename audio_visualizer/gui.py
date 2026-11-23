"""tkinter 图形界面：中文选项、实时示例效果图与参数预估。"""
from __future__ import annotations

import os
import queue
import shutil
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .demo import render_demo_preview
from .effects import THEMES
from .estimate import Estimator, estimate, format_duration, format_size, probe_duration
from .labels import (
    BARS_LABEL_BY_VALUE, BARS_OPTIONS, BARS_VALUES, FORMAT_BY_LABEL,
    FORMAT_LABEL_BY_KEY, FORMAT_OPTIONS, FPS_LABEL_BY_VALUE, FPS_OPTIONS,
    FPS_VALUES, GLOW_LABEL_BY_VALUE, GLOW_OPTIONS, GLOW_VALUES, MODE_BY_LABEL,
    MODE_OPTIONS, SIZES,
    THEME_BY_LABEL, THEME_LABEL_BY_KEY, THEME_OPTIONS, MODE_LABEL_BY_KEY,
    WORKERS_LABEL_BY_VALUE, WORKERS_OPTIONS, WORKERS_VALUES,
    label_for_mode, label_for_theme,
)
from .render import RenderConfig, generate, open_folder, preview_frame

NORMAL_FONT = ("Segoe UI", 10)
BOLD_RED = ("Segoe UI", 10, "bold")
RED = "#c62828"


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("音频频谱视频生成器 v1.2")
        self.root.geometry("1260x760")
        self.root.minsize(1160, 700)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        self.cancel = threading.Event()
        self.msgq: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.preview_worker: threading.Thread | None = None
        self.preview_lock = threading.Lock()
        self.pending_preview = None
        self.preview_seq = 0
        self.current_demo_img: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None

        self.estimator = Estimator()
        self._bench_notified = False
        self.durations: dict[tuple, float | None] = {}
        self.duration_errors: dict[tuple, str] = {}
        self.current_duration_key: tuple | None = None
        self.probe_thread: threading.Thread | None = None
        self.probe_key: tuple | None = None

        main = ttk.Frame(root, padding=14)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        left = ttk.Frame(main)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.LabelFrame(main, text="示例效果与生成预估", padding=10)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_left(left)
        self._build_right(right)
        for var in (self.mode_var, self.theme_var, self.size_var, self.fps_var,
                    self.bars_var, self.glow_var, self.fmt_var, self.audio_var,
                    self.audio_var2):
            var.trace_add("write", lambda *_: self.on_params_changed())
        self.update_estimate()
        self.root.after(80, self.pump)
        self.request_demo_preview()

    # ------------------------------ 界面布局 ------------------------------
    def _build_left(self, frm: ttk.Frame) -> None:
        row = 0
        ttk.Label(frm, text="音频频谱视频生成器", font=("Segoe UI", 17, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0, 4))
        row += 1
        ttk.Label(frm, text="后台离线渲染 · 支持透明背景 · 无需录屏",
                  foreground="#666666").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 8))

        row += 1
        ttk.Label(frm, text="音频文件：").grid(row=row, column=0, sticky="w")
        self.audio_var = tk.StringVar()
        ttk.Entry(frm, textvariable=self.audio_var, width=52).grid(row=row, column=1, sticky="ew")
        ttk.Button(frm, text="浏览…", command=self.choose_audio, width=10).grid(row=row, column=2)

        row += 1
        ttk.Label(frm, text="输出目录：").grid(row=row, column=0, sticky="w", pady=6)
        self.out_var = tk.StringVar(value=os.path.join(os.getcwd(), "频谱视频输出"))
        ttk.Entry(frm, textvariable=self.out_var, width=52).grid(row=row, column=1, sticky="ew")
        ttk.Button(frm, text="浏览…", command=self.choose_dir, width=10).grid(row=row, column=2)

        row += 1
        box = ttk.LabelFrame(frm, text="画面设置（选项后标注对文件大小/耗时的影响）", padding=10)
        box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=6)
        box.columnconfigure(0, weight=1)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="视觉效果：").grid(row=0, column=0, columnspan=2, sticky="w")
        self.mode_var = tk.StringVar(value=MODE_LABEL_BY_KEY["mirror"])
        self._combo(box, self.mode_var, MODE_OPTIONS, 62).grid(
            row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(box, text="配色：").grid(row=2, column=0, columnspan=2, sticky="w")
        self.theme_var = tk.StringVar(value=THEME_LABEL_BY_KEY["neon"])
        self._combo(box, self.theme_var, THEME_OPTIONS, 62).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(box, text="分辨率：").grid(row=4, column=0, columnspan=2, sticky="w")
        self.size_var = tk.StringVar(value="1280 × 720（横屏流畅·文件中等、耗时中等）")
        self._combo(box, self.size_var, list(SIZES), 62).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        ttk.Label(box, text="帧率：").grid(row=6, column=0, sticky="w")
        ttk.Label(box, text="频谱柱数：").grid(row=6, column=1, sticky="w")
        self.fps_var = tk.StringVar(value=FPS_LABEL_BY_VALUE["30"])
        self.bars_var = tk.StringVar(value=BARS_LABEL_BY_VALUE["192"])
        self._combo(box, self.fps_var, FPS_OPTIONS, 32).grid(row=7, column=0, sticky="ew", pady=(0, 6))
        self._combo(box, self.bars_var, BARS_OPTIONS, 32).grid(
            row=7, column=1, sticky="ew", pady=(0, 6), padx=(10, 0))

        ttk.Label(box, text="发光强度：").grid(row=8, column=0, columnspan=2, sticky="w")
        self.glow_var = tk.StringVar(value=GLOW_LABEL_BY_VALUE["1.5"])
        self._combo(box, self.glow_var, GLOW_OPTIONS, 62).grid(
            row=9, column=0, columnspan=2, sticky="ew")

        row += 1
        box2 = ttk.LabelFrame(frm, text="输出设置", padding=10)
        box2.grid(row=row, column=0, columnspan=3, sticky="ew", pady=4)
        box2.columnconfigure(1, weight=1)
        ttk.Label(box2, text="输出格式：").grid(row=0, column=0, sticky="w")
        self.fmt_var = tk.StringVar(value=FORMAT_LABEL_BY_KEY["mp4-black"])
        self._combo(box2, self.fmt_var, FORMAT_OPTIONS, 62).grid(
            row=0, column=1, columnspan=2, sticky="ew")
        self.audio_var2 = tk.BooleanVar(value=True)
        ttk.Checkbutton(box2, text="嵌入原音频", variable=self.audio_var2).grid(
            row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(box2, text="提示：MP4 本身不支持透明；mp4-matte 会输出主视频+遮罩两段 MP4。",
                  foreground="#a05000").grid(row=1, column=1, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(box2, text="并行进程数：").grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.workers_var = tk.StringVar(value=WORKERS_LABEL_BY_VALUE["0"])
        self._combo(box2, self.workers_var, WORKERS_OPTIONS, 62).grid(
            row=2, column=1, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Label(box2, text="自动按 CPU 核心数选择；粒子爆破含跨帧状态，始终单进程。",
                  foreground="#888888").grid(row=3, column=0, columnspan=3, sticky="w", pady=(2, 0))

        row += 1
        self.progress = ttk.Progressbar(frm, mode="determinate", maximum=100)
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(10, 4))
        self.status = ttk.Label(frm, text="就绪，请先选择音频文件")
        self.status.grid(row=row + 1, column=0, columnspan=3, sticky="w")

        row += 2
        btn = ttk.Frame(frm)
        btn.grid(row=row, column=0, columnspan=3, pady=10)
        self.start_btn = ttk.Button(btn, text="开始生成", command=self.start)
        self.start_btn.pack(side=tk.LEFT, padx=4)
        self.cancel_btn = ttk.Button(btn, text="取消", command=self.do_cancel, state=tk.DISABLED)
        self.cancel_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="预览当前音频一帧", command=self.do_preview).pack(side=tk.LEFT, padx=4)
        ttk.Button(btn, text="打开输出目录", command=self.open_out).pack(side=tk.LEFT, padx=4)

    def _build_right(self, frm: ttk.LabelFrame) -> None:
        self.preview_label = ttk.Label(frm, background="#121218", anchor=tk.CENTER)
        self.preview_label.pack(fill=tk.BOTH, expand=True, pady=(4, 6))
        self.preview_info = ttk.Label(frm, text="正在生成示例…", foreground="#444444",
                                      wraplength=430, justify=tk.CENTER)
        self.preview_info.pack(fill=tk.X, pady=(0, 8))

        est = ttk.LabelFrame(frm, text="生成预估（随参数实时更新）", padding=8)
        est.pack(fill=tk.X, pady=(0, 8))
        self.est_size = ttk.Label(est, text="预估文件大小：选择音频后显示", font=NORMAL_FONT)
        self.est_size.pack(anchor="w")
        self.est_time = ttk.Label(est, text="预估生成耗时：选择音频后显示", font=NORMAL_FONT)
        self.est_time.pack(anchor="w", pady=(2, 0))
        self.est_warn = ttk.Label(est, text="", font=NORMAL_FONT)
        self.est_warn.pack(anchor="w", pady=(3, 0))
        self.est_note = ttk.Label(est, text="", foreground="#777777", wraplength=420,
                                  justify=tk.LEFT)
        self.est_note.pack(anchor="w", pady=(4, 0))

        bar = ttk.Frame(frm)
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="保存当前示例图", command=self.save_demo).pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text="打开示例图库", command=self.open_gallery).pack(side=tk.LEFT, padx=2)
        ttk.Label(frm, text="示例使用内置合成音频；预估基于本机 CPU 实测基准，实际结果会有波动。",
                  foreground="#888888", wraplength=430, justify=tk.LEFT).pack(fill=tk.X, pady=(8, 0))

    @staticmethod
    def _combo(parent, var: tk.StringVar, values: list[str], width: int) -> ttk.Combobox:
        return ttk.Combobox(parent, textvariable=var, values=values,
                            state="readonly", width=width)

    # ------------------------------ 参数解码 ------------------------------
    def values(self) -> dict:
        w, h = SIZES[self.size_var.get()]
        return dict(
            input_path=self.audio_var.get().strip(),
            mode=MODE_BY_LABEL[self.mode_var.get()],
            theme=THEME_BY_LABEL[self.theme_var.get()],
            w=w, h=h,
            fps=int(FPS_VALUES[self.fps_var.get()]),
            bars=int(BARS_VALUES[self.bars_var.get()]),
            glow=float(GLOW_VALUES[self.glow_var.get()]),
            fmt=FORMAT_BY_LABEL[self.fmt_var.get()],
            embed=bool(self.audio_var2.get()),
            workers=int(WORKERS_VALUES[self.workers_var.get()]),
        )

    def config(self) -> RenderConfig:
        v = self.values()
        return RenderConfig(
            input_path=v["input_path"],
            output_dir=self.out_var.get().strip() or os.path.join(os.getcwd(), "频谱视频输出"),
            mode=v["mode"], theme=v["theme"], fmt=v["fmt"],
            width=v["w"], height=v["h"], fps=v["fps"],
            bars=v["bars"], glow=v["glow"], embed_audio=v["embed"],
            workers=v["workers"],
        )

    def on_params_changed(self) -> None:
        self.request_demo_preview()
        self.ensure_duration()
        self.update_estimate()

    # ------------------------------ 预估 ------------------------------
    def ensure_duration(self) -> None:
        path = self.audio_var.get().strip()
        self.current_duration_key = None
        if not path or not os.path.isfile(path):
            return
        st = os.stat(path)
        key = (path, st.st_mtime, st.st_size)
        self.current_duration_key = key
        if key in self.durations:
            return
        if self.probe_thread and self.probe_thread.is_alive() and self.probe_key == key:
            return
        self.probe_key = key
        self.probe_thread = threading.Thread(
            target=self._probe_worker, args=(path, key), daemon=True).start()

    def _probe_worker(self, path: str, key: tuple) -> None:
        try:
            dur, err = probe_duration(path), None
        except Exception as exc:  # noqa: BLE001
            dur, err = None, str(exc)
        self.msgq.put(("duration", (key, dur, err), None))

    def update_estimate(self) -> None:
        if not hasattr(self, "est_size"):
            return
        v = self.values()
        if not v["input_path"] or not os.path.isfile(v["input_path"]):
            for label in (self.est_size, self.est_time):
                label.config(text=label.cget("text").split("：")[0] + "：选择音频后显示",
                             font=NORMAL_FONT, foreground="#444444")
            self.est_warn.config(text="")
            self.est_note.config(text="", foreground="#777777")
            return
        key = self.current_duration_key
        dur = self.durations.get(key) if key else None
        if dur is None:
            probing = bool(self.probe_thread and self.probe_thread.is_alive())
            text = "正在读取音频时长…" if probing else "无法读取音频时长"
            self.est_size.config(text="预估文件大小：" + text, font=NORMAL_FONT, foreground="#444444")
            self.est_time.config(text="预估生成耗时：" + text, font=NORMAL_FONT, foreground="#444444")
            self.est_warn.config(text="")
            err = self.duration_errors.get(key) if key else None
            self.est_note.config(text=("时长读取失败：" + err) if err else "",
                                 foreground=RED if err else "#777777")
            return

        est = estimate(
            duration=dur, width=v["w"], height=v["h"], fps=v["fps"],
            mode=v["mode"], bars=v["bars"], glow=v["glow"], fmt=v["fmt"],
            embed_audio=v["embed"], workers=v["workers"],
            render_ms=self.estimator.render_ms, encode_ms=self.estimator.encode_ms,
        )
        self.est_size.config(
            text=f"预估文件大小：{format_size(est.size_bytes)}",
            font=BOLD_RED if est.size_warning else NORMAL_FONT,
            foreground=RED if est.size_warning else "#222222",
        )
        self.est_time.config(
            text=f"预估生成耗时：{format_duration(est.seconds)}",
            font=BOLD_RED if est.time_warning else NORMAL_FONT,
            foreground=RED if est.time_warning else "#222222",
        )
        warn: list[str] = []
        if est.size_warning:
            warn.append("⚠ 预估文件超过 200 MB")
        if est.time_warning:
            warn.append("⚠ 预估耗时超过 10 分钟")
        self.est_warn.config(text="  ".join(warn), font=BOLD_RED if warn else NORMAL_FONT,
                             foreground=RED if warn else "#222222")
        note = (f"音频 {dur:.1f} 秒 · {est.frames} 帧 · 输出 {est.files} 个文件 · "
                f"{v['w']}×{v['h']}@{v['fps']}fps")
        if not self.estimator.ready.is_set():
            note += " · CPU 性能校准中…"
        elif self.estimator.error:
            note += " · CPU 校准失败，使用参考基准"
        else:
            note += " · 已按当前 CPU 实测校准"
        self.est_note.config(text=note, foreground="#777777")

    # ------------------------------ 示例图预览 ------------------------------
    def request_demo_preview(self) -> None:
        if not hasattr(self, "mode_var"):
            return
        self.preview_seq += 1
        v = self.values()
        params = dict(mode=v["mode"], theme=v["theme"], bars=v["bars"], glow=v["glow"])
        with self.preview_lock:
            self.pending_preview = (self.preview_seq, params)
        if self.preview_worker is None or not self.preview_worker.is_alive():
            self.preview_worker = threading.Thread(target=self._preview_worker, daemon=True)
            self.preview_worker.start()

    def _preview_worker(self) -> None:
        while True:
            with self.preview_lock:
                if self.pending_preview is None:
                    break
                seq, params = self.pending_preview
                self.pending_preview = None
            try:
                img = render_demo_preview(**params, width=560, height=315)
                self.msgq.put(("demo", (seq, img, params), None))
            except Exception as exc:  # noqa: BLE001
                self.msgq.put(("demo_error", None, str(exc)))

    def _show_demo(self, seq: int, img: Image.Image, params: dict) -> None:
        if seq != self.preview_seq:
            return
        self.current_demo_img = img
        bg = Image.new("RGBA", img.size, (18, 18, 26, 255))
        disp = Image.alpha_composite(bg, img).convert("RGB")
        disp.thumbnail((560, 315), Image.Resampling.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        self.preview_label.config(image=self._photo)
        self.preview_info.config(
            text=f"{label_for_mode(params['mode'])} · {label_for_theme(params['theme'])} · "
                 f"柱数 {params['bars']} · 发光 {params['glow']}"
        )

    @staticmethod
    def _gallery_dir() -> str:
        """示例图库目录：打包环境下用 exe 旁边的持久目录，源码环境用项目根目录。"""
        if getattr(sys, "frozen", False):
            return os.path.join(os.path.dirname(sys.executable), "示例图库")
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "示例图库")

    def save_demo(self) -> None:
        if self.current_demo_img is None:
            messagebox.showinfo("提示", "示例图尚未生成")
            return
        out = self._gallery_dir()
        os.makedirs(out, exist_ok=True)
        path = os.path.join(
            out, f"自定义_{self.mode_var.get()}_{self.theme_var.get()}_"
                 f"{self.bars_var.get()}_{self.glow_var.get()}.png"
        )
        self.current_demo_img.save(path)
        self.status.config(text="示例图已保存: " + os.path.basename(path))
        messagebox.showinfo("已保存", path)

    def open_gallery(self) -> None:
        path = self._gallery_dir()
        if getattr(sys, "frozen", False) and not os.path.isdir(path):
            # 单文件 exe：内置图库在临时目录，先释放到 exe 旁的持久目录
            base = getattr(sys, "_MEIPASS", "")
            bundled = os.path.join(base, "示例图库")
            if os.path.isdir(bundled):
                try:
                    shutil.copytree(bundled, path)
                except OSError as exc:  # noqa: BLE001
                    messagebox.showerror("错误", f"释放示例图库失败: {exc}")
                    return
        if os.path.isdir(path):
            open_folder(path)
        else:
            messagebox.showinfo("提示", "示例图库不存在，请先运行 python -m audio_visualizer.generate_gallery")

    # ------------------------------ 文件与任务 ------------------------------
    def choose_audio(self) -> None:
        path = filedialog.askopenfilename(
            title="选择音频文件",
            filetypes=[("音频文件", "*.mp3 *.wav *.flac *.m4a *.aac *.ogg"), ("所有文件", "*.*")],
        )
        if path:
            self.audio_var.set(path)
            if not self.out_var.get():
                self.out_var.set(os.path.join(os.path.dirname(path), "频谱视频输出"))
            self.status.config(text="已选择: " + os.path.basename(path))

    def choose_dir(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.out_var.set(path)

    def open_out(self) -> None:
        path = self.out_var.get()
        if os.path.isdir(path):
            open_folder(path)
        else:
            messagebox.showinfo("提示", "输出目录尚不存在")

    def start(self) -> None:
        cfg = self.config()
        if not cfg.input_path or not os.path.isfile(cfg.input_path):
            messagebox.showerror("错误", "请先选择有效的音频文件")
            return
        if self.worker and self.worker.is_alive():
            return
        self.cancel.clear()
        self.start_btn.config(state=tk.DISABLED)
        self.cancel_btn.config(state=tk.NORMAL)
        self.progress["value"] = 0
        self.worker = threading.Thread(target=self._run, args=(cfg,), daemon=True)
        self.worker.start()

    def _run(self, cfg: RenderConfig) -> None:
        try:
            paths = generate(cfg, progress=self.on_progress, cancel=self.cancel)
            self.msgq.put(("done", paths, None))
        except Exception as exc:  # noqa: BLE001
            self.msgq.put(("error", None, str(exc)))

    def do_cancel(self) -> None:
        self.cancel.set()
        self.status.config(text="正在取消…")

    def do_preview(self) -> None:
        cfg = self.config()
        if not cfg.input_path or not os.path.isfile(cfg.input_path):
            messagebox.showerror("错误", "请先选择有效的音频文件")
            return
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("提示", "请等待当前任务完成")
            return
        self.status.config(text="正在生成预览图…")
        self.worker = threading.Thread(target=self._preview_real, args=(cfg,), daemon=True)
        self.worker.start()

    def _preview_real(self, cfg: RenderConfig) -> None:
        try:
            path = preview_frame(cfg, 12.0)
            self.msgq.put(("preview", path, None))
        except Exception as exc:  # noqa: BLE001
            self.msgq.put(("error", None, str(exc)))

    def on_progress(self, done: int, total: int, stage: str) -> None:
        self.msgq.put(("progress", (done, total, stage), None))

    def pump(self) -> None:
        try:
            while True:
                kind, payload, err = self.msgq.get_nowait()
                if kind == "progress":
                    done, total, stage = payload
                    self.progress["value"] = done / max(1, total) * 100
                    self.status.config(text=f"{stage}  {done}/{total}")
                elif kind == "duration":
                    key, dur, err = payload
                    self.durations[key] = dur
                    if err:
                        self.duration_errors[key] = err
                    else:
                        self.duration_errors.pop(key, None)
                    if self.current_duration_key == key:
                        self.update_estimate()
                elif kind == "demo":
                    self._show_demo(*payload)
                elif kind == "demo_error":
                    self.preview_info.config(text="示例生成失败: " + (err or "未知错误"))
                elif kind == "done":
                    self.start_btn.config(state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.DISABLED)
                    if payload:
                        self.status.config(text="完成！")
                        messagebox.showinfo(
                            "生成完成",
                            "已输出:\n" + "\n".join(os.path.abspath(p) for p in payload),
                        )
                    else:
                        self.status.config(text="已取消，临时文件已删除")
                elif kind == "preview":
                    self.status.config(text="预览图: " + payload)
                    open_folder(os.path.dirname(payload))
                elif kind == "error":
                    self.start_btn.config(state=tk.NORMAL)
                    self.cancel_btn.config(state=tk.DISABLED)
                    self.status.config(text="失败")
                    messagebox.showerror("错误", err or "未知错误")
        except queue.Empty:
            pass
        if self.estimator.ready.is_set() and not self._bench_notified:
            self._bench_notified = True
            self.update_estimate()
        self.root.after(80, self.pump)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
