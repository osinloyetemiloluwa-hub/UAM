package dev.nanomuse.devicehost

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.Build
import android.os.IBinder
import java.security.SecureRandom

/**
 * Foreground service that hosts the local MCP server on 127.0.0.1 with an
 * ephemeral port and a random Bearer token. The token/port pair is the whole
 * auth surface: whoever holds it can *request* a tool call, but never grant
 * themselves permission — that stays with the OS dialog in [DeviceAskActivity].
 */
class McpServerService : Service() {

    data class State(val url: String, val token: String)

    companion object {
        const val CHANNEL_ID = "nanomuse_host"
        const val NOTIFICATION_ID = 1

        @Volatile
        var state: State? = null
            private set

        val isRunning: Boolean get() = state != null
    }

    private var server: McpHttpServer? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        startHost()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (state == null) startHost()
        return START_STICKY
    }

    private fun startHost() {
        createChannel()

        val token = ByteArray(32).also { SecureRandom().nextBytes(it) }
            .joinToString("") { b -> "%02x".format(b) }

        val srv = McpHttpServer(applicationContext, token)
        srv.start()
        val url = "http://127.0.0.1:${'$'}{srv.listeningPort}/mcp"
        state = State(url, token)
        server = srv

        val pi = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        )
        val notification = Notification.Builder(this, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("NanoMuse device host")
            .setContentText("MCP on $url — open app to copy env")
            .setContentIntent(pi)
            .setOngoing(true)
            .build()
        startForeground(NOTIFICATION_ID, notification)
    }

    private fun createChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            getSystemService(NotificationManager::class.java).createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Device host", NotificationManager.IMPORTANCE_LOW)
            )
        }
    }

    override fun onDestroy() {
        server?.stop()
        server = null
        state = null
        super.onDestroy()
    }
}
