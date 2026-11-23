package com.example.audiovisualizer.core

import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin
import kotlin.random.Random

/**
 * 把音频特征渲染成透明背景 RGBA 帧。
 * 用多层 Bitmap 分离主线/辉光/柔光/竖线/圆环，合成顺序与 Python effects.py 一致。
 */
class Renderer(
    val width: Int,
    val height: Int,
    val mode: String,
    val theme: String,
    val glow: Float,
) {
    private val s: Float = min(width, height).toFloat()
    private var time: Float = 0f

    // 粒子系统（有跨帧状态）
    private val rng = Random(20261122)
    private val particles = ArrayList<Particle>()

    private data class Particle(
        var x: Float, var y: Float, var vx: Float, var vy: Float,
        var life: Float, val decay: Float, val size: Float,
        val p: Float, val v: Float,
    )

    // ---- 各图层 ----
    private lateinit var layer: Bitmap
    private lateinit var layerC: Canvas
    private lateinit var halo: Bitmap
    private lateinit var haloC: Canvas
    private lateinit var core: Bitmap
    private lateinit var coreC: Canvas
    private lateinit var spokes: Bitmap
    private lateinit var spokesC: Canvas
    private lateinit var bars: Bitmap
    private lateinit var barsC: Canvas
    private lateinit var rings: Bitmap
    private lateinit var ringsC: Canvas

    // ---- 画笔 ----
    private val linePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val compositePaint = Paint()

    // 渐变精灵缓存
    private val orbMaskCache = HashMap<Int, Bitmap>()   // power*100 -> 径向渐变蒙版
    private val vbarMaskCache = HashMap<Long, FloatArray>() // (w<<16|h) -> 竖线 alpha 蒙版

    init {
        allocate()
    }

    private fun allocate() {
        layer = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        layerC = Canvas(layer)
        halo = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        haloC = Canvas(halo)
        core = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        coreC = Canvas(core)
        spokes = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        spokesC = Canvas(spokes)
        bars = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        barsC = Canvas(bars)
        rings = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        ringsC = Canvas(rings)
    }

    fun release() {
        layer.recycle(); halo.recycle(); core.recycle()
        spokes.recycle(); bars.recycle(); rings.recycle()
        orbMaskCache.values.forEach { it.recycle() }
        orbMaskCache.clear()
    }

    /** 计算颜色，对应 Python Renderer.color()。 */
    private fun color(p: Float, v: Float, alpha: Float? = null, x: Float? = null): Int {
        val pp = Options.clamp01(p)
        val vv = Options.clamp01(v)
        val h: Float
        val l: Float
        val sat: Float
        when (theme) {
            "neon" -> { h = 0.50f + 0.22f * pp; l = 0.48f + 0.42f * vv; sat = 1f }
            "rainbow" -> { h = (pp + time * 0.055f) % 1f; l = 0.48f + 0.40f * vv; sat = 1f }
            "fire" -> { h = 0.02f + 0.11f * pp + 0.02f * vv; l = 0.42f + 0.45f * vv; sat = 1f }
            "aurora" -> { h = 0.34f + 0.22f * pp; l = 0.46f + 0.42f * vv; sat = 0.95f }
            "ice" -> { h = 0.53f + 0.08f * pp; l = 0.55f + 0.40f * vv; sat = 0.75f }
            "purple_blue" -> {
                val gx = Options.clamp01(x ?: pp)
                h = 0.80f - 0.22f * gx; l = 0.42f + 0.44f * vv; sat = 0.92f
            }
            else -> { h = 0f; l = 0.55f + 0.45f * vv; sat = 0f } // mono
        }
        val a = alpha ?: (90f + 165f * vv)
        return ColorUtil.hls(h, l, sat, a / 255f)
    }

    /** 渲染一帧，返回透明背景 RGBA 位图。 */
    fun render(f: FrameFeatures): Bitmap {
        time = f.time
        clearAll()

        when (mode) {
            "bottom" -> drawBottom(f)
            "mirror" -> drawMirror(f)
            "circle" -> drawCircle(f)
            "dual_ring" -> drawDualRing(f)
            "spiral" -> drawSpiral(f)
            "waveform" -> drawWaveform(f)
            "tunnel" -> drawTunnel(f)
            "particles" -> drawParticles(f)
            else -> drawMirror(f)
        }

        // 1) 渐变圆环 -> 主体
        compositePaint.alpha = 255
        layerC.drawBitmap(rings, 0f, 0f, compositePaint)
        // 2) 渐变竖线 -> 主体
        layerC.drawBitmap(bars, 0f, 0f, compositePaint)
        // 3) 渐变能量核 -> 主体
        layerC.drawBitmap(core, 0f, 0f, compositePaint)

        // 4) 柔光线带：垫在主线之下
        val hasSpokes = !spokes.isRecycled && hasContent(spokes)
        if (hasSpokes && glow > 0) {
            val soft = Blur.blurBitmap(spokes, max(2f, s / 240f), 2)
            compositePaint.alpha = minOf(255, (glow * 1.35f * 255f).toInt())
            // 先画柔光，再把主线叠上去
            val merged = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
            val mc = Canvas(merged)
            mc.drawBitmap(soft, 0f, 0f, compositePaint)
            compositePaint.alpha = 255
            mc.drawBitmap(layer, 0f, 0f, compositePaint)
            soft.recycle()
            // 用 merged 替换 layer
            layer.recycle()
            layer = merged
            layerC = Canvas(layer)
        } else if (hasSpokes) {
            // glow=0：直接叠原短线
            layerC.drawBitmap(spokes, 0f, 0f, compositePaint)
        }

        if (glow <= 0) return layer

        // 5) 局部辉光：较大半径模糊，叠在主体之上
        if (hasContent(halo)) {
            val glowLayer = Blur.blurBitmap(halo, max(2f, s / 200f), 3)
            compositePaint.alpha = minOf(255, (glow * 1.25f * 255f).toInt())
            layerC.drawBitmap(glowLayer, 0f, 0f, compositePaint)
            glowLayer.recycle()
        }

        // 6) 全局柔光
        val factor = glow * (if (mode in setOf("circle", "dual_ring", "spiral")) 1.15f else 1f)
        val haloFull = Blur.blurBitmap(layer, max(1f, s / 420f), 3)
        compositePaint.alpha = minOf(255, (factor * 255f).toInt())
        val finalBmp = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        val fc = Canvas(finalBmp)
        fc.drawBitmap(haloFull, 0f, 0f, compositePaint)
        compositePaint.alpha = 255
        fc.drawBitmap(layer, 0f, 0f, compositePaint)
        haloFull.recycle()
        // 保留 finalBmp 作为本帧输出；下一帧 render 时重新分配
        layer.recycle()
        layer = finalBmp
        layerC = Canvas(layer)
        return layer
    }

    private fun clearAll() {
        layer.eraseColor(Color.TRANSPARENT)
        halo.eraseColor(Color.TRANSPARENT)
        core.eraseColor(Color.TRANSPARENT)
        spokes.eraseColor(Color.TRANSPARENT)
        bars.eraseColor(Color.TRANSPARENT)
        rings.eraseColor(Color.TRANSPARENT)
    }

    private fun hasContent(b: Bitmap): Boolean {
        // 精确判断是否有非透明像素：整图读取一次，逐段扫描 alpha 字节
        val w = b.width
        val h = b.height
        val row = IntArray(w)
        for (y in 0 until h) {
            b.getPixels(row, 0, w, 0, y, w, 1)
            for (x in 0 until w) {
                if ((row[x] ushr 24) != 0) return true
            }
        }
        return false
    }

    // ============ 通用绘制封装 ============

    /** 柔化描边：柔光光带画到 spokes，主线降低权重画到主图层。 */
    private fun strokeGlow(
        rgba: Int, width: Float,
        softScale: Float = 0.85f, mainScale: Float = 0.6f,
        softWidth: Float? = null,
        draw: (Canvas, Int, Float) -> Unit,
    ) {
        if (glow > 0) {
            draw(spokesC, withAlphaScale(rgba, softScale), softWidth ?: width)
            draw(layerC, withAlphaScale(rgba, mainScale), width)
        } else {
            draw(layerC, rgba, width)
        }
    }

    private fun withAlphaScale(color: Int, scale: Float): Int {
        val a = ((color ushr 24) and 0xFF) * scale
        return ((a.toInt() and 0xFF) shl 24) or (color and 0x00FFFFFF)
    }

    private fun glowLine(
        seg: FloatArray, rgba: Int, width: Float,
        softScale: Float = 0.85f, mainScale: Float = 0.6f,
    ) {
        strokeGlow(rgba, width, softScale, mainScale, draw = { c, col, w ->
            linePaint.color = col
            linePaint.strokeWidth = w
            c.drawLine(seg[0], seg[1], seg[2], seg[3], linePaint)
        })
    }

    private fun glowPolyline(
        pts: FloatArray, rgba: Int, width: Float,
        softScale: Float = 0.85f, mainScale: Float = 0.6f,
    ) {
        strokeGlow(rgba, width, softScale, mainScale, draw = { c, col, w ->
            linePaint.color = col
            linePaint.strokeWidth = w
            val n = pts.size / 2
            for (i in 0 until n - 1) {
                c.drawLine(pts[i * 2], pts[i * 2 + 1], pts[i * 2 + 2], pts[i * 2 + 3], linePaint)
            }
        })
    }

    private fun glowEllipseOutline(
        cx: Float, cy: Float, r: Float, rgba: Int, width: Float,
        softScale: Float = 0.85f, mainScale: Float = 0.6f,
    ) {
        val box = RectF(cx - r, cy - r, cx + r, cy + r)
        strokeGlow(rgba, width, softScale, mainScale, draw = { c, col, w ->
            linePaint.color = col
            linePaint.strokeWidth = w
            c.drawOval(box, linePaint)
        })
    }

    /** 渐变竖线：单根独立精灵，横向中间亮两侧淡出，纵向顶部淡入底部淡出。 */
    private fun softVBar(cx: Float, y0: Float, y1: Float, barWidth: Float, rgba: Int) {
        val w = max(1, barWidth.roundToInt())
        val h = max(2, ((y1 - y0) / 4f).roundToInt() * 4)
        val key = (w.toLong() shl 16) or h.toLong()
        val mask = vbarMaskCache.getOrPut(key) { buildVBarMask(w, h) }
        val peak = minOf(255, ((rgba ushr 24) and 0xFF) * 118 / 100)
        val r = (rgba ushr 16) and 0xFF
        val g = (rgba ushr 8) and 0xFF
        val b = rgba and 0xFF
        val px = IntArray(w * h)
        for (i in 0 until w * h) {
            val a = ((mask[i] * peak) / 255f).toInt() and 0xFF
            px[i] = (a shl 24) or (r shl 16) or (g shl 8) or b
        }
        val sprite = Bitmap.createBitmap(px, w, h, Bitmap.Config.ARGB_8888)
        barsC.drawBitmap(sprite, (cx - w / 2f).roundToInt().toFloat(), y0.roundToInt().toFloat(), null)
        sprite.recycle()
    }

    private fun buildVBarMask(w: Int, h: Int): FloatArray {
        val mask = FloatArray(w * h)
        for (x in 0 until w) {
            val xs = ((x + 0.5f) / w) * 2f - 1f
            val hp = max(0f, 1f - xs * xs).powf(1.2f)
            for (y in 0 until h) {
                val ys = (y + 0.5f) / h
                var vp = max(0f, min(1f, ys / 0.28f)).powf(0.8f)
                vp *= max(0f, min(1f, (1f - ys) / 0.06f)).powf(0.5f)
                mask[y * w + x] = hp * vp * 255f
            }
        }
        return mask
    }

    /** 渐变圆环：多层 1px 同心细环按高斯权重叠加，边缘径向淡出。 */
    private fun softRing(cx: Float, cy: Float, r: Float, rgba: Int, ringWidth: Float, arc: IntArray? = null) {
        if (r < 2 || ringWidth <= 0) return
        val sigma = max(1.2f, ringWidth * 0.85f)
        val span = max(2, kotlin.math.ceil((ringWidth * 1.8f).toDouble()).toInt())
        val a0 = (rgba ushr 24) and 0xFF
        val rr0 = (rgba ushr 16) and 0xFF
        val gg0 = (rgba ushr 8) and 0xFF
        val bb0 = rgba and 0xFF
        val paint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeWidth = 1f }
        for (k in -span..span) {
            val rad = r + k
            if (rad < 1) continue
            val a = (a0 * exp(-0.5 * (k / sigma) * (k / sigma))).toInt()
            if (a < 2) continue
            paint.color = ((min(255, a) and 0xFF) shl 24) or (rr0 shl 16) or (gg0 shl 8) or bb0
            val box = RectF(cx - rad, cy - rad, cx + rad, cy + rad)
            if (arc == null) {
                ringsC.drawOval(box, paint)
            } else {
                // Android drawArc：startAngle 从 3 点方向顺时针，sweep 为跨度
                val sweep = wrapAngle(arc[1] - arc[0])
                ringsC.drawArc(box, arc[0].toFloat(), sweep, false, paint)
            }
        }
    }

    private fun wrapAngle(delta: Int): Float {
        var d = delta.toFloat() % 360f
        if (d < 0) d += 360f
        if (d == 0f) d = 360f
        return d
    }

    /** 径向渐变光球：中心亮、边缘平滑淡出。 */
    private fun softOrb(
        cx: Float, cy: Float, radius: Float, rgba: Int,
        power: Float = 1.6f, target: Int = TARGET_HALO,
    ) {
        if (radius < 2) return
        val key = (power * 100).roundToInt()
        val mask = orbMaskCache.getOrPut(key) { buildOrbMask(key / 100f) }
        val size = max(2, (radius * 2).roundToInt())
        val scaled = Bitmap.createScaledBitmap(mask, size, size, true)
        val alpha = (rgba ushr 24) and 0xFF
        val r = (rgba ushr 16) and 0xFF
        val g = (rgba ushr 8) and 0xFF
        val b = rgba and 0xFF
        // 用蒙版调制 alpha：直接绘制 scaled 后叠加颜色
        val px = IntArray(size * size)
        scaled.getPixels(px, 0, size, 0, 0, size, size)
        for (i in px.indices) {
            val m = (px[i] and 0xFF) // 蒙版是灰度，取 R 通道
            val a = (m * alpha) / 255
            px[i] = ((a and 0xFF) shl 24) or (r shl 16) or (g shl 8) or b
        }
        val orb = Bitmap.createBitmap(px, size, size, Bitmap.Config.ARGB_8888)
        scaled.recycle()
        val c = when (target) {
            TARGET_CORE -> coreC
            else -> haloC
        }
        c.drawBitmap(orb, cx - radius, cy - radius, null)
        orb.recycle()
    }

    private fun buildOrbMask(power: Float): Bitmap {
        val size = 128
        val px = IntArray(size * size)
        for (y in 0 until size) {
            for (x in 0 until size) {
                val ax = (x + 0.5f) / size * 2f - 1f
                val ay = (y + 0.5f) / size * 2f - 1f
                val rad = kotlin.math.sqrt(ax * ax + ay * ay)
                val v = max(0f, 1f - rad).powf(power)
                val g = (v * 255f).toInt() and 0xFF
                px[y * size + x] = (0xFF shl 24) or (g shl 16) or (g shl 8) or g
            }
        }
        return Bitmap.createBitmap(px, size, size, Bitmap.Config.ARGB_8888)
    }

    companion object {
        private const val TARGET_HALO = 0
        private const val TARGET_CORE = 1
    }

    // ================= 8 种效果 =================

    private fun drawBottom(f: FrameFeatures) {
        val n = f.bars.size
        val bw = width.toFloat() / n
        val lineW = max(1f, bw * 0.6f)
        for (i in 0 until n) {
            val v = f.bars[i]
            if (v < 0.015f) continue
            val bh = v * height * 0.76f
            softVBar((i + 0.5f) * bw, height - bh, height.toFloat(), lineW,
                color(i / n.toFloat(), v, x = i / n.toFloat()))
        }
        val w = max(2f, s * 0.003f)
        glowLine(
            floatArrayOf(0f, height - 1f, width.toFloat(), height - 1f),
            color(0.5f, f.level, 100f + 120f * f.level, x = 0.5f),
            w, 0.7f, 0.7f,
        )
    }

    private fun drawMirror(f: FrameFeatures) {
        val n = f.bars.size
        val count = minOf(n, 160)
        val cx = width / 2f
        val cy = height / 2f
        val span = width * 0.475f
        val bw = span / count
        val lineW = max(1f, bw * 0.6f)
        for (i in 0 until count) {
            val v = f.bars[(i.toFloat() / count * n).toInt().coerceAtMost(n - 1)]
            if (v < 0.012f) continue
            val bh = v * height * 0.44f
            val off = (i + 0.5f) * bw
            val colL = color(i / count.toFloat(), v, x = max(0f, (cx - off) / width))
            val colR = color(i / count.toFloat(), v, x = min(1f, (cx + off) / width))
            softVBar(cx - off, cy - bh, cy + bh, lineW, colL)
            softVBar(cx + off, cy - bh, cy + bh, lineW, colR)
        }
        glowLine(
            floatArrayOf(0f, cy, width.toFloat(), cy),
            color(0.7f, f.level, 90f + 130f * f.level, x = 0.5f),
            max(2f, s * 0.003f), 0.7f, 0.7f,
        )
    }

    private fun drawCircle(f: FrameFeatures) {
        val n = f.bars.size
        val cx = width / 2f
        val cy = height / 2f
        val base = s * 0.22f
        val count = if (s >= 800f) 360 else 180
        val w = max(1f, s * 0.0025f)
        for (i in 0 until count) {
            val v = f.bars[(i.toFloat() / count * n).toInt().coerceAtMost(n - 1)]
            if (v < 0.014f) continue
            val ang = 2f * PI.toFloat() * i / count - PI.toFloat() / 2f
            val ca = cos(ang); val sa = sin(ang)
            val outer = base + v * s * 0.27f
            val seg = floatArrayOf(cx + ca * base, cy + sa * base, cx + ca * outer, cy + sa * outer)
            val col = color(i / count.toFloat(), v, x = 0.5f + 0.5f * ca)
            // spokes 层完整 alpha
            linePaint.color = col; linePaint.strokeWidth = w
            spokesC.drawLine(seg[0], seg[1], seg[2], seg[3], linePaint)
            // 主线降权
            linePaint.color = withAlphaScale(col, 0.42f); linePaint.strokeWidth = max(1f, w * 0.8f)
            layerC.drawLine(seg[0], seg[1], seg[2], seg[3], linePaint)
        }
        val r = base * (0.87f + 0.07f * f.pulse)
        val ringA = 130f + 100f * f.bass
        softRing(cx, cy, r, color(0.5f, f.bass, ringA, x = 0.5f), max(3f, s * 0.006f))
    }

    private fun drawDualRing(f: FrameFeatures) {
        val n = f.bars.size
        val cx = width / 2f
        val cy = height / 2f
        val r1 = s * 0.16f
        val r2 = s * 0.31f
        val count = if (s >= 800f) 240 else 160
        val spin = time
        val w = max(1f, s * 0.0022f)
        // 两个渐变基准圆环
        softRing(cx, cy, r1, color(0.25f, 0.35f + 0.25f * f.bass, 120f + 90f * (0.35f + 0.25f * f.bass)), max(3f, s * 0.006f))
        softRing(cx, cy, r2, color(0.75f, 0.30f + 0.25f * f.mid, 120f + 90f * (0.30f + 0.25f * f.mid)), max(3f, s * 0.006f))
        for (i in 0 until count) {
            val v = f.bars[(i.toFloat() / count * n).toInt().coerceAtMost(n - 1)]
            if (v < 0.012f) continue
            val a1 = 2f * PI.toFloat() * i / count + spin * 0.45f
            val a2 = -2f * PI.toFloat() * i / count - spin * 0.28f + PI.toFloat() / count
            drawDualSpoke(cx, cy, a1, r1, 0.13f, i / count.toFloat(), v, w, n)
            drawDualSpoke(cx, cy, a2, r2, 0.19f, 1f - i / count.toFloat(), v, w, n)
            if (v > 0.55f && i % 4 == 0) {
                val ca = cos(a1); val sa = sin(a1)
                linePaint.color = color(i / count.toFloat(), v, 70f, x = 0.5f + 0.5f * ca)
                linePaint.strokeWidth = 1f
                spokesC.drawLine(cx + ca * r1, cy + sa * r1, cx + ca * r2, cy + sa * r2, linePaint)
            }
        }
    }

    private fun drawDualSpoke(
        cx: Float, cy: Float, ang: Float, r0: Float, span: Float,
        cp: Float, v: Float, w: Float, n: Int,
    ) {
        val ca = cos(ang); val sa = sin(ang)
        val outer = r0 + v * s * span
        val col = color(cp, v, x = 0.5f + 0.5f * ca)
        linePaint.color = col; linePaint.strokeWidth = w
        spokesC.drawLine(cx + ca * r0, cy + sa * r0, cx + ca * outer, cy + sa * outer, linePaint)
        linePaint.color = withAlphaScale(col, 0.42f); linePaint.strokeWidth = max(1f, w * 0.8f)
        layerC.drawLine(cx + ca * r0, cy + sa * r0, cx + ca * outer, cy + sa * outer, linePaint)
    }

    private fun drawSpiral(f: FrameFeatures) {
        val n = f.bars.size
        val cx = width / 2f
        val cy = height / 2f
        val arms = 3
        val w = max(2f, s * 0.0032f)
        for (arm in 0 until arms) {
            for (i in 0 until n) {
                val v = f.bars[i]
                if (v < 0.012f) continue
                val ang = i * 0.155f + arm * 2f * PI.toFloat() / arms + time * 0.55f
                val r = s * 0.045f + i / n.toFloat() * s * 0.40f
                val tip = r + v * s * 0.085f
                val ca = cos(ang); val sa = sin(ang)
                val col = color(i / n.toFloat(), v, x = 0.5f + 0.5f * ca)
                linePaint.color = col; linePaint.strokeWidth = w
                spokesC.drawLine(cx + ca * r, cy + sa * r, cx + ca * tip, cy + sa * tip, linePaint)
                linePaint.color = withAlphaScale(col, 0.42f); linePaint.strokeWidth = max(1f, w * 0.8f)
                layerC.drawLine(cx + ca * r, cy + sa * r, cx + ca * tip, cy + sa * tip, linePaint)
            }
        }
        val coreR = s * 0.035f * (1f + f.pulse * 0.8f)
        fillPaint.color = color(0.5f, 1f, 170f + 80f * f.pulse, x = 0.5f)
        layerC.drawCircle(cx, cy, coreR, fillPaint)
        softOrb(cx, cy, coreR * 1.9f, color(0.5f, 1f, 110f, x = 0.5f))
    }

    private fun drawWaveform(f: FrameFeatures) {
        val n = f.bars.size
        val cx = width / 2f
        val cy = height / 2f
        val bw = width.toFloat() / n
        val lineW = max(1f, bw * 0.6f)
        for (i in 0 until n) {
            val v = f.bars[i]
            if (v < 0.02f) continue
            val bh = v * height * 0.30f
            softVBar((i + 0.5f) * bw, cy - bh, cy + bh, lineW,
                color(i / n.toFloat(), v, 45f + 90f * v, x = i / n.toFloat()))
        }
        val wave = f.wave
        val amp = height * 0.30f * (0.5f + f.level)
        val pts = FloatArray(wave.size * 2)
        for (j in wave.indices) {
            pts[j * 2] = j.toFloat() / (wave.size - 1) * width
            pts[j * 2 + 1] = cy + wave[j] * amp
        }
        glowPolyline(pts, color(0.65f, max(0.4f, f.level), 240f, x = 0.65f),
            max(2f, s * 0.0045f), 0.9f, 0.6f)
        val mirror = pts.clone()
        for (j in wave.indices) mirror[j * 2 + 1] = height - pts[j * 2 + 1]
        glowPolyline(mirror, color(0.2f, f.level, 110f, x = 0.2f),
            max(1f, s * 0.002f), 0.6f, 0.75f)
    }

    private fun drawTunnel(f: FrameFeatures) {
        val n = f.bars.size
        val cx = width / 2f
        val cy = height / 2f
        val rings = if (s >= 800f) 30 else 22
        val rMin = s * 0.032f
        val rMax = s * 0.56f
        val ratio = rMax / rMin
        val flow = (time * 0.16f) % 1f
        val radii = FloatArray(rings)
        for (i in 0 until rings) {
            val p = i.toFloat() / rings
            val t = (p + flow) % 1f
            val r = rMin * ratio.powf(t)
            val fade = minOf(1f, t / 0.10f, (1f - t) / 0.16f)
            val v = f.bars[(p * n).toInt() % n]
            val alpha = (60f + 155f * v) * fade * (0.65f + 0.35f * t)
            val w = max(1f, s * (0.0013f + 0.0024f * v) * (0.7f + 0.6f * t))
            softRing(cx, cy, r, color(p, v, alpha, x = 0.80f), max(2f, w), intArrayOf(270, 90))
            softRing(cx, cy, r, color(p, v, alpha, x = 0.20f), max(2f, w), intArrayOf(90, 270))
            radii[i] = r
        }
        // 断续能量放射线
        val spokes = if (s >= 800f) 48 else 36
        val spin = time * 0.07f
        val flowInt = (flow * rings).toInt()
        for (j in 0 until spokes) {
            val p = j.toFloat() / spokes
            val v = f.bars[(p * n).toInt() % n]
            if (v < 0.16f) continue
            val ang = 2f * PI.toFloat() * p + spin
            val ca = cos(ang); val sa = sin(ang)
            val col = color(p, v, 28f + 70f * v, x = 0.5f + 0.5f * ca)
            var k = 3
            while (k < rings - 4) {
                val r0 = radii[(k + flowInt) % rings]
                val r1 = radii[(k + 3 + flowInt) % rings]
                if (r1 > r0) {
                    glowLine(floatArrayOf(cx + ca * r0, cy + sa * r0, cx + ca * r1, cy + sa * r1),
                        col, 1f, 0.6f, 0.75f)
                }
                k += 6
            }
        }
        val coreR = s * 0.011f * (1f + 0.5f * f.pulse)
        softOrb(cx, cy, coreR * 2.4f, color(0.5f, 1f, 170f + 60f * f.pulse, x = 0.5f),
            power = 2.2f, target = TARGET_CORE)
        softOrb(cx, cy, s * (0.05f + 0.02f * f.pulse), color(0.5f, 1f, 150f, x = 0.5f))
    }

    private fun drawParticles(f: FrameFeatures) {
        val cx = width / 2f
        val cy = height / 2f
        if (f.beat) {
            repeat(70) {
                val ang = rng.nextDouble(0.0, 2.0 * PI).toFloat()
                val speed = s * rng.nextDouble(0.002, 0.011).toFloat() * (0.8f + f.bass)
                particles.add(Particle(
                    cx, cy, cos(ang) * speed, sin(ang) * speed,
                    1f, rng.nextDouble(0.005, 0.012).toFloat(),
                    s * rng.nextDouble(0.003, 0.009).toFloat(),
                    rng.nextFloat(), 1f,
                ))
            }
        }
        repeat(20) {
            val i = rng.nextInt(f.bars.size)
            val v = f.bars[i]
            if (v < 0.06f) return@repeat
            val ang = 2f * PI.toFloat() * i / f.bars.size - PI.toFloat() / 2f
            val r = s * rng.nextDouble(0.10, 0.20).toFloat()
            particles.add(Particle(
                cx + cos(ang) * r, cy + sin(ang) * r,
                cos(ang) * s * 0.005f * v, sin(ang) * s * 0.005f * v,
                1f, rng.nextDouble(0.006, 0.011).toFloat(),
                s * 0.006f * v, i / f.bars.size.toFloat(), v,
            ))
        }
        val alive = ArrayList<Particle>()
        for (p in particles) {
            p.x += p.vx; p.y += p.vy
            p.vx *= 0.985f; p.vy *= 0.985f
            p.vy += s * 0.00008f
            p.life -= p.decay
            if (p.life <= 0) continue
            alive.add(p)
            val size = p.size * (0.4f + p.life)
            fillPaint.color = color(p.p, p.v, 220f * p.life, x = p.x / width)
            layerC.drawCircle(p.x, p.y, size, fillPaint)
        }
        // 保留最近 900 个
        if (alive.size > 900) alive.subList(0, alive.size - 900).clear()
        particles.clear(); particles.addAll(alive)

        val coreR = s * 0.075f * (1f + 0.5f * f.pulse)
        for ((ring, radius) in listOf(0.13f, 0.23f, 0.33f).withIndex()) {
            val r = s * radius * (1f + 0.06f * f.pulse)
            val ringAlpha = 40f + 90f * f.level
            glowEllipseOutline(cx, cy, r, color(ring / 3f, f.mid, ringAlpha, x = ring / 3f),
                max(1f, s * 0.002f), 0.6f, 0.7f)
            linePaint.color = color(ring / 3f, f.mid, ringAlpha * 0.85f, x = ring / 3f)
            linePaint.strokeWidth = max(3f, s * 0.006f)
            haloC.drawOval(RectF(cx - r, cy - r, cx + r, cy + r), linePaint)
        }
        var i = 0
        while (i < f.bars.size) {
            val v = f.bars[i]
            if (v >= 0.06f) {
                val ang = 2f * PI.toFloat() * i / f.bars.size - PI.toFloat() / 2f
                val ca = cos(ang); val sa = sin(ang)
                glowLine(
                    floatArrayOf(cx + ca * coreR, cy + sa * coreR,
                        cx + ca * (coreR + v * s * 0.26f), cy + sa * (coreR + v * s * 0.26f)),
                    color(i / f.bars.size.toFloat(), v, x = 0.5f + 0.5f * ca),
                    max(1f, s * 0.002f), 0.65f, 0.75f,
                )
            }
            i += 3
        }
        val coreCol = color(0.5f, f.bass, 205f + 25f * f.bass, x = 0.5f)
        softOrb(cx, cy, coreR * 1.7f, coreCol, power = 2.4f, target = TARGET_CORE)
        softOrb(cx, cy, coreR * 2.3f, color(0.5f, f.bass, 150f, x = 0.5f), power = 2.2f)
    }
}
