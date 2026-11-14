package dev.nanomuse.devicehost

import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast

/** Minimal operator console: start/stop the host and copy the env pair for Termux/PRoot. */
class MainActivity : Activity() {

    private lateinit var status: TextView
    private val ui = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val pad = (16 * resources.displayMetrics.density).toInt()
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad, pad, pad)
        }
        status = TextView(this)
        val start = Button(this).apply { text = "Start device host" }
        val stop = Button(this).apply { text = "Stop host" }
        val copy = Button(this).apply { text = "Copy NANOMUSE_HOST_URL / TOKEN to clipboard" }

        start.setOnClickListener {
            if (Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1)
            }
            startForegroundService(Intent(this, McpServerService::class.java))
            ui.postDelayed({ refresh() }, 800)
        }
        stop.setOnClickListener {
            stopService(Intent(this, McpServerService::class.java))
            refresh()
        }
        copy.setOnClickListener {
            val s = McpServerService.state ?: return@setOnClickListener
            (getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager)
                .setPrimaryClip(ClipData.newPlainText("nanomuse-env",
                    "export NANOMUSE_HOST_URL=\"${'$'}{s.url}\"\n" +
                    "export NANOMUSE_HOST_TOKEN=\"${'$'}{s.token}\""))
            Toast.makeText(this, "env copied — paste it into Termux/PRoot", Toast.LENGTH_LONG).show()
        }

        root.addView(status)
        root.addView(start)
        root.addView(stop)
        root.addView(copy)
        setContentView(root)
        refresh()
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    private fun refresh() {
        val s = McpServerService.state
        status.text = if (s == null)
            "Host stopped. Start it, then copy the env into Termux/PRoot."
        else
            "Host running:\nNANOMUSE_HOST_URL=${'$'}{s.url}\n" +
            "NANOMUSE_HOST_TOKEN=${'$'}{s.token.take(12)}… (${'$'}{s.token.length} hex chars)"
    }
}
