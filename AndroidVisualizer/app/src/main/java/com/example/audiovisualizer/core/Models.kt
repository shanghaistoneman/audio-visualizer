package com.example.audiovisualizer.core

import kotlin.math.max
import kotlin.math.min

/** 一帧视频所需的全部音频特征，与 Python 端 FrameFeatures 一一对应。 */
data class FrameFeatures(
    val bars: FloatArray,      // 归一化频段能量 0..1
    val wave: FloatArray,      // 波形采样 -1..1
    val level: Float,
    val bass: Float,
    val mid: Float,
    val treble: Float,
    val pulse: Float,
    val beat: Boolean,
    val time: Float,
)

/** 渲染配置，默认值与桌面版一致。 */
data class RenderConfig(
    val inputUri: String = "",
    val outputDir: String = "",
    val mode: String = "mirror",
    val theme: String = "neon",
    val fmt: String = "mp4-black",
    val width: Int = 720,
    val height: Int = 1280,
    val fps: Int = 30,
    val bars: Int = 192,
    val fftSize: Int = 4096,
    val glow: Float = 1.5f,
    val embedAudio: Boolean = true,
    val crf: Int = 20,
    val sampleRate: Int = 44100,
) {
    val shortSide: Int get() = min(width, height)
}

object Options {
    const val KEY_MODE = "mode"
    const val KEY_THEME = "theme"
    const val KEY_FMT = "fmt"

    /** 效果内部 key -> 中文名（与桌面版 MODE_NAMES 一致） */
    val MODE_NAMES = linkedMapOf(
        "bottom" to "底部频谱条",
        "mirror" to "中央镜像扩散",
        "circle" to "环形频谱",
        "dual_ring" to "双环旋转",
        "spiral" to "螺旋星轨",
        "waveform" to "波形脉冲",
        "tunnel" to "能量隧道",
        "particles" to "粒子爆破",
    )

    val THEME_NAMES = linkedMapOf(
        "neon" to "霓虹青紫（默认）",
        "rainbow" to "全彩循环",
        "fire" to "烈焰金红",
        "aurora" to "极光青绿",
        "ice" to "冰蓝纯白",
        "mono" to "纯白",
        "purple_blue" to "紫蓝渐变（左紫右蓝）",
    )

    val FORMAT_NAMES = linkedMapOf(
        "mp4-black" to "MP4 · 黑幕背景",
        "mp4-green" to "MP4 · 绿幕背景",
        "mp4-matte" to "MP4 + 黑白遮罩",
    )

    val MODE_KEYS = MODE_NAMES.keys.toList()
    val THEME_KEYS = THEME_NAMES.keys.toList()
    val FORMAT_KEYS = FORMAT_NAMES.keys.toList()

    val BAR_OPTIONS = intArrayOf(32, 64, 96, 128, 192)
    val GLOW_OPTIONS = floatArrayOf(0f, 0.5f, 1f, 1.5f, 2f)
    val SIZE_OPTIONS = arrayOf(
        intArrayOf(1080, 1920),
        intArrayOf(720, 1280),
        intArrayOf(1080, 1080),
        intArrayOf(640, 640),
        intArrayOf(1920, 1080),
        intArrayOf(1280, 720),
    )
    val FPS_OPTIONS = intArrayOf(24, 30, 60)

    /** 有跨帧状态的效果：安卓端单线程渲染，这里仅用于未来扩展标记。 */
    val STATEFUL_MODES = setOf("particles")

    fun clamp01(v: Float): Float = if (v < 0f) 0f else if (v > 1f) 1f else v
    fun clamp(v: Float, lo: Float, hi: Float): Float = max(lo, min(hi, v))
}
