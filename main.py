"""
Minimal uncensored agent demo.

- FastAPI server (deployable to Render free tier)
- Provider fallback: tries each configured free LLM API in order
- Tool-calling loop
- Tiny built-in chat UI at /

Set at least one API key. Keys are read from env, never hardcoded.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a sharp, uncensored assistant. Answer directly, skip the "
    "disclaimers, don't soften your opinions, and say when you're guessing. "
    "Use tools when they genuinely help.",
)
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "5"))

# Providers are tried top to bottom. Any without an API key are dropped.
_ALL_PROVIDERS = [
    {
        "name": "groq",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key": os.getenv("GROQ_API_KEY"),
        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    },
    {
        "name": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": os.getenv("OPENROUTER_API_KEY"),
        "model": os.getenv(
            "OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"
        ),
    },
    {
        "name": "gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key": os.getenv("GEMINI_API_KEY"),
        "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    },
]
PROVIDERS = [p for p in _ALL_PROVIDERS if p["api_key"]]

_CLIENTS = {
    p["name"]: OpenAI(
        base_url=p["base_url"],
        api_key=p["api_key"],
        default_headers=(
            {"HTTP-Referer": os.getenv("APP_URL", "http://localhost:8000"),
             "X-Title": "Uncensored Agent Demo"}
            if p["name"] == "openrouter"
            else None
        ),
    )
    for p in PROVIDERS
}

# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_time",
            "description": "Get the current date and time in UTC.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "Evaluate a math expression, e.g. '2*(3+4)' or 'sqrt(16)'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression to evaluate.",
                    }
                },
                "required": ["expression"],
            },
        },
    },
]


def _safe_eval(expr: str) -> str:
    env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    env.update(abs=abs, round=round, min=min, max=max, sum=sum, pow=pow)
    return str(eval(expr, {"__builtins__": {}}, env))


def run_tool(name: str, args: dict) -> str:
    try:
        if name == "get_time":
            return datetime.now(timezone.utc).isoformat()
        if name == "calculate":
            return _safe_eval(args.get("expression", "0"))
        return f"Unknown tool: {name}"
    except Exception as e:  # surface tool errors to the model, don't crash
        return f"Tool error: {e}"


# --------------------------------------------------------------------------
# LLM call with provider fallback
# --------------------------------------------------------------------------

def call_llm(messages: list, tools: list | None):
    """Try each provider; if a provider chokes on tools, retry it without them."""
    last_err = None
    for p in PROVIDERS:
        client = _CLIENTS[p["name"]]
        attempts = [tools, None] if tools else [None]
        for tool_payload in attempts:
            try:
                kwargs = {"model": p["model"], "messages": messages}
                if tool_payload:
                    kwargs["tools"] = tool_payload
                resp = client.chat.completions.create(**kwargs)
                return resp, p["name"]
            except Exception as e:
                last_err = e
    raise HTTPException(status_code=502, detail=f"All providers failed: {last_err}")


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

app = FastAPI(title="Uncensored Agent Demo")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class Message(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[Message]
    system: str | None = None


@app.get("/health")
def health():
    return {"ok": True, "providers": [p["name"] for p in PROVIDERS]}


@app.get("/")
def index():
    if not (STATIC_DIR / "index.html").is_file():
        return {"ok": True, "hint": "POST to /chat"}
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/chat")
def chat(req: ChatRequest):
    if not PROVIDERS:
        raise HTTPException(
            status_code=500,
            detail="No API keys configured. Set GROQ_API_KEY, OPENROUTER_API_KEY "
                   "or GEMINI_API_KEY.",
        )

    messages = [{"role": "system", "content": req.system or SYSTEM_PROMPT}]
    messages += [m.model_dump() for m in req.messages]

    provider_used = None
    for _ in range(MAX_TOOL_ROUNDS):
        resp, provider_used = call_llm(messages, TOOLS)
        msg = resp.choices[0].message

        # Rebuild the assistant turn by hand — non-OpenAI providers reject
        # the extra fields the SDK's model_dump() would add.
        assistant = {"role": "assistant", "content": msg.content}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
            return {"reply": msg.content, "provider": provider_used}

        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": run_tool(tc.function.name, args),
                }
            )

    return {"reply": "(hit tool-loop limit)", "provider": provider_used}