# -*- mode: python ; coding: utf-8 -*-
"""精简打包配置：单文件 exe，仅包含本项目实际依赖。

依赖白名单：numpy、Pillow、tkinter、imageio-ffmpeg 的 ffmpeg 二进制。
其余模块一律排除，避免把环境里安装的 gradio/torch/chromadb 等无关库打进去。
"""
import os

ROOT = os.path.abspath(SPECPATH)  # PyInstaller 注入的 spec 所在目录
FFMPEG = r"C:\Python\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v9.0.2.exe"

# 环境里装了很多大型库，PyInstaller 的 hook 可能误收集；显式排除
EXCLUDES = [
    # 科学计算/绘图（本项目只需 numpy 核心）
    "scipy", "pandas", "matplotlib", "mpl_toolkits", "seaborn", "sklearn", "skimage",
    # AI/Web/文档等大型库
    "torch", "tensorflow", "jax", "gradio", "fastapi", "uvicorn", "starlette",
    "pydantic", "chromadb", "requests", "aiohttp", "bs4", "lxml", "cryptography",
    "IPython", "jupyter", "notebook", "sphinx", "pytest", "setuptools", "pkg_resources",
    # numpy / Pillow 中项目用不到的子模块
    "numpy.testing", "numpy.f2py", "numpy.distutils", "numpy.doc", "numpy.ma",
    "PIL.ImageQt", "PIL.ImageShow", "PIL.ImageGrab",
    # 注意：不要排除标准库模块。numpy.random 依赖 secrets/hashlib/_random 等，
    # 排除 secrets 会导致打包后 default_rng() 直接 ModuleNotFoundError。
    # 标准库只按需被 PyInstaller 收集，体积很小，无需手动排除。
]

GALLERY = os.path.join(ROOT, "示例图库")
# 示例图库随包携带：GUI 的"打开示例图库"在冻结环境下从 _MEIPASS/示例图库 读取，
# 与 gui.py 中基于 __file__ 计算的路径一致。
gallery_data = [(GALLERY, "示例图库")] if os.path.isdir(GALLERY) else []

a = Analysis(
    [os.path.join(ROOT, "build_entry.py")],
    pathex=[ROOT],
    # 不手动加 ffmpeg：hook-imageio_ffmpeg 会自动把唯一一份收进包内，
    # 手动再加会导致同一个 100MB 二进制被打进去两遍。
    binaries=[],
    datas=gallery_data,
    # numpy.random 的 Cython 模块在运行时才 import secrets，静态扫描发现不了，
    # 必须显式声明，否则打包后 default_rng() 抛 ModuleNotFoundError。
    hiddenimports=["secrets"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUDES,
    noarchive=False,
    # 不能用 optimize=2：numpy 启动时会读取自身 docstring，剥离后
    # add_docstring 收到 None 直接 TypeError（打包后必崩）。
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="音频频谱视频生成器",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 纯 GUI，不弹黑色控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
