package dev.nanomuse.devicehost

import android.content.Context
import android.os.Build
import android.provider.CalendarContract
import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.format.DateTimeFormatter

/** Tracks whether the host app is foreground — Android 10's clipboard gate. */
object ForegroundTracker {
    @Volatile
    var inForeground: Boolean = false
}

/**
 * The device__* tool implementations. Every entry routes through
 * [DeviceAskActivity.gated] — the agent can invoke a tool but can never grant
 * the permission itself; the Android OS dialog is the final authority.
 */
object DeviceTools {

    suspend fun execute(context: Context, name: String, args: JSONObject): JSONObject = when (name) {
        "device__clipboard_read" ->
            DeviceAskActivity.gated(context, args, permissions = emptyArray()) { ctx, _ ->
                readClipboard(ctx)
            }
        "device__calendar_list" ->
            DeviceAskActivity.gated(
                context, args,
                permissions = arrayOf(android.Manifest.permission.READ_CALENDAR)
            ) { ctx, a -> listCalendarEvents(ctx, a.optString("from")) }
        else -> throw IllegalArgumentException("unknown tool: $name")
    }

    fun readClipboard(context: Context): JSONObject {
        // Android 10+ restriction: ClipboardManager only returns data while the app
        // is in the foreground. DeviceAskActivity just put us there; no runtime
        // permission exists for the clipboard, so the foreground check IS the
        // OS-level authorization for this tool.
        if (Build.VERSION.SDK_INT >= 29 && !ForegroundTracker.inForeground) {
            throw SecurityException("clipboard requires host app in foreground (Android 10+)")
        }
        val cm = context.getSystemService(Context.CLIPBOARD_SERVICE)
            as android.content.ClipboardManager
        val clip = cm.primaryClip
        val text = if (clip != null && clip.itemCount > 0)
            clip.getItemAt(0).coerceToText(context)?.toString() else null
        return JSONObject().put("text", text ?: JSONObject.NULL)
    }

    fun listCalendarEvents(context: Context, from: String): JSONObject {
        if (context.checkSelfPermission(android.Manifest.permission.READ_CALENDAR)
            != android.content.pm.PackageManager.PERMISSION_GRANTED
        ) {
            throw SecurityException("READ_CALENDAR not granted")
        }
        val zone = ZoneId.systemDefault()
        val fromDate = try {
            LocalDate.parse(from)
        } catch (e: Exception) {
            throw IllegalArgumentException("'from' must be yyyy-MM-dd, got '$from'")
        }
        val begin = fromDate.atStartOfDay(zone).toInstant().toEpochMilli()
        val end = fromDate.plusDays(7).atStartOfDay(zone).toInstant().toEpochMilli()

        val projection = arrayOf(
            CalendarContract.Instances.EVENT_ID,
            CalendarContract.Instances.TITLE,
            CalendarContract.Instances.BEGIN,
            CalendarContract.Instances.END,
            CalendarContract.Instances.EVENT_LOCATION,
            CalendarContract.Instances.ALL_DAY
        )
        val events = JSONArray()
        CalendarContract.Instances.query(context.contentResolver, projection, begin, end).use { c ->
            while (c.moveToNext()) {
                events.put(JSONObject()
                    .put("event_id", c.getLong(0))
                    .put("title", c.getString(1) ?: JSONObject.NULL)
                    .put("start", iso(c.getLong(2), zone))
                    .put("end", iso(c.getLong(3), zone))
                    .put("location", c.getString(4) ?: JSONObject.NULL)
                    .put("all_day", c.getInt(5) == 1))
            }
        }
        return JSONObject()
            .put("from", from)
            .put("to", fromDate.plusDays(7).toString())
            .put("timezone", zone.id)
            .put("events", events)
    }

    private fun iso(epochMillis: Long, zone: ZoneId): String =
        DateTimeFormatter.ISO_LOCAL_DATE_TIME.format(Instant.ofEpochMilli(epochMillis).atZone(zone))
}
