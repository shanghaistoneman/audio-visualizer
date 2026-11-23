package com.example.audiovisualizer.core

import android.graphics.Bitmap
import kotlin.math.max

/**
 * 高性能模糊工具：可分离滑动窗口盒式模糊，3 次迭代近似高斯。
 * 对应 Pillow 的 ImageFilter.GaussianBlur，但在低分辨率位图上执行以保证手机性能。
 * 与 Pillow 一致：对 R/G/B/A 各通道独立模糊（非预乘 alpha）。
 */
object Blur {

    /** 对 ARGB int 数组做可分离盒式模糊，radius 为像素半径，iterations 通常为 3。 */
    fun boxBlur(
        src: IntArray,
        dst: IntArray,
        w: Int,
        h: Int,
        radius: Int,
        iterations: Int = 3,
    ) {
        if (radius < 1 || w <= 0 || h <= 0) {
            System.arraycopy(src, 0, dst, 0, minOf(src.size, dst.size))
            return
        }
        val tmp = IntArray(src.size)
        var input = src
        var output = tmp
        repeat(iterations) {
            blurHorizontal(input, output, w, h, radius)
            blurVertical(output, input, w, h, radius)
            // 下一轮 input/output 保持不变（水平写 tmp，垂直写回 input）
        }
        if (output !== dst) System.arraycopy(input, 0, dst, 0, minOf(input.size, dst.size))
    }

    private fun blurHorizontal(src: IntArray, dst: IntArray, w: Int, h: Int, r: Int) {
        val win = 2 * r + 1
        for (y in 0 until h) {
            val row = y * w
            var sumA = 0; var sumR = 0; var sumG = 0; var sumB = 0
            // 初始窗口：x = -r..r，负数部分夹紧到 0
            for (k in -r..r) {
                val c = src[row + max(0, minOf(w - 1, k))]
                sumA += (c ushr 24) and 0xFF
                sumR += (c ushr 16) and 0xFF
                sumG += (c ushr 8) and 0xFF
                sumB += c and 0xFF
            }
            for (x in 0 until w) {
                dst[row + x] = pack(sumA / win, sumR / win, sumG / win, sumB / win)
                // 滑动：移除 x-r，加入 x+r+1
                val outC = src[row + max(0, minOf(w - 1, x - r))]
                sumA -= (outC ushr 24) and 0xFF
                sumR -= (outC ushr 16) and 0xFF
                sumG -= (outC ushr 8) and 0xFF
                sumB -= outC and 0xFF
                val inC = src[row + max(0, minOf(w - 1, x + r + 1))]
                sumA += (inC ushr 24) and 0xFF
                sumR += (inC ushr 16) and 0xFF
                sumG += (inC ushr 8) and 0xFF
                sumB += inC and 0xFF
            }
        }
    }

    private fun blurVertical(src: IntArray, dst: IntArray, w: Int, h: Int, r: Int) {
        val win = 2 * r + 1
        for (x in 0 until w) {
            var sumA = 0; var sumR = 0; var sumG = 0; var sumB = 0
            for (k in -r..r) {
                val c = src[max(0, minOf(h - 1, k)) * w + x]
                sumA += (c ushr 24) and 0xFF
                sumR += (c ushr 16) and 0xFF
                sumG += (c ushr 8) and 0xFF
                sumB += c and 0xFF
            }
            for (y in 0 until h) {
                dst[y * w + x] = pack(sumA / win, sumR / win, sumG / win, sumB / win)
                val outC = src[max(0, minOf(h - 1, y - r)) * w + x]
                sumA -= (outC ushr 24) and 0xFF
                sumR -= (outC ushr 16) and 0xFF
                sumG -= (outC ushr 8) and 0xFF
                sumB -= outC and 0xFF
                val inC = src[max(0, minOf(h - 1, y + r + 1)) * w + x]
                sumA += (inC ushr 24) and 0xFF
                sumR += (inC ushr 16) and 0xFF
                sumG += (inC ushr 8) and 0xFF
                sumB += inC and 0xFF
            }
        }
    }

    private fun pack(a: Int, r: Int, g: Int, b: Int): Int =
        ((a and 0xFF) shl 24) or ((r and 0xFF) shl 16) or ((g and 0xFF) shl 8) or (b and 0xFF)

    /** 生成一张位图的模糊版本（原尺寸），内部降采样到 1/scale 后模糊再放大。 */
    fun blurBitmap(src: Bitmap, radius: Float, scale: Int = 2): Bitmap {
        val sw = max(2, src.width / scale)
        val sh = max(2, src.height / scale)
        val small = Bitmap.createScaledBitmap(src, sw, sh, true)
        val px = IntArray(sw * sh)
        small.getPixels(px, 0, sw, 0, 0, sw, sh)
        val blurred = IntArray(px.size)
        boxBlur(px, blurred, sw, sh, max(1, (radius / scale).toInt()), 3)
        small.setPixels(blurred, 0, sw, 0, 0, sw, sh)
        val big = Bitmap.createScaledBitmap(small, src.width, src.height, true)
        small.recycle()
        return big
    }
}
