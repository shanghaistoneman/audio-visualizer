# 音频频谱视频生成器 · Android 版

把桌面版（Python）的音频频谱视频工具完整移植到 Android 的原生 Kotlin 应用。
解码、频谱分析、8 种视觉效果、渐变柔光、视频编码全部在手机本地离线完成，不上传音频、不依赖网络。

## 一、编译（需要在有 Android Studio 的电脑上操作）

本机（当前 Windows 环境）没有安装 Android SDK，**无法在这里直接编译出 APK**。请按下面步骤在有 Android Studio 的机器上生成安装包：

1. 安装 **Android Studio**（Hedgehog 2023.1 或更新版本），首次启动时它会引导安装 JDK 17 和 Android SDK。
2. 打开 Android Studio → `File` → `Open` → 选择本目录 `AndroidVisualizer`。
3. 等待 Gradle 同步完成（首次会自动下载 Gradle 8.9 和依赖库，需要联网）。
4. 用数据线连接安卓手机，开启「开发者选项 → USB 调试」。
5. 点击工具栏的运行按钮 ▶，App 会安装到手机上。
6. 生成正式安装包：`Build` → `Build Bundle(s) / APK(s)` → `Build APK(s)`，
   产物在 `app/build/outputs/apk/debug/app-debug.apk`，把它拷到手机安装即可。

命令行方式（已配置好 SDK 时）：
```bash
cd AndroidVisualizer
./gradlew assembleDebug
```

- 最低系统版本：**Android 8.0（API 26）**
- 目标版本：Android 15（API 35）

## 二、使用方法

1. 打开 App，右侧示例预览会随参数实时刷新（无需选音频）。
2. 点「选择音频文件」，从手机里挑一首 mp3 / wav / m4a / flac。
3. 调整参数：视觉效果、配色、分辨率、帧率、频谱柱数、发光强度、输出格式。
4. 勾选是否嵌入原音频，点「生成视频」。
5. 生成在后台进行，可随时点「取消」。完成后点「打开输出文件夹」查看。

输出位置（应用私有目录）：
```
Android/data/com.example.audiovisualizer/files/Movies/频谱视频输出/
```

## 三、与桌面版的差异（重要）

| 项目 | 桌面版 | Android 版 |
|---|---|---|
| 透明视频 MOV / WebM | 支持 | **不支持**（Android 编码器无 alpha 通道） |
| 透明替代方案 | MP4 + 遮罩 | MP4 + 黑白遮罩（两段视频，剪辑软件用亮度键抠像） |
| 并行渲染 | 多进程 | 单线程（手机多进程传帧开销更大，反而更慢） |
| 音频格式 | ffmpeg 全格式 | 系统解码器支持的格式（mp3/wav/m4a/flac 等主流格式均可） |

除以上平台限制外，算法与画面与桌面版一致：

- FFT 4096 点、20 Hz–20 kHz 对数频段
- 逐频段自适应归一化 + attack/release 平滑 + 节拍检测
- 8 种效果：底部频谱条 / 中央镜像扩散 / 环形频谱 / 双环旋转 / 螺旋星轨 / 波形脉冲 / 能量隧道 / 粒子爆破
- 7 套配色（含紫蓝渐变）、渐变模糊竖线、径向渐变圆环、柔光光带、渐变发光核心
- 已用对照测试验证：FFT、分位数、频段边界与 Python 原版逐点一致

## 四、性能提示

- 手机渲染速度取决于分辨率与发光强度。想要更快：选 `640×640` 或 `720×1280`、帧率 30、发光 1.0 或更低。
- `1920×1080` + 60fps + 发光 2.0 在手机上会非常慢，且可能占用较多内存。
- 生成时请保持 App 在前台；长时间后台运行可能被系统回收。

## 五、代码结构

```
app/src/main/java/com/example/audiovisualizer/
├── core/
│   ├── Models.kt         数据模型、参数选项、中文标签
│   ├── Fft.kt            radix-2 Cooley-Tukey FFT
│   ├── AudioDecoder.kt   MediaExtractor + MediaCodec 音频解码
│   ├── Analyzer.kt       STFT / 对数频段 / 归一化 / 节拍检测
│   ├── ColorUtil.kt      HSL→RGB
│   ├── MathExt.kt        Float 幂运算扩展
│   ├── Blur.kt           可分离盒式模糊（近似高斯）
│   ├── Renderer.kt       8 种效果 + 分层合成（约 685 行）
│   ├── Demo.kt           内置合成音频与示例预览
│   ├── VideoEncoder.kt   H.264 + AAC + MediaMuxer 编码
│   └── Generator.kt      解码→分析→渲染→编码流程编排
└── ui/MainActivity.kt    界面、文件选择、进度、取消
```
