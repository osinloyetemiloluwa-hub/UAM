# NanoMuse Device Host

Native Android host that exposes real phone capabilities to a Python agent
running inside PRoot/Termux on the same device, over MCP on 127.0.0.1.
This replaces the `static/mobile.html` simulation in the UAM project — delete
`static/mobile.html` and any references to it in `main.py`/templates; the
Android app below is now the device surface.

## Architecture

- **Kotlin host** (`android/`): foreground service (`McpServerService`) runs a
  NanoHTTPD 2.3.1 JSON-RPC/MCP endpoint on `127.0.0.1` with an **ephemeral
  port** (`NanoHTTPD("127.0.0.1", 0)`) and a **random 256-bit Bearer token**
  (`SecureRandom`). Bearer auth on every `/mcp` request. Tools are exposed as
  `device__*`. The only runtime permission declared is `READ_CALENDAR`.
- **Permission authority**: there is **no custom permission UI anywhere**.
  `DeviceAskActivity` is a fully transparent activity; tools with a runtime
  permission call `requestPermissions()` there, so the user interacts only
  with the real Android system dialog. `device__clipboard_read` has no
  runtime permission — Android 10+ gates the clipboard on the app being
  foreground, and surfacing this activity *is* that OS-level gate.
- **Blocking calls over SSE**: `tools/call` responds with
  `Content-Type: text/event-stream` and holds the connection until the dialog
  resolves (up to a 5-minute gate timeout), then streams one MCP frame.
- **Deny propagates**: Deny/dismissal/timeout completes the pending gate
  exceptionally and comes back to the agent as a tool call with
  `isError: true`; the CLI exits 1. **The agent can never grant itself
  permissions — the OS dialog is the final authority.**
- **Python client** (`python/`): MCP SDK `streamablehttp_client` reading
  `NANOMUSE_HOST_URL` / `NANOMUSE_HOST_TOKEN` from the environment.

## Build & run

1. `cd android && ./gradlew assembleDebug` (or open in Android Studio), install
   the APK, open "NanoMuse Device Host", tap **Start device host**.
2. Tap **Copy env** and paste the two `export` lines into Termux/PRoot
   (loopback is shared, so `127.0.0.1` works from inside PRoot).
3. In Termux/PRoot:
   ```bash
   cd python && pip install .
   nanomuse-device tools
   nanomuse-device clipboard read
   nanomuse-device calendar list --from 2026-11-11
   ```

## Files

- `McpServerService.kt` — foreground service, random port + token, notification.
- `McpEndpoint.kt` — NanoHTTPD JSON-RPC 2.0 endpoint, Bearer auth, SSE for `tools/call`, `device__*` tool schemas.
- `DeviceAskActivity.kt` — transparent OS-permission gate; blocks the MCP call until Allow/Deny.
- `DeviceTools.kt` — `device__clipboard_read` (foreground-gated) and `device__calendar_list` (CalendarContract.Instances, next 7 days).
- `MainActivity.kt` — operator console (start/stop, copy env).
- `python/device_client.py` — MCP client + `nanomuse-device` CLI.

## Caveats

- **Background activity launches**: starting `DeviceAskActivity` from the
  foreground service works on Android 10–13. On Android 14+ some OEM builds
  enforce background-activity-launch (BAL) restrictions; the start is wrapped
  in a try/catch that turns the block into a clear tool error telling the user
  to open the host app and retry. Keep the host app open (or in a split screen
  with Termux) if your build is strict.
- If `READ_CALENDAR` was already granted, the system returns the result
  immediately without re-showing the dialog — that is standard OS behavior;
  the agent still never self-grants.
