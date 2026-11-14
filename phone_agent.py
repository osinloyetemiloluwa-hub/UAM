"""nanoMuse "Hands" for UAM: lets the chat agent operate the simulated phone (MobileGym).

The phone page opens a WebSocket to /ws (the protocol the nanoMuse app module already speaks),
announces itself as a device, and answers three requests: `screen`, `act`, `task`.
POST /phone/task starts a goal-driven loop: look at the screen, ask a vision model for ONE
action, do it on the phone, repeat. The loop lives on the server, so it keeps going if the
chat page is backgrounded while the phone shows another app; the page re-joins by call_id.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import BaseModel

TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
MAX_STEPS = 14
MAX_SECONDS = 170
LONG_POLL = 25
STOP_MARK = "nanomuse:stop"
ALLOWED = {"tap", "double_tap", "long_press", "type", "swipe", "enter", "back", "home",
           "recents", "open_app", "wait"}
KEYS = {"action", "x", "y", "x2", "y2", "label", "direction", "distance", "text", "clear",
        "submit", "app", "seconds"}

SYSTEM = """You operate a simulated Android phone for the user. Every turn you get the current screen (a picture and a list of elements with their centre coordinates) and must reply with ONE JSON object, nothing else:

{"thought": "<short reason>", "action": "<one of below>", ...fields}

Actions:
- {"action":"tap","x":N,"y":N,"label":"<what you tap>"}      use an element's centre from the list
- {"action":"type","text":"...","x":N,"y":N,"submit":false}  taps the field at x,y first, then types
- {"action":"swipe","direction":"up|down|left|right"}        up = scroll down the page
- {"action":"open_app","app":"<app name>"}
- {"action":"back"} {"action":"home"} {"action":"enter"} {"action":"wait","seconds":2}
- {"action":"ask","question":"..."}    STOP and ask the user (see rules)
- {"action":"done","summary":"<what you did and what you found, plain words>"}

