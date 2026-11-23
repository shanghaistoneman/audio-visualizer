package com.example.audiovisualizer.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Environment
import android.provider.OpenableColumns
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.ImageView
import android.widget.ProgressBar
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.example.audiovisualizer.R
import com.example.audiovisualizer.core.Demo
import com.example.audiovisualizer.core.Generator
import com.example.audiovisualizer.core.Options
import com.example.audiovisualizer.core.RenderConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.atomic.AtomicBoolean

class MainActivity : AppCompatActivity() {

    private lateinit var spinMode: Spinner
    private lateinit var spinTheme: Spinner
    private lateinit var spinSize: Spinner
    private lateinit var spinFps: Spinner
    private lateinit var spinBars: Spinner
    private lateinit var spinGlow: Spinner
    private lateinit var spinFormat: Spinner
    private lateinit var checkAudio: CheckBox
    private lateinit var previewImage: ImageView
    private lateinit var previewLoading: ProgressBar
    private lateinit var progressBar: ProgressBar
    private lateinit var statusText: TextView
    private lateinit var audioName: TextView
    private lateinit var btnGenerate: Button
    private lateinit var btnCancel: Button
    private lateinit var btnOpenOutput: Button

    private var audioUri: Uri? = null
    private var previewJob: Job? = null
    private var generateJob: Job? = null
    private val cancelFlag = AtomicBoolean(false)

