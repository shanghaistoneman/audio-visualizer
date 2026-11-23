package com.example.audiovisualizer.core

import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min

/** 颜色工具：HSL -> RGB，与 Python colorsys.hls_to_rgb 等价。 */
object ColorUtil {

    /** h/l/s 均为 0..1，返回 0xAARRGGBB（alpha 单独传入 0..1）。 */
    fun hls(h0: Float, l: Float, s: Float, alpha: Float): Int {
        val h = ((h0 % 1f) + 1f) % 1f
        val light = min(0.98f, l)
        var r: Float
        var g: Float
        var b: Float
        if (s <= 0f) {
            r = light; g = light; b = light
        } else {
            val q = if (light < 0.5f) light * (1f + s) else light + s - light * s
            val p = 2f * light - q
            r = hueToRgb(p, q, h + 1f / 3f)
            g = hueToRgb(p, q, h)
            b = hueToRgb(p, q, h - 1f / 3f)
        }
        val a = (Options.clamp01(alpha) * 255f).toInt()
        val ri = (max(0f, min(1f, r)) * 255f).toInt()
        val gi = (max(0f, min(1f, g)) * 255f).toInt()
        val bi = (max(0f, min(1f, b)) * 255f).toInt()
        return (a shl 24) or (ri shl 16) or (gi shl 8) or bi
    }

    private fun hueToRgb(p: Float, q: Float, t0: Float): Float {
        var t = t0
        if (t < 0f) t += 1f
        if (t > 1f) t -= 1f
        if (t < 1f / 6f) return p + (q - p) * 6f * t
        if (t < 1f / 2f) return q
        if (t < 2f / 3f) return p + (q - p) * (2f / 3f - t) * 6f
        return p
    }

    fun withAlpha(color: Int, alpha01: Float): Int {
        val a = (Options.clamp01(alpha01) * 255f).toInt()
        return (a shl 24) or (color and 0x00FFFFFF)
    }

    fun alphaOf(color: Int): Float = ((color ushr 24) and 0xFF) / 255f
}
