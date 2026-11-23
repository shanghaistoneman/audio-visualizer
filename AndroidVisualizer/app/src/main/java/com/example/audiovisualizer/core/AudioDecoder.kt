package com.example.audiovisualizer.core

import android.content.Context
import android.media.MediaCodec
import android.media.MediaExtractor
import android.media.MediaFormat
import android.net.Uri
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.max

/** 音频解码：用系统 MediaCodec 把 mp3/wav/m4a/flac 解码为单声道 float PCM。 */
object AudioDecoder {

    /**
     * 解码为 44100Hz 单声道 float 采样。
     * 所有格式统一重采样到 44100Hz，与分析器期望一致。
     */
    fun decode(context: Context, uri: Uri, targetRate: Int = 44100): FloatArray {
        val extractor = MediaExtractor()
        var codec: MediaCodec? = null
        try {
            extractor.setDataSource(context, uri, null)
            val trackIndex = selectAudioTrack(extractor)
                ?: throw IllegalArgumentException("文件中没有音频轨道")
            extractor.selectTrack(trackIndex)
            val format = extractor.getTrackFormat(trackIndex)
            val mime = format.getString(MediaFormat.KEY_MIME)
                ?: throw IllegalArgumentException("无法读取音频编码格式")

            codec = MediaCodec.createDecoderByType(mime)
            codec.configure(format, null, null, 0)
            codec.start()

            val srcRate = if (format.containsKey(MediaFormat.KEY_SAMPLE_RATE))
                format.getInteger(MediaFormat.KEY_SAMPLE_RATE) else 44100
            val channels = if (format.containsKey(MediaFormat.KEY_CHANNEL_COUNT))
                format.getInteger(MediaFormat.KEY_CHANNEL_COUNT) else 1

            val raw = decodeToMono(codec, extractor, srcRate, channels)
            return if (srcRate == targetRate) raw else resample(raw, srcRate, targetRate)
        } finally {
            codec?.let {
                try { it.stop() } catch (_: Exception) {}
                try { it.release() } catch (_: Exception) {}
            }
            extractor.release()
        }
    }

    private fun selectAudioTrack(extractor: MediaExtractor): Int? {
        for (i in 0 until extractor.trackCount) {
            val mime = extractor.getTrackFormat(i).getString(MediaFormat.KEY_MIME) ?: continue
            if (mime.startsWith("audio/")) return i
        }
        return null
    }

    /** 解码并把多声道混合为单声道，返回 float 数组。 */
    private fun decodeToMono(
        codec: MediaCodec,
        extractor: MediaExtractor,
        sampleRate: Int,
        channels: Int,
    ): FloatArray {
        val info = MediaCodec.BufferInfo()
        val result = java.io.ByteArrayOutputStream()
        var sawInputEos = false
        var sawOutputEos = false
        val timeoutUs = 10000L

        while (!sawOutputEos) {
            if (!sawInputEos) {
                val inIndex = codec.dequeueInputBuffer(timeoutUs)
                if (inIndex >= 0) {
                    val buffer = codec.getInputBuffer(inIndex) ?: break
                    buffer.clear()
                    val size = extractor.readSampleData(buffer, 0)
                    if (size < 0) {
                        codec.queueInputBuffer(
                            inIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM
                        )
                        sawInputEos = true
                    } else {
                        codec.queueInputBuffer(inIndex, 0, size, extractor.sampleTime, 0)
                        extractor.advance()
                    }
                }
            }

            val outIndex = codec.dequeueOutputBuffer(info, timeoutUs)
            when {
                outIndex == MediaCodec.INFO_OUTPUT_FORMAT_CHANGED -> {
                    // 解码器实际输出格式可能与源文件不同，更新采样率/声道数
                }
                outIndex >= 0 -> {
                    val buffer = codec.getOutputBuffer(outIndex)
                    if (buffer != null && info.size > 0) {
                        val bytes = ByteArray(info.size)
                        buffer.position(info.offset)
                        buffer.get(bytes, 0, info.size)
                        result.write(bytes, 0, bytes.size)
                    }
                    codec.releaseOutputBuffer(outIndex, false)
                    if (info.flags and MediaCodec.BUFFER_FLAG_END_OF_STREAM != 0) {
                        sawOutputEos = true
                    }
                }
            }
        }

        // MediaCodec 解码 PCM 通常是 16bit 小端（PCM 16-bit）
        val pcm = result.toByteArray()
        val totalSamples = pcm.size / 2 / max(1, channels)
        val out = FloatArray(totalSamples)
        val bb = ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN)
        var i = 0
        while (i < totalSamples) {
            var sum = 0
            for (c in 0 until channels) {
                if (bb.remaining() >= 2) sum += bb.short.toInt()
            }
            out[i] = (sum / max(1, channels)).toFloat() / 32768f
            i++
        }
        return out
    }

    /** 线性插值重采样。 */
    private fun resample(src: FloatArray, srcRate: Int, dstRate: Int): FloatArray {
        if (src.isEmpty()) return src
        val ratio = srcRate.toDouble() / dstRate
        val outSize = max(1, (src.size / ratio).toInt())
        val out = FloatArray(outSize)
        for (i in 0 until outSize) {
            val pos = i * ratio
            val i0 = pos.toInt().coerceAtMost(src.size - 1)
            val i1 = (i0 + 1).coerceAtMost(src.size - 1)
            val frac = (pos - i0).toFloat()
            out[i] = src[i0] * (1f - frac) + src[i1] * frac
        }
        return out
    }
}