    private val pickAudio = registerForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri != null) {
            audioUri = uri
            audioName.text = queryName(uri) ?: "已选择音频"
            Toast.makeText(this, "已选择：${audioName.text}", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        spinMode = findViewById(R.id.spinMode)
        spinTheme = findViewById(R.id.spinTheme)
        spinSize = findViewById(R.id.spinSize)
        spinFps = findViewById(R.id.spinFps)
        spinBars = findViewById(R.id.spinBars)
        spinGlow = findViewById(R.id.spinGlow)
        spinFormat = findViewById(R.id.spinFormat)
        checkAudio = findViewById(R.id.checkAudio)
        previewImage = findViewById(R.id.previewImage)
        previewLoading = findViewById(R.id.previewLoading)
        progressBar = findViewById(R.id.progressBar)
        statusText = findViewById(R.id.statusText)
        audioName = findViewById(R.id.audioName)
        btnGenerate = findViewById(R.id.btnGenerate)
        btnCancel = findViewById(R.id.btnCancel)
        btnOpenOutput = findViewById(R.id.btnOpenOutput)

        // 默认项与桌面版一致：中央镜像 / 霓虹青紫 / 30fps / 192 柱 / 发光 1.5 / MP4 黑幕
        spinMode.setSelection(Options.MODE_KEYS.indexOf("mirror"))
        spinTheme.setSelection(Options.THEME_KEYS.indexOf("neon"))
        spinSize.setSelection(1) // 720x1280 竖屏流畅（手机默认）
        spinFps.setSelection(1)  // 30
        spinBars.setSelection(4) // 192
        spinGlow.setSelection(3) // 1.5
        spinFormat.setSelection(0) // mp4-black

        // 参数变化时刷新示例预览（防抖）
        val refresh = object : android.widget.AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: android.widget.AdapterView<*>?, view: View?, pos: Int, id: Long) {
                schedulePreview()
            }
            override fun onNothingSelected(parent: android.widget.AdapterView<*>?) {}
        }
        listOf(spinMode, spinTheme, spinSize, spinFps, spinBars, spinGlow, spinFormat)
            .forEach { it.onItemSelectedListener = refresh }
        checkAudio.setOnCheckedChangeListener { _, _ -> schedulePreview() }

        findViewById<Button>(R.id.btnPickAudio).setOnClickListener {
            pickAudio.launch("audio/*")
        }
        btnGenerate.setOnClickListener { startGenerate() }
        btnCancel.setOnClickListener {
            cancelFlag.set(true)
            statusText.text = "正在取消…"
        }
        btnOpenOutput.setOnClickListener { openOutputFolder() }

        schedulePreview()
    }

    // ---------------- 参数 ----------------

    private fun sizePair(): IntArray {
        val values = resources.getStringArray(R.array.size_values)
        val parts = values[spinSize.selectedItemPosition].split("x")
        return intArrayOf(parts[0].toInt(), parts[1].toInt())
    }

    private fun currentConfig(): RenderConfig {
        val size = sizePair()
        return RenderConfig(
            inputUri = audioUri?.toString() ?: "",
            outputDir = outputDir().absolutePath,
            mode = Options.MODE_KEYS[spinMode.selectedItemPosition],
            theme = Options.THEME_KEYS[spinTheme.selectedItemPosition],
            fmt = Options.FORMAT_KEYS[spinFormat.selectedItemPosition],
            width = size[0],
            height = size[1],
            fps = resources.getStringArray(R.array.fps_values)[spinFps.selectedItemPosition].toInt(),
            bars = resources.getStringArray(R.array.bars_values)[spinBars.selectedItemPosition].toInt(),
            glow = resources.getStringArray(R.array.glow_values)[spinGlow.selectedItemPosition].toFloat(),
            embedAudio = checkAudio.isChecked,
        )
    }

    private fun outputDir(): File {
        val base = getExternalFilesDir(Environment.DIRECTORY_MOVIES) ?: filesDir
        val dir = File(base, "频谱视频输出")
        if (!dir.exists()) dir.mkdirs()
        return dir
    }

    // ---------------- 预览 ----------------

    private fun schedulePreview() {
        previewJob?.cancel()
        previewJob = lifecycleScope.launch {
            delay(180) // 防抖
            previewLoading.visibility = View.VISIBLE
            val cfg = currentConfig()
            val bmp = withContext(Dispatchers.Default) {
                try {
                    Demo.renderPreview(cfg.mode, cfg.theme, cfg.bars, cfg.glow, 480, 270)
                } catch (e: Throwable) {
                    null
                }
            }
            previewLoading.visibility = View.GONE
            if (bmp != null) previewImage.setImageBitmap(bmp)
        }
    }

    // ---------------- 生成 ----------------

    private fun startGenerate() {
        if (audioUri == null) {
            Toast.makeText(this, "请先选择音频文件", Toast.LENGTH_SHORT).show()
            return
        }
        if (generateJob?.isActive == true) {
            Toast.makeText(this, "正在生成中", Toast.LENGTH_SHORT).show()
            return
        }
        cancelFlag.set(false)
        btnGenerate.isEnabled = false
        btnCancel.isEnabled = true
        progressBar.progress = 0
        val cfg = currentConfig()

        generateJob = lifecycleScope.launch {
            val result = withContext(Dispatchers.Default) {
                try {
                    Generator.generate(this@MainActivity, cfg, cancelFlag) { done, total, stage ->
                        runOnUiThread {
                            statusText.text = "$stage  $done / $total"
                            progressBar.progress = if (total > 0) done * 100 / total else 0
                        }
                    }
                } catch (e: Throwable) {
                    withContext(Dispatchers.Main) {
                        Toast.makeText(this@MainActivity, "生成失败：${e.message}", Toast.LENGTH_LONG).show()
                    }
                    null
                }
            }
            withContext(Dispatchers.Main) {
                btnGenerate.isEnabled = true
                btnCancel.isEnabled = false
                if (result != null && result.outputs.isNotEmpty()) {
                    statusText.text = "完成：已生成 ${result.outputs.size} 个文件"
                    Toast.makeText(this@MainActivity, "生成完成！", Toast.LENGTH_SHORT).show()
                } else if (cancelFlag.get()) {
                    statusText.text = "已取消"
                }
            }
        }
    }

    private fun openOutputFolder() {
        val dir = outputDir()
        val intent = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.N) {
            Intent(Intent.ACTION_VIEW).apply {
                setDataAndType(androidx.core.content.FileProvider.getUriForFile(
                    this@MainActivity,
                    "${packageName}.fileprovider",
                    dir
                ), "resource/folder")
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
        } else {
            Intent(Intent.ACTION_VIEW).apply { setDataAndType(Uri.fromFile(dir), "resource/folder") }
        }
        try {
            startActivity(intent)
        } catch (e: Exception) {
            Toast.makeText(this, "请用文件管理器打开：${dir.absolutePath}", Toast.LENGTH_LONG).show()
        }
    }

    private fun queryName(uri: Uri): String? {
        contentResolver.query(uri, null, null, null, null)?.use { cursor ->
            val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (idx >= 0 && cursor.moveToFirst()) return cursor.getString(idx)
        }
        return uri.lastPathSegment
    }
}
