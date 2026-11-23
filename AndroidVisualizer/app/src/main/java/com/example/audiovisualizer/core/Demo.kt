package com.example.audiovisualizer.core

import android.graphics.Bitmap
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.sin
import kotlin.random.Random

/**
 * 内置合成演示音频，供界面实时示例预览使用（未选择音频也能看效果）。
 * 与 Python demo.py 的合成逻辑与"视觉友好频谱"混合一致。
 */
object Demo {

    @Volatile
    private var cachedSamples: FloatArray? = null

    private fun demoSamples(): FloatArray {
        cachedSamples?.let { return it }
        val sr = 44100
        val duration = 5.0
        val n = (sr * duration).toInt()
        val t = FloatArray(n) { it.toFloat() / sr }
        val rng = Random(11)
        val samples = FloatArray(n)

        for (i in 0 until n) {
            val ti = t[i]
            val noise = 0.075 * (rng.nextDouble() * 2 - 1)
            val chord = 0.30 * (sin(2 * PI * 220 * ti) + 0.65 * sin(2 * PI * 330 * ti) + 0.45 * sin(2 * PI * 440 * ti))
            val sweep = 0.22 * sin(2 * PI * (120 + 850 * ti / duration) * ti)
            samples[i] = (chord + sweep + noise).toFloat()
        }
        // 底鼓（每 0.5s）
        var beat = 0.0
        while (beat < duration) {
            val i0 = (beat * sr).toInt()
            val count = minOf(n - i0, (0.18 * sr).toInt())
            for (k in 0 until count) {
                val env = exp(-14.0 * k / count)
                samples[i0 + k] += (0.58 * env * sin(2 * PI * 62 * (0.18 * k / count))).toFloat()
            }
            beat += 0.5
        }
        // 踩镲（每 0.25s）
        var hat = 0.25
        while (hat < duration) {
            val i0 = (hat * sr).toInt()
            val count = minOf(n - i0, (0.05 * sr).toInt())
            for (k in 0 until count) {
                val env = exp(-8.0 * k / count)
                samples[i0 + k] += (0.11 * (rng.nextDouble() * 2 - 1) * env).toFloat()
            }
            hat += 0.25
        }
        for (i in 0 until n) samples[i] = samples[i].coerceIn(-1f, 1f)
        cachedSamples = samples
        return samples
    }

    /** 返回合成音频在 2.4s 处的"视觉友好"单帧特征。 */
    fun demoFeatures(bars: Int): FrameFeatures {
        val samples = demoSamples()
        val fps = 24
        val analyzer = SpectrumAnalyzer(samples, 44100, fps = fps, bars = bars, fftSize = 4096)
        val frames = analyzer.analyze()
        val idx = minOf(frames.size - 1, maxOf(0, (2.4 * fps).toInt()))
        val feat = frames[idx]

        val mixed = FloatArray(bars)
        for (i in 0 until bars) {
            val x = i.toFloat() / bars
            val base = 0.16f + 0.10f * (1f - x)
            val bumps = 0.55f * exp(-((x - 0.12f) / 0.05f) * ((x - 0.12f) / 0.05f)).toFloat() +
                0.42f * exp(-((x - 0.35f) / 0.07f) * ((x - 0.35f) / 0.07f)).toFloat() +
                0.34f * exp(-((x - 0.62f) / 0.09f) * ((x - 0.62f) / 0.09f)).toFloat()
            val ripple = 0.10f * (0.5f + 0.5f * sin(x * 38f + 2.4f * 3f))
            val nice = (base + bumps + ripple).coerceIn(0f, 1f)
            mixed[i] = (0.78f * nice + 0.22f * feat.bars[i]).coerceIn(0f, 1f)
        }
        val lowEnd = maxOf(2, bars / 5)
        val highStart = (bars * 0.6).toInt()
        var level = 0f; var bass = 0f; var mid = 0f; var treble = 0f
        for (v in mixed) level += v
        level /= bars
        for (i in 0 until lowEnd) bass += mixed[i]
        bass /= lowEnd
        for (i in lowEnd until highStart) mid += mixed[i]
        mid /= maxOf(1, highStart - lowEnd)
        for (i in highStart until bars) treble += mixed[i]
        treble /= maxOf(1, bars - highStart)

        return FrameFeatures(
            bars = mixed, wave = feat.wave,
            level = level, bass = bass, mid = mid, treble = treble,
            pulse = feat.pulse, beat = feat.beat, time = feat.time,
        )
    }

    /** 按指定参数渲染一张示例效果图（透明背景）。 */
    fun renderPreview(mode: String, theme: String, bars: Int, glow: Float, w: Int, h: Int): Bitmap {
        val feat = demoFeatures(bars)
        val renderer = Renderer(w, h, mode, theme, glow)
        val rendered = renderer.render(feat)
        // 复制一份再释放，避免 render() 内部回收的位图被外部继续引用
        val bmp = rendered.copy(Bitmap.Config.ARGB_8888, false)
        renderer.release()
        return bmp
    }
}
