# 第三方组件与许可说明

本文件是本项目使用第三方组件的合规清单与后续分发模板。
**当前仓库不包含、也不分发任何 ffmpeg 可执行文件**；`dist/` 与 `*.exe` 已在 `.gitignore` 中忽略，请保持这一状态，除非你准备自行承担下文的 GPLv3 分发义务。

## 1. Python 运行时依赖

这些依赖由 `requirements.txt` 声明，通过 pip 从各自的上游发行渠道安装：

| 组件 | 用途 | 许可证（以随包 LICENSE 文件为准） |
|---|---|---|
| numpy | 频谱分析、图像运算 | BSD-3-Clause |
| Pillow | RGBA 图像绘制与合成 | HPND / PIL Software License |
| imageio-ffmpeg | 提供 ffmpeg 可执行文件路径 | BSD-2-Clause |

本项目尊重上述组件的版权与许可声明，未修改其源码。

## 2. ffmpeg（重点）

- **获取方式**：安装 `imageio-ffmpeg` 时由其发行包提供；程序也支持通过环境变量 `FFMPEG_PATH` 指向用户自行安装的 ffmpeg。
- **本项目中的实际二进制**：`ffmpeg 9.0.2-essentials_build-www.gyan.dev`，构建参数含 `--enable-gpl --enable-version3 --enable-libx264 --enable-libx265`，`-L` 声明为 GPL 第 3 版或更高版本（GPLv3+）。
- **许可证资料**：<https://ffmpeg.org/legal.html>；源码：<https://ffmpeg.org/download.html>；该二进制来源：<https://www.gyan.dev/ffmpeg/builds/>。
- **调用方式**：本项目通过 `subprocess` 启动 ffmpeg 进程、以管道传入原始视频帧、用命令行参数传递配置，属于两个独立程序之间的通信（单纯聚合 / mere aggregation），因此本项目自身代码不受 GPL 传染，可继续按自有条款提供。
- **分发边界**：一旦把 ffmpeg 二进制随 exe、压缩包或其他媒介一起提供给他人，你即成为分发方，需自行履行 GPLv3 义务。

### 若将来需要对外分发含 ffmpeg 的 exe（模板）

- [ ] 附上 GPLv3 许可证全文，并保留 ffmpeg 的版权与声明。
- [ ] 提供 ffmpeg 对应版本的完整源码，或提供获取源码的书面要约（写明版本号、来源 URL；gyan.dev 构建需对应到 FFmpeg 官方 release commit）。
- [ ] 说明本项目代码与 ffmpeg 之间为聚合关系，不暗示 ffmpeg 受本项目许可证约束。
- [ ] 若二进制来自第三方构建方，按其要求保留来源标注。
- [ ] 另行评估 H.264/H.265 的专利授权问题（与版权许可相互独立），尤其用于商业收费场景时。
- [ ] 如改在进程内链接 libav* 库（而非子进程调用），需重新评估 LGPL/GPL 链接义务，本文件的聚合结论不再适用。

## 3. 免责声明

本文件是基于 FFmpeg 官方网站、GNU FAQ 及实际二进制 `-L` 输出整理的合规清单模板，不构成法律意见。若涉及商业发布，请咨询专业律师。
