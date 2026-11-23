package com.example.audiovisualizer.core

import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

/** 生成进度回调：(已完成帧, 总帧, 阶段文本)。 */
typealias ProgressFn = (Int, Int, String) -> Unit

/** 端到端生成结果。 */
data class GenerateResult(val outputs: List<File>, val durationSec: Float)

/**
 * 生成流程编排：解码 -> 分析 -> 逐帧渲染 -> 编码输出。
 * 安卓端单线程渲染（手机多进程 IPC 传帧反而更慢），保证粒子等跨帧状态正确。
 */
object Generator {

    fun generate(
        context: Context,
        cfg: RenderConfig,
        cancel: AtomicBoolean,
        progress: ProgressFn,
    ): GenerateResult {
        progress(0, 1, "正在解码音频…")
        val uri = Uri.parse(cfg.inputUri)
        val pcm = AudioDecoder.decode(context, uri, cfg.sampleRate)
        if (pcm.isEmpty()) throw IllegalArgumentException("音频文件没有可解码的采样数据")

        progress(0, 1, "正在分析频谱…")
        val analyzer = SpectrumAnalyzer(
            pcm, cfg.sampleRate,
            fps = cfg.fps, bars = cfg.bars, fftSize = cfg.fftSize,
        )
        val features = analyzer.analyze()
        val total = features.size
        if (total == 0) throw IllegalStateException("没有生成任何视频帧")

        val outDir = File(cfg.outputDir)
        if (!outDir.exists()) outDir.mkdirs()
        val baseName = sanitize(uri, cfg)
        val bgMode = when (cfg.fmt) {
            "mp4-green" -> VideoEncoder.BG_GREEN
            "mp4-matte" -> VideoEncoder.BG_MATTE
            else -> VideoEncoder.BG_BLACK
        }

        val encoders = ArrayList<VideoEncoder>()
        val outputs = ArrayList<File>()
        val audioForEncode = if (cfg.embedAudio && cfg.fmt != "mp4-matte") pcm else null

        val mainFile = File(outDir, "${baseName}_${cfg.mode}.mp4")
        outputs.add(mainFile)
        encoders.add(
            VideoEncoder(
                mainFile.absolutePath, cfg.width, cfg.height, cfg.fps,
                background = bgMode, matteOnly = false,
                audioPcm = audioForEncode, audioRate = cfg.sampleRate,
            )
        )

        // mp4-matte：额外输出黑白遮罩 MP4（不带音频）
        var matteFile: File? = null
        if (cfg.fmt == "mp4-matte") {
            matteFile = File(outDir, "${baseName}_${cfg.mode}_matte.mp4")
            outputs.add(matteFile)
            encoders.add(
                VideoEncoder(
                    matteFile.absolutePath, cfg.width, cfg.height, cfg.fps,
                    background = VideoEncoder.BG_MATTE, matteOnly = true,
                    audioPcm = null,
                )
            )
        }

        val renderer = Renderer(cfg.width, cfg.height, cfg.mode, cfg.theme, cfg.glow)
        var cancelled = false
        try {
            encoders.forEach { it.start() }
            for (i in 0 until total) {
                if (cancel.get()) { cancelled = true; break }
                val frame: Bitmap = renderer.render(features[i])
                encoders.forEach { it.writeFrame(frame) }
                if (i % 3 == 0 || i == total - 1) {
                    progress(i + 1, total, "正在渲染画面…")
                }
            }
        } finally {
            if (cancelled) {
                encoders.forEach { it.cancel() }
            } else {
                encoders.forEach { it.finish() }
            }
            renderer.release()
        }

        if (cancelled) {
            outputs.forEach { it.delete() }
            progress(0, total, "已取消")
            return GenerateResult(emptyList(), features.lastOrNull()?.time ?: 0f)
        }

        progress(total, total, "完成")
        return GenerateResult(outputs.filter { it.exists() }, analyzer.duration)
    }

    private fun sanitize(uri: Uri, cfg: RenderConfig): String {
        val name = uri.lastPathSegment ?: "audio"
        val stem = name.substringAfterLast('/').substringBeforeLast('.')
        return stem.replace(Regex("[^\\w\\u4e00-\\u9fa5-]"), "_").ifEmpty { "audio" }
    }
}
