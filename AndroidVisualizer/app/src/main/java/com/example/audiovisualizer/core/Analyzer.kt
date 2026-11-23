package com.example.audiovisualizer.core

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow
import kotlin.math.sqrt

/**
 * 离线频谱分析：STFT -> 对数频段 -> 自适应归一化 + 节拍检测。
 * 与 Python 端 analysis.py 的算法逐步骤对齐。
 */
class SpectrumAnalyzer(
    private val samples: FloatArray,
    private val sampleRate: Int,
    private val fps: Int = 30,
    private val bars: Int = 96,
    private val fftSize: Int = 4096,
    private val attack: Float = 0.62f,
    private val release: Float = 0.16f,
) {
    private val hop: Int = max(1, sampleRate / fps)
    private val frameCount: Int = max(1, (samples.size.toDouble() / hop).toInt())

    /** 对数频率刻度的频段边界 bin 索引，长度 bars+1。 */
    private fun bandEdges(): IntArray {
        val nyquist = sampleRate / 2.0
        val highHz = min(20000.0, nyquist * 0.96)
        val edges = IntArray(bars + 1)
        for (i in 0..bars) {
            val hz = 20.0 * pow(highHz / 20.0, i.toDouble() / bars)
            var bin = floor(hz * fftSize / sampleRate).toInt()
            bin = max(1, min(fftSize / 2, bin))
            edges[i] = bin
        }
        for (i in 1..bars) {
            if (edges[i] <= edges[i - 1]) edges[i] = edges[i - 1] + 1
            if (edges[i] > fftSize / 2) edges[i] = fftSize / 2
        }
        return edges
    }

    fun analyze(): List<FrameFeatures> {
        val n = fftSize
        // Hann 窗
        val window = FloatArray(n) { i ->
            (0.5 - 0.5 * cos(2.0 * PI * i / (n - 1))).toFloat()
        }
        val edges = bandEdges()

        // raw[frame][bar]
        val raw = Array(frameCount) { FloatArray(bars) }
        val waves = Array(frameCount) { FloatArray(128) }
        val waveStep = max(1, n / 128)

        for (t in 0 until frameCount) {
            val start = t * hop
            val seg = FloatArray(n)
            for (k in 0 until n) {
                val idx = start + k
                seg[k] = if (idx < samples.size) samples[idx] * window[k] else 0f
            }
            val spec = Fft.rfftMagnitude(seg, n)
            for (b in 0 until bars) {
                val lo = edges[b]
                val hi = edges[b + 1]
                var sum = 0.0
                for (k in lo until hi) sum += spec[k]
                raw[t][b] = (sum / max(1, hi - lo)).toFloat()
            }
            for (j in 0 until 128) {
                val idx = j * waveStep
                // 波形用未加窗的原始采样
                val sidx = start + idx
                waves[t][j] = if (sidx < samples.size) samples[sidx] else 0f
            }
        }

        // 逐频段自适应归一化（分位数估计本底噪声与峰值）
        // db[bar][frame] 转置存储便于求分位数
        val dbByBar = Array(bars) { FloatArray(frameCount) }
        for (t in 0 until frameCount) {
            for (b in 0 until bars) {
                dbByBar[b][t] = (20.0 * log10(raw[t][b].toDouble() + 1e-7)).toFloat()
            }
        }
        val norm = Array(frameCount) { FloatArray(bars) }
        for (b in 0 until bars) {
            val col = dbByBar[b]
            val floor = percentile(col, 25.0)
            var peak = percentile(col, 99.5)
            peak = max(peak, floor + 12f)
            val denom = max(1e-6f, peak - floor)
            for (t in 0 until frameCount) {
                norm[t][b] = Options.clamp01((col[t] - floor) / denom)
            }
        }

        // 频域轻微平滑（3点核 0.2/0.6/0.2，边缘复制）
        val freqSmoothed = Array(frameCount) { FloatArray(bars) }
        for (t in 0 until frameCount) {
            for (b in 0 until bars) {
                val left = norm[t][max(0, b - 1)]
                val mid = norm[t][b]
                val right = norm[t][min(bars - 1, b + 1)]
                freqSmoothed[t][b] = 0.2f * left + 0.6f * mid + 0.2f * right
            }
        }

        // 时域 attack/release 平滑
        val smoothed = Array(frameCount) { FloatArray(bars) }
        val prev = FloatArray(bars)
        for (t in 0 until frameCount) {
            for (b in 0 until bars) {
                val cur = freqSmoothed[t][b]
                val a = if (cur > prev[b]) attack else release
                prev[b] = prev[b] + a * (cur - prev[b])
                smoothed[t][b] = prev[b]
            }
        }

        // 节拍检测
        val lowCount = max(4, bars / 8)
        val energy = FloatArray(frameCount)
        var maxEnergy = 0f
        for (t in 0 until frameCount) {
            var s = 0f
            for (b in 0 until lowCount) s += raw[t][b]
            energy[t] = s / lowCount
            maxEnergy = max(maxEnergy, energy[t])
        }
        var meanEnergy = if (frameCount > 0) energy[0] else 0f
        val beats = BooleanArray(frameCount)
        val pulse = FloatArray(frameCount)
        var lastBeat = -999
        val minGap = max(3, fps / 6)
        for (t in 0 until frameCount) {
            val e = if (maxEnergy > 1e-9f) energy[t] / maxEnergy else 0f
            meanEnergy = meanEnergy * 0.97f + e * 0.03f
            if (t > 3 && e > meanEnergy * 1.35f && e > 0.06f && (t - lastBeat) >= minGap) {
                beats[t] = true
                pulse[t] = 1f
                lastBeat = t
            }
            if (t > 0) pulse[t] = max(pulse[t], pulse[t - 1] * 0.86f)
        }

        // 组装特征
        val lowEnd = max(2, bars / 5)
        val highStart = (bars * 0.6).toInt()
        val out = ArrayList<FrameFeatures>(frameCount)
        for (t in 0 until frameCount) {
            val f = smoothed[t]
            var level = 0f
            var bass = 0f
            var mid = 0f
            var treble = 0f
            for (v in f) level += v
            level /= bars
            for (b in 0 until lowEnd) bass += f[b]
            bass /= lowEnd
            for (b in lowEnd until highStart) mid += f[b]
            mid /= max(1, highStart - lowEnd)
            for (b in highStart until bars) treble += f[b]
            treble /= max(1, bars - highStart)
            out.add(
                FrameFeatures(
                    bars = f.copyOf(),
                    wave = waves[t],
                    level = level,
                    bass = bass,
                    mid = mid,
                    treble = treble,
                    pulse = pulse[t],
                    beat = beats[t],
                    time = t.toFloat() / fps,
                )
            )
        }
        return out
    }

    /** 线性插值分位数，对应 numpy.percentile 默认 method='linear'。 */
    private fun percentile(values: FloatArray, p: Double): Float {
        if (values.isEmpty()) return 0f
        val sorted = values.copyOf()
        sorted.sort()
        val index = (sorted.size - 1) * p
        val lo = floor(index).toInt()
        val hi = min(sorted.size - 1, lo + 1)
        val frac = (index - lo).toFloat()
        return sorted[lo] * (1f - frac) + sorted[hi] * frac
    }

    val duration: Float get() = samples.size.toFloat() / sampleRate
}
