package com.example.audiovisualizer.core

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * 纯 Kotlin 的 radix-2 Cooley-Tukey FFT。
 * 对应 Python 端 numpy.fft.rfft：输入实数序列，输出幅度谱（0..N/2 共 N/2+1 点）。
 */
object Fft {

    /** 就地 FFT（复数交错存储：re[0],im[0],re[1],im[1]...）。n 必须为 2 的幂。 */
    private fun fftInPlace(re: FloatArray, im: FloatArray, n: Int) {
        // 位反转置换
        var j = 0
        for (i in 1 until n) {
            var bit = n shr 1
            while (j and bit != 0) {
                j = j xor bit
                bit = bit shr 1
            }
            j = j xor bit
            if (i < j) {
                var t = re[i]; re[i] = re[j]; re[j] = t
                t = im[i]; im[i] = im[j]; im[j] = t
            }
        }

        // 逐级蝶形运算
        var len = 2
        while (len <= n) {
            val ang = -2.0 * PI / len
            val wlenR = cos(ang).toFloat()
            val wlenI = sin(ang).toFloat()
            var i = 0
            while (i < n) {
                var wr = 1f
                var wi = 0f
                val half = len shr 1
                for (k in 0 until half) {
                    val ur = re[i + k]
                    val ui = im[i + k]
                    val vr = re[i + k + half] * wr - im[i + k + half] * wi
                    val vi = re[i + k + half] * wi + im[i + k + half] * wr
                    re[i + k] = ur + vr
                    im[i + k] = ui + vi
                    re[i + k + half] = ur - vr
                    im[i + k + half] = ui - vi
                    val nwr = wr * wlenR - wi * wlenI
                    wi = wr * wlenI + wi * wlenR
                    wr = nwr
                }
                i += len
            }
            len = len shl 1
        }
    }

    /**
     * 计算实数序列的幅度谱，长度 n/2+1。
     * @param src 输入实数样本（长度至少 n）
     * @param n FFT 点数，必须是 2 的幂
     */
    fun rfftMagnitude(src: FloatArray, n: Int): FloatArray {
        val re = FloatArray(n)
        val im = FloatArray(n)
        val copy = minOf(n, src.size)
        System.arraycopy(src, 0, re, 0, copy)
        fftInPlace(re, im, n)
        val out = FloatArray(n / 2 + 1)
        for (k in out.indices) {
            out[k] = sqrt(re[k] * re[k] + im[k] * im[k])
        }
        return out
    }
}
