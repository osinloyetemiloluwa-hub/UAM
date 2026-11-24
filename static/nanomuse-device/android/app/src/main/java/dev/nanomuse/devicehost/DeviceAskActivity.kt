package dev.nanomuse.devicehost

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.withTimeout
import org.json.JSONObject
import java.security.SecureRandom
import java.util.concurrent.ConcurrentHashMap

/**
 * Transparent permission gate. There is NO custom permission UI in this app:
 *
 * - Tools with a runtime permission (device__calendar_list → READ_CALENDAR)
 *   call [requestPermissions] here, so the user sees only the real Android
 *   system dialog. The MCP call stays suspended until they tap Allow or Deny.
 * - Tools without a runtime permission (device__clipboard_read) use this
 *   activity purely to bring the host to the foreground, which is the
 *   Android 10+ OS-level gate for that capability.
 *
 * Deny, dismissal, or timeout completes the pending gate exceptionally, and
 * [McpHttpServer.handleToolCall] propagates that as a tool error to the agent.
 */
class DeviceAskActivity : Activity() {

    private class Gate(
        val args: JSONObject,
        val permissions: Array<String>,
        val deferred: CompletableDeferred<JSONObject>,
        val block: (Context, JSONObject) -> JSONObject
    )

    companion object {
        private const val EXTRA_GATE_ID = "dev.nanomuse.devicehost.GATE_ID"
        private const val REQ_PERMISSION = 1001
        private const val GATE_TIMEOUT_MS = 5 * 60_000L // user has 5 min to tap Allow/Deny

        private val gates = ConcurrentHashMap<String, Gate>()
        private val random = SecureRandom()

        /**
         * Launch the gate and block until the OS dialog (or foreground gate)
         * resolves. Never grants anything itself.
         */
        suspend fun gated(
            context: Context,
            args: JSONObject,
            permissions: Array<String>,
            block: (Context, JSONObject) -> JSONObject
        ): JSONObject {
            val id = random.nextLong().toString(16) + Integer.toHexString(random.nextInt())
            val deferred = CompletableDeferred<JSONObject>()
            gates[id] = Gate(args, permissions, deferred, block)

            val intent = Intent(context, DeviceAskActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                .putExtra(EXTRA_GATE_ID, id)
            try {
                context.startActivity(intent)
            } catch (t: Throwable) {
                gates.remove(id)
                throw IllegalStateException(
                    "could not surface the Android permission dialog: ${'$'}{t.message}. " +
                    "Open the NanoMuse host app and retry.", t)
            }

            return try {
                withTimeout(GATE_TIMEOUT_MS) { deferred.await() }
            } catch (e: TimeoutCancellationException) {
                gates.remove(id)
                throw IllegalStateException(
                    "user did not respond to the Android permission dialog within " +
                    "${'$'}{GATE_TIMEOUT_MS / 1000}s")
            }
        }
    }

    private var gateId: String? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        ForegroundTracker.inForeground = true
        gateId = intent.getStringExtra(EXTRA_GATE_ID)
        val gate = gates[gateId] ?: run { finish(); return }

        if (gate.permissions.isEmpty()) {
            // No runtime permission exists for this tool; foreground-ness was the gate.
            completeGranted(gate)
        } else {
            // The ONLY UI the user ever sees from this activity is the system dialog.
            requestPermissions(gate.permissions, REQ_PERMISSION)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        val gate = gates[gateId] ?: return finish()
        if (requestCode == REQ_PERMISSION &&
            grantResults.isNotEmpty() &&
            grantResults.all { it == PackageManager.PERMISSION_GRANTED }
        ) {
            completeGranted(gate)
        } else {
            gates.remove(gateId)
            gate.deferred.completeExceptionally(SecurityException(
                "permission denied by user (${'$'}{permissions.joinToString()})"))
            finish()
        }
    }

    private fun completeGranted(gate: Gate) {
        gates.remove(gateId)
        try {
            // Runs while this activity is still foreground — required for clipboard.
            gate.deferred.complete(gate.block(this, gate.args))
        } catch (t: Throwable) {
            gate.deferred.completeExceptionally(t)
        }
        finish()
    }

    override fun onDestroy() {
        ForegroundTracker.inForeground = false
        val id = gateId
        if (id != null) {
            gates.remove(id)?.deferred?.completeExceptionally(
                IllegalStateException("permission prompt dismissed without a result"))
        }
        super.onDestroy()
    }
}
