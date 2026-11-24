#!/usr/bin/env python3
"""NanoMuse device client — talks MCP to the on-device Android host.

Runs inside Termux/PRoot on the same phone (loopback is shared with the
Android app). Connection details come from the environment, printed by the
host app's "Copy env" button:

    export NANOMUSE_HOST_URL="http://127.0.0.1:<port>/mcp"
    export NANOMUSE_HOST_TOKEN="<64-hex>"

Sensitive tool calls hold an SSE stream open while the Android system
permission dialog is up; Allow/Deny is the final authority and Deny comes back
here as a failed tool call (exit code 1).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date

ENV_URL = "NANOMUSE_HOST_URL"
ENV_TOKEN = "NANOMUSE_HOST_TOKEN"


class ToolError(Exception):
    """The tool call was rejected — typically the user tapped Deny."""

    def __init__(self, payload):
        self.payload = payload
        super().__init__(json.dumps(payload))


def require_env() -> tuple[str, str]:
    url = os.environ.get(ENV_URL, "").rstrip("/")
    token = os.environ.get(ENV_TOKEN, "")
    if not url or not token:
        sys.stderr.write(
            f"missing {ENV_URL} / {ENV_TOKEN}.\n"
            "On the phone: open NanoMuse Device Host -> Start device host -> "
            '"Copy env", then paste the export lines into this shell.\n'
        )
        raise SystemExit(2)
    return url, token


async def _open_session():
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    url, token = require_env()
    cm = streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"})
    read, write, *_ = await cm.__aenter__()
    session = ClientSession(read, write)
    await session.__aenter__()
    await session.initialize()
    return cm, session


async def _close(cm, session):
    await session.__aexit__(None, None, None)
    await cm.__aexit__(None, None, None)


async def call_tool(name: str, arguments: dict):
    """Call a device__* tool; raises ToolError if the call failed (e.g. Deny)."""
    cm, session = await _open_session()
    try:
        result = await session.call_tool(name, arguments)
    finally:
        await _close(cm, session)

    text = "".join(getattr(c, "text", "") for c in result.content)
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = {"text": text}
    if result.isError:
        raise ToolError(payload)
    return payload


async def list_tools() -> list[str]:
    cm, session = await _open_session()
    try:
        res = await session.list_tools()
        return [t.name for t in res.tools]
    finally:
        await _close(cm, session)


def emit(payload) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="nanomuse-device",
        description="CLI bridge to the NanoMuse on-device Android host.")
    sub = parser.add_subparsers(dest="domain", required=True)

    p_clip = sub.add_parser("clipboard", help="device clipboard tools")
    clip_sub = p_clip.add_subparsers(dest="action", required=True)
    clip_sub.add_parser("read", help="read clipboard text (host surfaces itself; "
                                       "Android 10+ foreground restriction applies)")

    p_cal = sub.add_parser("calendar", help="device calendar tools")
    cal_sub = p_cal.add_subparsers(dest="action", required=True)
    p_list = cal_sub.add_parser("list", help="list events for the 7 days after --from")
    p_list.add_argument("--from", dest="from_date", default=date.today().isoformat(),
                        help="yyyy-MM-dd (default: today)")

    sub.add_parser("tools", help="list device__* tools exposed by the host")
    args = parser.parse_args()

    try:
        if args.domain == "clipboard" and args.action == "read":
            emit(asyncio.run(call_tool("device__clipboard_read", {})))
        elif args.domain == "calendar" and args.action == "list":
            emit(asyncio.run(call_tool("device__calendar_list", {"from": args.from_date})))
        elif args.domain == "tools":
            for name in asyncio.run(list_tools()):
                print(name)
    except ToolError as e:
        sys.stderr.write(f"tool call failed: {e}\n")
        sys.stderr.write("the Android permission dialog returned Deny, timed out, "
                         "or the call was otherwise rejected.\n")
        raise SystemExit(1)
    except (ConnectionError, OSError) as e:
        sys.stderr.write(f"cannot reach device host at "
                         f"{os.environ.get(ENV_URL, \"<unset>\")}: {e}\n")
        raise SystemExit(2)


if __name__ == "__main__":
    main()