Rules:
- Coordinates are in the screenshot's pixel space. Prefer element centres from the list.
- One action per turn. Look at the result before the next one.
- Before anything that cannot be undone (paying, ordering, booking, sending, deleting, posting) do NOT do it: reply with "ask" describing exactly what you are about to do. The user will confirm in chat and you will be called again.
- Never invent data. If something is not on screen, say so in "done".
- Password and code fields are the user's to fill in; the phone will hand them over.
- Finish with "done" as soon as the goal is met or clearly impossible."""


class Device:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.pending: dict[str, asyncio.Future] = {}
        self.info: dict = {}
        self.busy = False

    async def call(self, op: str, params: dict | None = None, timeout: float = 45) -> dict:
        rid = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        try:
            await self.ws.send_json({"kind": "device_request", "id": rid, "op": op, "params": params or {}})
            msg = await asyncio.wait_for(fut, timeout)
        finally:
            self.pending.pop(rid, None)
        if not msg.get("ok"):
            raise DeviceError(str(msg.get("error") or "the phone refused"))
        return msg.get("result") or {}


class DeviceError(Exception):
    pass


class Task:
    def __init__(self, call_id: str, token: str, goal: str):
        self.call_id, self.token, self.goal = call_id, token, goal
        self.status = "running"          # running | done | ask | failed | stopped
        self.summary = ""
        self.steps: list[str] = []
        self.created = time.time()
        self.finished = asyncio.Event()

    def public(self) -> dict:
        return {"status": self.status, "summary": self.summary, "steps": self.steps[-8:]}


DEVICES: dict[str, Device] = {}
TASKS: dict[str, Task] = {}


class TaskReq(BaseModel):
    token: str
    call_id: str
    goal: str
    memory: list[str] = []
    skills: list[str] = []
    profile: str = "balanced"


# ---------------------------------------------------------------- model step

def _nodes_text(nodes: list[dict]) -> str:
    out = []
    for n in (nodes or [])[:80]:
        label = n.get("text") or n.get("desc") or n.get("hint") or n.get("res") or n.get("class", "")
        flags = [k for k in ("clickable", "editable", "scrollable", "checked", "disabled", "password") if n.get(k)]
        out.append(f'- "{str(label)[:60]}" at ({n.get("cx")},{n.get("cy")})' + (f" [{', '.join(flags)}]" if flags else ""))
    return "\n".join(out) or "(no readable elements)"


def _json_from(text: str) -> dict | None:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        d = json.loads(text[a:b + 1])
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _ask_model(deps: dict, profile: str, messages: list) -> str:
    errs = []
    order = deps["profiles"].get(profile) or deps["profiles"]["balanced"]
    if profile in ("photo", "video"):
        order = deps["profiles"]["balanced"]
    for name in order:
        p = deps["provider_by_name"].get(name)
        if not p:
            continue
        for model in deps["candidate_models"](p, True):
            try:
                r = deps["clients"][name].chat.completions.create(
                    model=model, messages=messages, temperature=0, max_tokens=500)
                return r.choices[0].message.content or ""
            except Exception as e:  # try the next model/provider
                errs.append(f"{name}/{model}: {str(e)[:120]}")
    raise RuntimeError("no vision model answered (" + "; ".join(errs[-3:]) + ")")


def _system(ctx_memory: list[str], skills: list[str]) -> str:
    s = SYSTEM
    if ctx_memory:
        s += "\n\nWhat you know about the user:\n" + "\n".join("- " + m[:300] for m in ctx_memory[-30:])
    if skills:
        s += "\n\nSkills the user added (follow them when relevant):\n" + "\n".join("- " + k[:600] for k in skills[-20:])
    return s


async def _decide(deps, req: TaskReq, screen: dict, history: list[str]) -> dict:
    text = (f"GOAL: {req.goal}\n\nCURRENT APP: {screen.get('app_name') or screen.get('app')}  "
            f"(screen {screen.get('width')}x{screen.get('height')}, keyboard {'open' if screen.get('keyboard') else 'closed'})\n"
            f"ELEMENTS:\n{_nodes_text(screen.get('nodes') or [])}\n\n"
            f"WHAT YOU DID SO FAR:\n" + ("\n".join(history[-6:]) or "(nothing yet)") +
            "\n\nReply with the next single JSON action.")
    content: list[dict] = [{"type": "text", "text": text}]
    if screen.get("screenshot"):
        content.append({"type": "image_url", "image_url": {"url": "data:image/png;base64," + screen["screenshot"]}})
    messages = [{"role": "system", "content": _system(req.memory, req.skills)},
                {"role": "user", "content": content}]
    raw = await asyncio.to_thread(_ask_model, deps, req.profile, messages)
    d = _json_from(raw)
    if d is None:  # one repair attempt
        messages += [{"role": "assistant", "content": raw[:500]},
                     {"role": "user", "content": "That was not valid JSON. Reply with ONE JSON object only."}]
        raw = await asyncio.to_thread(_ask_model, deps, req.profile, messages)
        d = _json_from(raw)
    if d is None:
        raise RuntimeError("the model did not return an action")
    return d


# ---------------------------------------------------------------- the loop

async def _run(deps, dev: Device, task: Task, req: TaskReq) -> None:
    started = time.time()
    last_sig, repeats = "", 0
    try:
        await dev.call("task", {"event": "begin", "text": req.goal[:120]})
        screen = await dev.call("screen")
        history: list[str] = []
        for step in range(MAX_STEPS):
            if time.time() - started > MAX_SECONDS:
                task.status, task.summary = "failed", "That took too long; stopped. Progress so far: " + "; ".join(history[-3:])
                return
            d = await _decide(deps, req, screen, history)
            action = str(d.get("action", "")).strip()
            thought = str(d.get("thought", ""))[:160]
            if action == "done":
                task.status, task.summary = "done", str(d.get("summary") or "Done.")[:1500]
                return
            if action == "ask":
                task.status, task.summary = "ask", str(d.get("question") or "Can I go ahead?")[:600]
                return
            if action not in ALLOWED:
                history.append(f"(invalid action {action!r})")
                continue
            params = {k: v for k, v in d.items() if k in KEYS}
            sig = json.dumps(params, sort_keys=True)
            repeats = repeats + 1 if sig == last_sig else 0
            last_sig = sig
            if repeats >= 2:
                task.status, task.summary = "failed", "I got stuck repeating the same action on " + str(screen.get("app_name") or "the phone") + "."
                return
            line = f"{action} {params.get('label') or params.get('app') or params.get('text') or params.get('direction') or ''}".strip()
            task.steps.append(line)
            history.append(f"{line} — {thought}")
            if action == "wait":
                await asyncio.sleep(min(5.0, float(params.get("seconds") or 2)))
                screen = await dev.call("screen")
                continue
            res = await dev.call("act", params)
            note = str(res.get("note") or "")
            if note and note != "ok":
                history[-1] += f" (phone: {note[:160]})"
            screen = res.get("screen") or await dev.call("screen")
        task.status, task.summary = "failed", "I ran out of steps. Progress so far: " + "; ".join(history[-3:])
    except DeviceError as e:
        if STOP_MARK in str(e):
            task.status, task.summary = "stopped", "The user stopped the task on the phone."
        else:
            task.status, task.summary = "failed", f"The phone said: {e}"
    except asyncio.TimeoutError:
        task.status, task.summary = "failed", "The phone stopped answering."
    except Exception as e:
        task.status, task.summary = "failed", f"Could not finish: {str(e)[:300]}"
    finally:
        dev.busy = False
        try:
            await dev.call("task", {"event": "end"}, timeout=10)
        except Exception:
            pass
        task.finished.set()


def _sweep() -> None:
    cut = time.time() - 900
    for k in [k for k, t in TASKS.items() if t.created < cut and t.finished.is_set()]:
        TASKS.pop(k, None)


# ---------------------------------------------------------------- routes

def register(app, *, profiles, provider_by_name, clients, candidate_models) -> None:
    deps = {"profiles": profiles, "provider_by_name": provider_by_name,
            "clients": clients, "candidate_models": candidate_models}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        try:
            first = await asyncio.wait_for(ws.receive_json(), 10)
            token = str(first.get("token", ""))
            if first.get("kind") != "auth" or not TOKEN_RE.match(token):
                await ws.close(4401)
                return
        except Exception:
            await ws.close(4401)
            return
        dev = Device(ws)
        DEVICES[token] = dev
        try:
            await ws.send_json({"kind": "hello", "state": {"phone": {"task": None}, "holds": [], "pending_approvals": []}})
            while True:
                msg = await ws.receive_json()
                kind = msg.get("kind")
                if kind == "device":
                    dev.info = msg
                elif kind == "device_result":
                    fut = dev.pending.get(msg.get("id"))
                    if fut and not fut.done():
                        fut.set_result(msg)
        except (WebSocketDisconnect, Exception):
            pass
        finally:
            if DEVICES.get(token) is dev:
                DEVICES.pop(token, None)
            for f in dev.pending.values():
                if not f.done():
                    f.cancel()

    @app.get("/phone/status")
    def phone_status(token: str = ""):
        dev = DEVICES.get(token)
        return {"connected": bool(dev and dev.info.get("gui")),
                "apps": [a.get("name") for a in (dev.info.get("apps") or [])] if dev else []}

    @app.post("/phone/task")
    async def phone_task(req: TaskReq):
        if not TOKEN_RE.match(req.token):
            return {"status": "failed", "summary": "Bad phone token.", "steps": []}
        _sweep()
        key = f"{req.token}:{req.call_id}"
        task = TASKS.get(key)
        if task is None:
            dev = DEVICES.get(req.token)
            if not dev or not dev.info.get("gui"):
                return {"status": "failed", "steps": [],
                        "summary": "The simulated phone is not open. Ask the user to open the phone (the /phone page) and try again."}
            if dev.busy:
                return {"status": "failed", "steps": [], "summary": "The phone is already busy with another task."}
            dev.busy = True
            task = Task(req.call_id, req.token, req.goal[:500])
            TASKS[key] = task
            req.goal = task.goal
            asyncio.create_task(_run(deps, dev, task, req))
        try:
            await asyncio.wait_for(task.finished.wait(), LONG_POLL)
        except asyncio.TimeoutError:
            pass
        return task.public()
