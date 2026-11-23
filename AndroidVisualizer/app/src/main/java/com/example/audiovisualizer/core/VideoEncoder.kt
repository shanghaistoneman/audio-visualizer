package com.example.audiovisualizer.core

import android.graphics.Bitmap
import android.media.MediaCodec
import android.media.MediaCodecInfo
import android.media.MediaFormat
import android.media.MediaMuxer
import java.nio.file.Files
import java.nio.file.Paths
import kotlin.math.max

/**
 * 视频编码：MediaCodec(H.264) + 可选 AAC 音频 + MediaMuxer 输出 MP4。
 * 逐帧接收透明 RGBA 位图，先合成到指定背景色，再转 NV12 送入编码器。
 * 安卓端 MediaCodec 不支持 alpha，因此只输出黑幕/绿幕/遮罩三种 MP4。
 */
class VideoEncoder(
    private val outputPath: String,
    private val width: Int,
    private val height: Int,
    private val fps: Int,
    private val bitRate: Int = defaultBitrate(width, height),
    private val background: Int = BG_BLACK,
    private val matteOnly: Boolean = false,
    private val audioPcm: FloatArray? = null,
    private val audioRate: Int = 44100,
) {
    companion object {
        const val BG_BLACK = 0
        const val BG_GREEN = 1
        const val BG_MATTE = 2

        fun defaultBitrate(w: Int, h: Int): Int = when {
            w * h >= 1920 * 1080 -> 12_000_000
            w * h >= 720 * 1280 || w * h >= 1280 * 720 -> 8_000_000
            else -> 5_000_000
        }
    }

    private var videoCodec: MediaCodec? = null
    private var audioCodec: MediaCodec? = null
    private var muxer: MediaMuxer? = null
    private var videoTrack = -1
    private var audioTrack = -1
    private var started = false
    private var frameIndex = 0
    private val videoInfo = MediaCodec.BufferInfo()
    private val audioInfo = MediaCodec.BufferInfo()

    private val rgbaBuf = IntArray(width * height)
    private val yuvBuf = ByteArray(width * height * 3 / 2)

    // 音频编码进度（按输入采样位置）
    private var audioInputPos = 0
    private var audioDone = false

    fun start() {
        // --- 视频编码器 ---
        val vfmt = MediaFormat.createVideoFormat(MediaFormat.MIMETYPE_VIDEO_AVC, width, height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatYUV420SemiPlanar)
            setInteger(MediaFormat.KEY_BIT_RATE, bitRate)
            setInteger(MediaFormat.KEY_FRAME_RATE, fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, 2)
        }
        val vc = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_VIDEO_AVC)
        vc.configure(vfmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        vc.start()
        videoCodec = vc

        Files.deleteIfExists(Paths.get(outputPath))
        val m = MediaMuxer(outputPath, MediaMuxer.OutputFormat.MUXER_OUTPUT_MPEG_4)
        muxer = m
        videoTrack = m.addTrack(vc.outputFormat)

        // --- 音频编码器（可选） ---
        if (audioPcm != null && audioPcm.isNotEmpty()) {
            val afmt = MediaFormat.createAudioFormat(MediaFormat.MIMETYPE_AUDIO_AAC, audioRate, 1).apply {
                setInteger(MediaFormat.KEY_BIT_RATE, 128_000)
                setInteger(MediaFormat.KEY_AAC_PROFILE, MediaCodecInfo.CodecCapabilities.AACObjectLC)
            }
            val ac = MediaCodec.createEncoderByType(MediaFormat.MIMETYPE_AUDIO_AAC)
            ac.configure(afmt, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
            ac.start()
            audioCodec = ac
            audioTrack = m.addTrack(ac.outputFormat)
        }

        m.start()
        started = true
    }

    /** 写入一帧透明 RGBA 位图，同时按需推进音频编码。 */
    fun writeFrame(frame: Bitmap) {
        if (!started) throw IllegalStateException("编码器未启动")
        frame.getPixels(rgbaBuf, 0, width, 0, 0, width, height)
        rgbaToNv12(rgbaBuf, yuvBuf, width, height, background, matteOnly)

        val vc = videoCodec ?: return
        val inIndex = vc.dequeueInputBuffer(50_000L)
        if (inIndex >= 0) {
            val input = vc.getInputBuffer(inIndex) ?: return
            input.clear()
            input.put(yuvBuf)
            val ptsUs = (frameIndex.toLong() * 1_000_000L) / fps
            vc.queueInputBuffer(inIndex, 0, yuvBuf.size, ptsUs, 0)
            frameIndex++
        }
        drainVideo(false)

        // 音频按视频时间轴推进：每帧应喂入的采样数
        if (audioCodec != null && !audioDone) {
            val targetPos = minOf(audioPcm!!.size, (frameIndex.toLong() * audioRate / fps).toInt())
            feedAudioUntil(targetPos)
        }
    }

    fun finish() {
        val vc = videoCodec
        if (vc != null && started) {
            val inIndex = vc.dequeueInputBuffer(50_000L)
            if (inIndex >= 0) {
                vc.queueInputBuffer(inIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
            }
            drainVideo(true)
        }
        // 冲刷音频
        if (audioCodec != null) {
            feedAudioUntil(audioPcm!!.size)
            val ac = audioCodec!!
            val inIndex = ac.dequeueInputBuffer(50_000L)
            if (inIndex >= 0) {
                ac.queueInputBuffer(inIndex, 0, 0, 0, MediaCodec.BUFFER_FLAG_END_OF_STREAM)
            }
            drainAudio(true)
        }
        try { muxer?.stop() } catch (_: Exception) {}
        try { muxer?.release() } catch (_: Exception) {}
        try { videoCodec?.stop() } catch (_: Exception) {}
        try { videoCodec?.release() } catch (_: Exception) {}
        try { audioCodec?.stop() } catch (_: Exception) {}
        try { audioCodec?.release() } catch (_: Exception) {}
        started = false
    }

    fun cancel() {
        try { muxer?.stop() } catch (_: Exception) {}
        try { muxer?.release() } catch (_: Exception) {}
        try { videoCodec?.stop() } catch (_: Exception) {}
        try { videoCodec?.release() } catch (_: Exception) {}
        try { audioCodec?.stop() } catch (_: Exception) {}
        try { audioCodec?.release() } catch (_: Exception) {}
        started = false
        try { java.io.File(outputPath).delete() } catch (_: Exception) {}
    }

    // ---------------- 音频 ----------------

    private fun feedAudioUntil(targetPos: Int) {
        val ac = audioCodec ?: return
        val pcm = audioPcm ?: return
        val samplesPerFrame = 1024
        while (audioInputPos < targetPos) {
            val count = minOf(samplesPerFrame, pcm.size - audioInputPos)
            if (count <= 0) break
            val index = ac.dequeueInputBuffer(50_000L)
            if (index < 0) break
            val input = ac.getInputBuffer(index) ?: break
            input.clear()
            // 打包为 PCM 16bit 小端
            val bytes = ByteArray(count * 2)
            for (i in 0 until count) {
                val s = (max(-1f, minOf(1f, pcm[audioInputPos + i])) * 32767).toInt().toShort()
                bytes[i * 2] = (s.toInt() and 0xFF).toByte()
                bytes[i * 2 + 1] = ((s.toInt() ushr 8) and 0xFF).toByte()
            }
            input.put(bytes)
            val ptsUs = (audioInputPos.toLong() * 1_000_000L) / audioRate
            ac.queueInputBuffer(index, 0, bytes.size, ptsUs, 0)
            audioInputPos += count
        }
        drainAudio(false)
    }

    private fun drainAudio(end: Boolean) {
        val ac = audioCodec ?: return
        val m = muxer ?: return
        var index = ac.dequeueOutputBuffer(audioInfo, if (end) 50_000L else 0)
        var guard = 0
        while (index >= 0 && guard < 100000) {
            guard++
            val out = ac.getOutputBuffer(index)
            if (out != null && audioInfo.size > 0) {
                out.position(audioInfo.offset)
                out.limit(audioInfo.offset + audioInfo.size)
                m.writeSampleData(audioTrack, out, audioInfo)
            }
            ac.releaseOutputBuffer(index, false)
            index = ac.dequeueOutputBuffer(audioInfo, if (end) 50_000L else 0)
        }
    }

    // ---------------- 视频 drain ----------------

    private fun drainVideo(end: Boolean) {
        val vc = videoCodec ?: return
        val m = muxer ?: return
        var index = vc.dequeueOutputBuffer(videoInfo, if (end) 50_000L else 0)
        var guard = 0
        while (index >= 0 && guard < 100000) {
            guard++
            val out = vc.getOutputBuffer(index)
            if (out != null && videoInfo.size > 0) {
                out.position(videoInfo.offset)
                out.limit(videoInfo.offset + videoInfo.size)
                m.writeSampleData(videoTrack, out, videoInfo)
            }
            vc.releaseOutputBuffer(index, false)
            index = vc.dequeueOutputBuffer(videoInfo, if (end) 50_000L else 0)
        }
    }

    /** RGBA(ARGB_8888) -> NV12，4:2:0 半色度平面。 */
    private fun rgbaToNv12(
        src: IntArray, dst: ByteArray, w: Int, h: Int,
        bgMode: Int, matte: Boolean,
    ) {
        val yPlane = w * h
        for (y in 0 until h) {
            val row = y * w
            for (x in 0 until w) {
                val c = src[row + x]
                val a = ((c ushr 24) and 0xFF) / 255f
                var r = (c ushr 16) and 0xFF
                var g = (c ushr 8) and 0xFF
                var b = c and 0xFF
                if (matte || bgMode == BG_MATTE) {
                    val v = minOf(255, ((c ushr 24) and 0xFF) * 103 / 100)
                    r = v; g = v; b = v
                } else {
                    val br = 0
                    val bg = if (bgMode == BG_GREEN) 255 else 0
                    val bb = 0
                    r = (br * (1f - a) + r * a).toInt()
                    g = (bg * (1f - a) + g * a).toInt()
                    b = (bb * (1f - a) + b * a).toInt()
                }
                val yy = (0.299f * r + 0.587f * g + 0.114f * b).toInt()
                dst[row + x] = clampByte(yy)
            }
        }
        var uvIndex = yPlane
        for (y in 0 until h step 2) {
            for (x in 0 until w step 2) {
                var ur = 0; var ug = 0; var ub = 0; var cnt = 0
                for (dy in 0..1) {
                    val yy = y + dy
                    if (yy >= h) continue
                    for (dx in 0..1) {
                        val xx = x + dx
                        if (xx >= w) continue
                        val c = src[yy * w + xx]
                        val a = ((c ushr 24) and 0xFF) / 255f
                        var r = (c ushr 16) and 0xFF
                        var g = (c ushr 8) and 0xFF
                        var b = c and 0xFF
                        if (matte || bgMode == BG_MATTE) {
                            val v = minOf(255, ((c ushr 24) and 0xFF) * 103 / 100)
                            r = v; g = v; b = v
                        } else {
                            val br = 0
                            val bg = if (bgMode == BG_GREEN) 255 else 0
                            val bb = 0
                            r = (br * (1f - a) + r * a).toInt()
                            g = (bg * (1f - a) + g * a).toInt()
                            b = (bb * (1f - a) + b * a).toInt()
                        }
                        ur += r; ug += g; ub += b; cnt++
                    }
                }
                val mr = ur / max(1, cnt)
                val mg = ug / max(1, cnt)
                val mb = ub / max(1, cnt)
                val u = (128f - 0.169f * mr - 0.331f * mg + 0.5f * mb).toInt()
                val v = (128f + 0.5f * mr - 0.419f * mg - 0.081f * mb).toInt()
                dst[uvIndex++] = clampByte(u)
                dst[uvIndex++] = clampByte(v)
            }
        }
    }

    private fun clampByte(v: Int): Byte = v.coerceIn(0, 255).toByte()
}
