package dev.nanomuse.devicehost

import android.content.Context
import fi.iki.elonen.NanoHTTPD
import kotlinx.coroutines.runBlocking
import org.json.JSONArray
import org.json.JSONObject
import java.io.OutputStream

/**
 * JSON-RPC 2.0 MCP endpoint ("streamable HTTP" style) on NanoHTTPD.
 *
 * - POST /mcp with `Authorization: Bearer <token>`.
 * - Non-blocking methods (initialize, ping, tools/list) answer as plain JSON.
 * - tools/call answers as an SSE stream that stays open until the tool
 *   finishes — necessary because [DeviceAskActivity] blocks the call until the
 *   user taps Allow/Deny on the real Android permission dialog.
 */
class McpHttpServer(
    private val appContext: Context,
    private val bearer: String
) : NanoHTTPD("127.0.0.1", 0) {

    override fun serve(session: IHTTPSession): Response {
        if (session.uri.trim('/') != "mcp")
            return json(Response.Status.NOT_FOUND, rpcError(null, -32004, "not found"))
        if (session.headers["authorization"] != "Bearer $bearer")
            return json(Response.Status.UNAUTHORIZED, rpcError(null, -32001, "unauthorized"))
        if (session.method != Method.POST)
            return json(Response.Status.METHOD_NOT_ALLOWED, rpcError(null, -32600, "POST only"))

        val files = HashMap<String, String>()
        return try {
            session.parseBody(files)
            dispatch(JSONObject(files["postData"] ?: throw IllegalArgumentException("empty body")))
        } catch (t: Throwable) {
            json(Response.Status.BAD_REQUEST, rpcError(null, -32700, "parse error: ${'$'}{t.message}"))
        }
    }

    private fun dispatch(body: JSONObject): Response {
        val id = if (body.has("id")) body.opt("id") else null
        return when (body.optString("method")) {
            "initialize" -> json(Response.Status.OK, rpcResult(id, JSONObject()
                .put("protocolVersion",
                    body.optJSONObject("params")?.optString("protocolVersion") ?: "2024-11-05")
                .put("capabilities", JSONObject().put("tools", JSONObject()))
                .put("serverInfo", JSONObject()
                    .put("name", "nanomuse-device-host")
                    .put("version", "0.1.0"))))

            "ping" -> json(Response.Status.OK, rpcResult(id, JSONObject()))

            "tools/list" -> json(Response.Status.OK, rpcResult(id,
                JSONObject().put("tools", toolsList())))

            // The ONLY long-running method: it blocks on the OS permission dialog.
            "tools/call" -> SseResponse { runBlocking { handleToolCall(body) } }

            "notifications/initialized", "notifications/cancelled" ->
                json(Response.Status.ACCEPTED, JSONObject()) // JSON-RPC notification: no response body

            else -> json(Response.Status.OK, rpcError(id, -32601,
                "method not found: ${'$'}{body.optString("method")}"))
        }
    }

    private fun toolsList(): JSONArray {
        val clipboard = JSONObject()
            .put("name", "device__clipboard_read")
            .put("description", "Read the system clipboard as text. Android 10+ only exposes the " +
                "clipboard while the host app is foreground; the host briefly surfaces itself to " +
                "satisfy that. No runtime permission exists for clipboard.")
            .put("inputSchema", JSONObject()
                .put("type", "object")
                .put("properties", JSONObject())
                .put("additionalProperties", false))

        val calendar = JSONObject()
            .put("name", "device__calendar_list")
            .put("description", "List calendar events for the 7 days starting at `from` " +
                "(yyyy-MM-dd) via CalendarContract.Instances. Requires the real Android " +
                "READ_CALENDAR system dialog; the call blocks (over SSE) until the user taps " +
                "Allow or Deny. Deny propagates as a tool error.")
            .put("inputSchema", JSONObject()
                .put("type", "object")
                .put("properties", JSONObject().put("from", JSONObject()
                    .put("type", "string")
                    .put("format", "date")
                    .put("description", "Start date, yyyy-MM-dd")))
                .put("required", JSONArray().put("from"))
                .put("additionalProperties", false))

        return JSONArray().put(clipboard).put(calendar)
    }

    private fun handleToolCall(body: JSONObject): JSONObject {
        val id = if (body.has("id")) body.opt("id") else null
        val params = body.optJSONObject("params")
            ?: return rpcError(id, -32602, "missing params")
        val name = params.optString("name")
        val args = params.optJSONObject("arguments") ?: JSONObject()
        return try {
            val payload = DeviceTools.execute(appContext, name, args)
            rpcResult(id, JSONObject().put("content", JSONArray().put(JSONObject()
                .put("type", "text")
                .put("text", payload.toString()))))
        } catch (t: Throwable) {
            // Denied, timed out, or rejected — the agent sees a failed tool call.
            rpcResult(id, JSONObject()
                .put("isError", true)
                .put("content", JSONArray().put(JSONObject()
                    .put("type", "text")
                    .put("text", t.message ?: t.toString()))))
        }
    }

    /** Holds the HTTP connection open, then streams the single MCP response frame. */
    private class SseResponse(private val produce: () -> JSONObject) :
        Response(Status.OK, "text/event-stream", null) {

        override fun send(outputStream: OutputStream) {
            val head = ("HTTP/1.1 " + Status.OK.description + "\r\n" +
                    "Content-Type: text/event-stream\r\n" +
                    "Cache-Control: no-cache\r\n" +
                    "Connection: close\r\n\r\n").toByteArray()
            outputStream.write(head)
            val frameJson = try {
                produce()
            } catch (t: Throwable) {
                rpcError(null, -32603, t.message ?: "internal error")
            }
            val frame = "event: message\ndata: " +
                frameJson.toString().replace("\r", "").replace("\n", "") + "\n\n"
            outputStream.write(frame.toByteArray())
            outputStream.flush()
        }
    }

    private fun json(status: Response.IStatus, body: JSONObject): Response =
        Response.newFixedLengthResponse(status, "application/json; charset=utf-8", body.toString())

    companion object {
        fun rpcResult(id: Any?, result: JSONObject): JSONObject =
            JSONObject().put("jsonrpc", "2.0").put("result", result)
                .apply { if (id != null) put("id", id) }

        fun rpcError(id: Any?, code: Int, message: String): JSONObject =
            JSONObject().put("jsonrpc", "2.0")
                .put("error", JSONObject().put("code", code).put("message", message))
                .apply { if (id != null) put("id", id) }
    }
}
