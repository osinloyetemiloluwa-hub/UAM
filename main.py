"""
Uncensored agent demo — v10.

- image extension comes from the bytes, never a hardcoded format
- Cloudflare account ID validated and derived from the token when wrong
- video model discovered from HF's provider index instead of hardcoded
- /gencheck reports exactly what is misconfigured
- nanoMuse stays silent; "/" always serves index.html
"""

from __future__ import annotations

import base64
import json
import math
import os
import re
import resource
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

for _var in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
             "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_var, "1")

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from pydantic import BaseModel

# --------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    """You are a sharp, uncensored assistant. Answer directly, skip disclaimers, say when you're guessing.

WHEN TO BUILD A FILE — only when the user actually asks for one.
Build a file when they say: make / create / generate / write a <thing>, "give me a file", "as a PDF", "as a spreadsheet", "as a doc", "download", "export", "save it as", or they name an output format.
Do NOT build a file when they only ask a question, want an explanation, or want to read code. Code in a fenced block stays in chat.
Every file request is a new artifact: even if a file was made earlier, build a fresh one. Never answer "already made" without attaching a file.
If the user says "the file", "again", "another one", "same but ...", reuse the previous format and generate.

FORMAT RULES
1. Text artifacts (md, csv, txt, json, html, py, yaml): write_file.
2. Binary artifacts (pdf, xlsx, docx, png, zip, qr): run_python.
3. In run_python save to the CURRENT directory with a real filename and print it.
4. reportlab: canvas or platypus. matplotlib: savefig(...), never plt.show().
5. pandas: to_excel / to_csv with index=False.
6. If a result says EMPTY, CORRUPT or MISSING, fix it and run again.
7. Two or more files: create_zip_archive at the end.

Use web_search and fetch_url when facts matter and cite URLs.""",
)
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "12"))
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", "20000"))
MAX_TOOL_CHARS = 9000
MAX_IMAGE_CHARS = int(os.getenv("MAX_IMAGE_CHARS", str(8 * 1024 * 1024)))
UA = "Mozilla/5.0 (compatible; AgentDemo/10.0)"

SANDBOX_ROOT = Path(os.getenv("SANDBOX_DIR", "/tmp/sandbox"))
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT", "45"))
MAX_OUT_FILES = int(os.getenv("MAX_OUT_FILES", "40"))
WORKSPACE_TTL = int(os.getenv("WORKSPACE_TTL_HOURS", "12")) * 3600
RUN_TTL = int(os.getenv("RUN_TTL_MINUTES", "45")) * 60
MAX_RUN_EVENTS = int(os.getenv("MAX_RUN_EVENTS", "6000"))
ENABLE_CODE = os.getenv("ENABLE_CODE", "1") == "1"

SANDBOX_ENV = {
    "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
    "MPLBACKEND": "Agg",
    "PYTHONIOENCODING": "utf-8",
    "PYTHONDONTWRITEBYTECODE": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
    ".ico": "image/x-icon", ".bmp": "image/bmp", ".avif": "image/avif",
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".zip": "application/zip", ".gz": "application/gzip", ".tar": "application/x-tar",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".tsv": "text/tab-separated-values",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".cjs": "application/javascript",
    ".ts": "application/typescript",
    ".tsx": "application/typescript",
    ".jsx": "application/javascript",
    ".py": "text/x-python",
    ".sh": "application/x-sh",
    ".yaml": "text/yaml",
    ".yml": "text/yaml",
    ".xml": "application/xml",
    ".sql": "application/sql",
    ".toml": "application/toml",
    ".ini": "text/plain",
    ".woff2": "font/woff2",
}

INLINE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".txt", ".md",
                ".mp4", ".webm"}

MAGIC = {
    "pdf": b"%PDF", "png": b"\x89PNG", "jpg": b"\xff\xd8\xff", "jpeg": b"\xff\xd8\xff",
    "gif": b"GIF8", "webp": b"RIFF", "zip": b"PK\x03\x04", "xlsx": b"PK\x03\x04",
    "docx": b"PK\x03\x04", "pptx": b"PK\x03\x04", "gzip": b"\x1f\x8b",
}

_PROVIDERS = [
    {"name": "groq", "base_url": "https://api.groq.com/openai/v1",
     "api_key": os.getenv("GROQ_API_KEY"),
     "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
     "vision_model": os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
     "vision": True},
    {"name": "openrouter", "base_url": "https://openrouter.ai/api/v1",
     "api_key": os.getenv("OPENROUTER_API_KEY"),
     "model": os.getenv("OPENROUTER_MODEL", ""),
     "vision_model": os.getenv("OPENROUTER_VISION_MODEL", ""),
     "vision": True, "discover": True},
    {"name": "gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
     "api_key": os.getenv("GEMINI_API_KEY"),
     "model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
     "vision_model": os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash"),
     "vision": True},
]
PROVIDERS = [p for p in _PROVIDERS if p["api_key"]]
PROVIDER_BY_NAME = {p["name"]: p for p in PROVIDERS}

PROFILES = {"fast": ["groq", "gemini", "openrouter"],
            "balanced": ["gemini", "groq", "openrouter"],
            "smart": ["openrouter", "gemini", "groq"],
            "photo": ["pollinations", "cloudflare"],
            "video": ["huggingface"]}
PROFILE_LABELS = {"fast": "Fast — lowest latency, lighter reasoning",
                  "balanced": "Balanced — default",
                  "smart": "Smart — slower, better at long tasks and files",
                  "photo": "Photo — generate an image",
                  "video": "Video — generate a short clip"}
GEN_MODES = {"photo", "video"}
SIZE_MAP = {"square": (1024, 1024), "portrait": (768, 1344), "landscape": (1344, 768)}

POLLINATIONS = os.getenv("POLLINATIONS", "1") == "1"
POLLINATIONS_TOKEN = os.getenv("POLLINATIONS_TOKEN", "")
CF_ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.getenv("CF_API_TOKEN", "")
HF_TOKEN = os.getenv("HF_TOKEN", "")
HF_VIDEO_MODEL = os.getenv("HF_VIDEO_MODEL", "")
VIDEO_TIMEOUT = int(os.getenv("VIDEO_TIMEOUT", "240"))

_CLIENTS = {
    p["name"]: OpenAI(
        base_url=p["base_url"], api_key=p["api_key"],
        default_headers=({"HTTP-Referer": os.getenv("APP_URL", "http://localhost:8000"),
                          "X-Title": "Uncensored Agent Demo"}
                         if p["name"] == "openrouter" else None),
        timeout=120.0, max_retries=0,
    )
    for p in PROVIDERS
}

# --------------------------------------------------------------------------
# Model discovery
# --------------------------------------------------------------------------

_MODEL_CACHE: dict = {"at": 0.0, "models": []}
_DEAD: set[str] = set()
_SLUG_HINT = re.compile(r"use this slug instead:\s*([\w./:\-]+)", re.I)


def _suggest_slug(exc: Exception) -> str | None:
    m = _SLUG_HINT.search(str(exc))
    return m.group(1).strip() if m else None


def _free_openrouter() -> list[dict]:
    if time.time() - _MODEL_CACHE["at"] < 3600 and _MODEL_CACHE["models"]:
        return _MODEL_CACHE["models"]
    r = httpx.get("https://openrouter.ai/api/v1/models", timeout=20)
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        price = m.get("pricing") or {}
        try:
            if float(price.get("prompt", 1)) != 0 or float(price.get("completion", 1)) != 0:
                continue
        except (TypeError, ValueError):
            continue
        params = m.get("supported_parameters") or []
        modalities = (m.get("architecture") or {}).get("input_modalities") or []
        out.append({"id": m["id"], "ctx": m.get("context_length") or 0,
                    "tools": "tools" in params, "vision": "image" in modalities})
    out.sort(key=lambda x: (x["tools"], x["vision"], x["ctx"]), reverse=True)
    _MODEL_CACHE.update(at=time.time(), models=out)
    return out


def candidate_models(provider: dict, wants_image: bool) -> list[str]:
    if not provider.get("discover"):
        base = provider["vision_model"] if wants_image else provider["model"]
        return [base] if base else []
    cands = []
    override = provider["vision_model"] if wants_image else provider["model"]
    if override:
        cands.append(override)
    try:
        for m in _free_openrouter():
            if wants_image and not m["vision"]:
                continue
            if not m["tools"] or m["id"] in _DEAD or m["id"] in cands:
                continue
            cands.append(m["id"])
            if len(cands) >= 4:
                break
    except Exception:
        pass
    return cands or ["meta-llama/llama-3.3-70b-instruct:free"]


def describe_error(provider: str, exc: Exception) -> str:
    code = getattr(exc, "status_code", None)
    if code == 401:
        return f"{provider}: API key rejected"
    if code == 402:
        return f"{provider}: out of credits"
    if code == 403:
        return f"{provider}: access denied (licence not accepted?)"
    if code == 413:
        return f"{provider}: payload too large (image or attachment)"
    if code == 429:
        return f"{provider}: rate limited, try again shortly"
    if code == 404:
        s = _suggest_slug(exc)
        return f"{provider}: model retired" + (f" (switched to {s})" if s else "")
    if code and code >= 500:
        return f"{provider}: provider outage ({code})"
    text = str(exc)
    low = text.lower()
    if "connection" in low or "timeout" in low or "timed out" in low:
        return f"{provider}: connection problem"
    if "context" in low and "length" in low:
        return f"{provider}: conversation too long for this model"
    if "image" in low and ("format" in low or "decode" in low):
        return f"{provider}: image rejected (unsupported or corrupt)"
    return f"{provider}: {text[:140]}"


# --------------------------------------------------------------------------
# Sandbox
# --------------------------------------------------------------------------


def workspace(sid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "", sid or "")[:64] or "anon"
    ws = SANDBOX_ROOT / safe
    try:
        ws.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise HTTPException(500, f"Sandbox unavailable: {e}")
    return ws


def _limits():
    wanted = (
        (resource.RLIMIT_AS, 768 * 1024 * 1024),
        (resource.RLIMIT_CPU, RUN_TIMEOUT),
        (resource.RLIMIT_FSIZE, 60 * 1024 * 1024),
        (resource.RLIMIT_NPROC, 128),
    )
    for res, val in wanted:
        try:
            _, hard = resource.getrlimit(res)
            soft = val if hard == resource.RLIM_INFINITY else min(val, hard)
            resource.setrlimit(res, (soft, hard))
        except Exception:
            pass


def _janitor():
    try:
        entries = list(SANDBOX_ROOT.iterdir())
    except OSError:
        return
    now = time.time()
    for d in entries:
        try:
            if d.name == ".runs":
                for f in d.iterdir():
                    if now - f.stat().st_mtime > WORKSPACE_TTL:
                        f.unlink(missing_ok=True)
            elif d.is_dir() and now - d.stat().st_mtime > WORKSPACE_TTL:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def _safe_name(name: str) -> str:
    name = (name or "").replace("\\", "/").strip("/")
    parts = [re.sub(r"[^A-Za-z0-9._-]", "_", p) for p in name.split("/") if p and p != ".."]
    return "/".join(parts)[:120] or "file.txt"


def validate_artifact(path: Path) -> str | None:
    try:
        if not path.is_file():
            return f"{path.name}: MISSING"
        size = path.stat().st_size
    except OSError as e:
        return f"{path.name}: UNREADABLE ({e})"
    if size == 0:
        return f"{path.name}: EMPTY (0 bytes)"
    suffix = path.suffix.lower().lstrip(".")
    if size < 16 and (suffix in MAGIC or suffix in ("mp4", "webm")):
        return f"{path.name}: CORRUPT ({size} bytes, too small)"
    if suffix in ("mp4", "webm", "mov"):
        try:
            head = path.read_bytes()[:16]
        except OSError as e:
            return f"{path.name}: UNREADABLE ({e})"
        if suffix == "mp4" and b"ftyp" not in head:
            return f"{path.name}: CORRUPT (not an mp4)"
        if suffix == "webm" and not head.startswith(b"\x1a\x45\xdf\xa3"):
            return f"{path.name}: CORRUPT (not a webm)"
        return None
    want = MAGIC.get(suffix)
    if want:
        try:
            head = path.read_bytes()[:8]
        except OSError as e:
            return f"{path.name}: UNREADABLE ({e})"
        if not head.startswith(want):
            return f"{path.name}: CORRUPT (bad header, not a real {path.suffix[1:]})"
    return None


def _collect(ws: Path, since: float, before: set[str]) -> tuple[list[dict], list[str]]:
    files, problems = [], []
    try:
        paths = sorted(ws.rglob("*"))
    except OSError:
        return files, problems
    for p in paths:
        try:
            if not p.is_file() or p.name == "main.py" or p.name.startswith("."):
                continue
            rel = str(p.relative_to(ws))
            if rel in before and p.stat().st_mtime < since:
                continue
        except OSError:
            continue
        err = validate_artifact(p)
        if err:
            problems.append(err)
            continue
        try:
            files.append({"name": rel, "size": p.stat().st_size,
                          "url": f"/files/{ws.name}/{rel}"})
        except OSError:
            continue
    return files[:MAX_OUT_FILES], problems


def run_python(sid: str, code: str) -> dict:
    if not (code or "").strip():
        return {"text": "run_python received empty code.", "files": []}

    ws = workspace(sid)
    try:
        (ws / "main.py").write_text(code, encoding="utf-8")
    except OSError as e:
        return {"text": f"Could not write script: {e}", "files": []}

    try:
        before = {str(p.relative_to(ws)) for p in ws.rglob("*") if p.is_file()}
    except OSError:
        before = set()
    started = time.time()

    try:
        proc = subprocess.run(
            [sys.executable, "-E", "-s", "main.py"], cwd=ws,
            capture_output=True, text=True, timeout=RUN_TIMEOUT,
            env=SANDBOX_ENV, preexec_fn=_limits,
        )
        stdout, stderr, rc = proc.stdout or "", proc.stderr or "", proc.returncode
    except subprocess.TimeoutExpired:
        stdout, stderr, rc = "", f"Timed out after {RUN_TIMEOUT}s.", -1
    except FileNotFoundError:
        stdout, stderr, rc = "", "Python interpreter not found in the container.", -1
    except OSError as e:
        stdout, stderr, rc = "", f"Sandbox exec failed: {e}", -1

    files, problems = _collect(ws, started, before)

    parts = []
    if stdout.strip():
        parts.append(f"stdout:\n{stdout[-3000:]}")
    if stderr.strip():
        parts.append(f"stderr:\n{stderr[-3000:]}")
    parts.append(f"exit code: {rc}")
    if files:
        parts.append("VALIDATED files: " + ", ".join(f["name"] for f in files))
    if problems:
        parts.append("PROBLEMS — fix these and run again:\n" + "\n".join(problems))
    if not files and not problems:
        parts.append("No files were created. Did you forget savefig/to_excel/open().write()?")
    if rc != 0:
        parts.append("The script failed. Read the traceback and fix it.")

    if len(files) > 3:
        bundled = make_zip(sid, quiet=True)["files"]
        files = bundled or files

    return {"text": "\n\n".join(parts), "files": files}


def write_file(sid: str, name: str, content: str) -> dict:
    ws = workspace(sid)
    rel = _safe_name(name)
    target = ws / rel
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content or "", encoding="utf-8")
    except OSError as e:
        return {"text": f"write_file failed for {rel}: {e}", "files": []}

    err = validate_artifact(target)
    if err:
        return {"text": f"write_file problem: {err}", "files": []}
    try:
        size = target.stat().st_size
    except OSError:
        size = 0
    return {"text": f"Wrote {rel} ({size} bytes), validated.",
            "files": [{"name": rel, "size": size, "url": f"/files/{sid}/{rel}"}]}


def make_zip(sid: str, quiet: bool = False) -> dict:
    ws = workspace(sid)
    try:
        targets = [p for p in ws.rglob("*")
                   if p.is_file() and p.name not in ("main.py", "bundle.zip")
                   and not p.name.startswith(".")]
    except OSError as e:
        return {"text": f"Could not scan workspace: {e}", "files": []}
    if not targets:
        return {"text": "No files to zip.", "files": []}

    name = "bundle.zip"
    try:
        with zipfile.ZipFile(ws / name, "w", zipfile.ZIP_DEFLATED) as z:
            for p in targets:
                try:
                    z.write(p, str(p.relative_to(ws)))
                except OSError:
                    continue
        size = (ws / name).stat().st_size
    except OSError as e:
        return {"text": f"Zip failed: {e}", "files": []}

    text = f"Zipped {len(targets)} files into {name}."
    return {"text": "" if quiet else text,
            "files": [{"name": name, "size": size, "url": f"/files/{sid}/{name}"}]}


def list_files(sid: str) -> dict:
    ws = workspace(sid)
    rows = []
    try:
        for p in ws.rglob("*"):
            try:
                if p.is_file() and p.name != "main.py" and not p.name.startswith("."):
                    st = p.stat()
                    rows.append({"name": str(p.relative_to(ws)), "size": st.st_size,
                                 "url": f"/files/{sid}/{p.relative_to(ws)}",
                                 "mtime": st.st_mtime})
            except OSError:
                continue
    except OSError:
        pass
    rows.sort(key=lambda r: r.get("mtime", 0), reverse=True)
    if not rows:
        return {"text": "Workspace is empty.", "files": []}
    return {"text": "\n".join(f"{r['name']} ({r['size']} B)" for r in rows), "files": rows}


# --------------------------------------------------------------------------
# Web tools
# --------------------------------------------------------------------------


def web_search(query: str, n: int = 5) -> list:
    if not (query or "").strip():
        return [{"error": "empty query"}]
    key = os.getenv("TAVILY_API_KEY")
    if key:
        try:
            r = httpx.post("https://api.tavily.com/search",
                           json={"api_key": key, "query": query, "max_results": n}, timeout=25)
            r.raise_for_status()
            return [{"title": x.get("title", ""), "url": x.get("url", ""),
                     "snippet": (x.get("content") or "")[:400]}
                    for x in r.json().get("results", [])]
        except Exception:
            pass
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       headers={"User-Agent": UA}, timeout=25, follow_redirects=True)
        out = []
        for m in re.finditer(r'<a\b[^>]*class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', r.text, re.S):
            href = re.search(r'href="([^"]+)"', m.group(0))
            if not href:
                continue
            url = href.group(1)
            if "uddg=" in url:
                url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
            out.append({"title": re.sub(r"<[^>]+>", "", m.group(1)).strip(), "url": url})
            if len(out) >= n:
                break
        return out or [{"note": "no results"}]
    except Exception as e:
        return [{"error": str(e)}]


def fetch_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return "fetch failed: empty url"
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=25, follow_redirects=True)
        html = re.sub(r"(?is)<(script|style|nav|footer|header|svg|noscript)[^>]*>.*?</\1>", " ", r.text)
        text = re.sub(r"(?s)<[^>]+>", " ", html)
        return f"[{url}]\n" + re.sub(r"\s+", " ", text).strip()[:6000]
    except Exception as e:
        return f"fetch failed: {e}"


def _safe_eval(expr: str) -> str:
    env = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
    env.update(abs=abs, round=round, min=min, max=max, sum=sum, pow=pow)
    return str(eval(expr or "0", {"__builtins__": {}}, env))


# --------------------------------------------------------------------------
# Media generation
# --------------------------------------------------------------------------


def _slug(text: str, n: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:n] or "media"


IMG_SIGS = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF8", "gif"),
)


def _sniff_image(raw: bytes) -> str | None:
    """Real extension from the bytes. Providers do not always honour the format."""
    for sig, ext in IMG_SIGS:
        if raw.startswith(sig):
            return ext
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "webp"
    return None


def _looks_image(r: httpx.Response) -> bool:
    if r.status_code != 200 or not r.content:
        return False
    return _sniff_image(r.content) is not None


def _save(sid: str, prompt: str, raw: bytes, ext: str | None = None) -> dict:
    if not raw:
        return {"text": "Empty bytes from provider.", "files": []}
    real = _sniff_image(raw)
    if real:
        ext = real
    elif ext is None:
        return {"text": f"Provider returned {len(raw)} bytes that are not an image.",
                "files": []}

    ws = workspace(sid)
    name = f"{_slug(prompt)}-{int(time.time())}.{ext}"
    try:
        (ws / name).write_bytes(raw)
    except OSError as e:
        return {"text": f"Could not save: {e}", "files": []}
    err = validate_artifact(ws / name)
    if err:
        return {"text": f"Generated but invalid: {err}", "files": []}
    return {"text": f"Generated {name} ({len(raw)} bytes).",
            "files": [{"name": name, "size": len(raw), "url": f"/files/{sid}/{name}"}]}


_CF_ACCOUNT: dict = {"id": "", "at": 0.0}


def _cf_account_id() -> str:
    """Account IDs are 32 hex chars. People paste a token here constantly."""
    raw = (CF_ACCOUNT_ID or "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{32}", raw):
        return raw
    if not CF_API_TOKEN:
        return ""
    if _CF_ACCOUNT["id"] and time.time() - _CF_ACCOUNT["at"] < 3600:
        return _CF_ACCOUNT["id"]
    try:
        r = httpx.get("https://api.cloudflare.com/client/v4/accounts",
                      headers={"Authorization": f"Bearer {CF_API_TOKEN}"}, timeout=20)
        r.raise_for_status()
        rows = r.json().get("result") or []
        if rows:
            _CF_ACCOUNT.update(id=rows[0]["id"], at=time.time())
            return rows[0]["id"]
    except Exception:
        pass
    return ""


def gen_image(sid: str, prompt: str, size: str = "square") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"text": "Empty prompt.", "files": []}
    w, h = SIZE_MAP.get(size, SIZE_MAP["square"])
    fails = []

    if POLLINATIONS:
        try:
            q = urllib.parse.urlencode({
                "width": w, "height": h, "model": "flux",
                "nologo": "true", "seed": int(time.time()) % 999983,
            })
            headers = {"Accept": "image/*"}
            if POLLINATIONS_TOKEN:
                headers["Authorization"] = f"Bearer {POLLINATIONS_TOKEN}"
            r = httpx.get(
                f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt[:900])}?{q}",
                headers=headers, timeout=90, follow_redirects=True)
            if _looks_image(r):
                return _save(sid, prompt, r.content)
            if r.status_code == 402:
                fails.append("pollinations: HTTP 402 — set POLLINATIONS_TOKEN")
            else:
                fails.append(f"pollinations: HTTP {r.status_code}")
        except Exception as e:
            fails.append(f"pollinations: {e}")

    acct = _cf_account_id()
    if acct and CF_API_TOKEN:
        try:
            r = httpx.post(
                f"https://api.cloudflare.com/client/v4/accounts/{acct}"
                "/ai/run/@cf/black-forest-labs/flux-1-schnell",
                headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
                json={"prompt": prompt[:900], "steps": 6}, timeout=90)
            if r.status_code == 200:
                b64 = (r.json().get("result") or {}).get("image")
                if b64:
                    return _save(sid, prompt, base64.b64decode(b64))
                fails.append("cloudflare: 200 but no image field")
            elif r.status_code in (401, 403):
                fails.append(f"cloudflare: HTTP {r.status_code} — token lacks Workers AI")
            else:
                fails.append(f"cloudflare: HTTP {r.status_code} {r.text[:120]}")
        except Exception as e:
            fails.append(f"cloudflare: {e}")
    elif CF_API_TOKEN and not acct:
        fails.append("cloudflare: CF_ACCOUNT_ID is not 32 hex chars and could not be "
                     "derived from the token")

    return {"text": "Every image provider failed.\n" + "\n".join(fails), "files": []}


_HF_MODELS: dict = {"at": 0.0, "list": []}


def hf_video_candidates() -> list[str]:
    """hf-inference only serves some video models; ask which, do not hardcode."""
    cands: list[str] = []
    if HF_VIDEO_MODEL.strip():
        cands.append(HF_VIDEO_MODEL.strip())

    if time.time() - _HF_MODELS["at"] > 3600 or not _HF_MODELS["list"]:
        try:
            r = httpx.get(
                "https://huggingface.co/api/models",
                params={"pipeline_tag": "text-to-video",
                        "inference_provider": "hf-inference",
                        "sort": "downloads", "direction": -1, "limit": 30},
                headers={"Authorization": f"Bearer {HF_TOKEN}"} if HF_TOKEN else None,
                timeout=20)
            if r.status_code == 200:
                found = [m["id"] for m in r.json() if m.get("id")]
                _HF_MODELS.update(at=time.time(), list=found)
        except Exception:
            pass

    for m in _HF_MODELS["list"]:
        if m not in cands:
            cands.append(m)
    return cands


def gen_video(sid: str, prompt: str, size: str = "landscape") -> dict:
    prompt = (prompt or "").strip()
    if not prompt:
        return {"text": "Empty prompt.", "files": []}
    if not HF_TOKEN:
        return {"text": "Video needs HF_TOKEN set.", "files": []}

    cands = hf_video_candidates()
    if not cands:
        return {"text": "No hf-inference video model found. Set HF_VIDEO_MODEL to one "
                        "listed at huggingface.co/models?pipeline_tag=text-to-video.", "files": []}

    fails = []
    for model in cands[:4]:
        try:
            r = httpx.post(
                f"https://router.huggingface.co/hf-inference/models/{model}",
                headers={"Authorization": f"Bearer {HF_TOKEN}", "Accept": "video/mp4"},
                json={"inputs": prompt[:600]}, timeout=VIDEO_TIMEOUT)
            if r.status_code == 200 and r.content:
                ext = "webm" if "webm" in (r.headers.get("content-type") or "").lower() else "mp4"
                return _save(sid, prompt, r.content, ext)
            body = r.text[:140].replace("\n", " ")
            if r.status_code in (400, 404):
                fails.append(f"{model}: not served by hf-inference")
                continue
            if r.status_code == 403:
                fails.append(f"{model}: HTTP 403 — accept the model licence on its page")
                continue
            if r.status_code == 503:
                fails.append(f"{model}: HTTP 503 — model loading, retry shortly")
                continue
            fails.append(f"{model}: HTTP {r.status_code} {body}")
        except httpx.TimeoutException:
            fails.append(f"{model}: timed out after {VIDEO_TIMEOUT}s")
        except Exception as e:
            fails.append(f"{model}: {e}")

    return {"text": "Every video model failed.\n" + "\n".join(fails), "files": []}


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------

CODE_TOOLS = [
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Write a text file directly (md, csv, txt, json, html, py, yaml). No execution. Content is validated.",
        "parameters": {"type": "object",
                       "properties": {"name": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["name", "content"]}}},
    {"type": "function", "function": {
        "name": "run_python",
        "description": ("Run Python to build binary files (pdf, xlsx, docx, png, qr). "
                        "Save into the current directory and print the filename. Output is validated "
                        "for size and file signature; failures are reported so you can fix and retry. "
                        "Available: reportlab, matplotlib, pandas, openpyxl, pillow, qrcode, python-docx, json, csv, zipfile."),
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}},
                       "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "create_zip_archive",
        "description": "Zip every generated file. Call when done building multiple files.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "List files already built in this session.",
        "parameters": {"type": "object", "properties": {}}}},
]

WEB_TOOLS = [
    {"type": "function", "function": {
        "name": "web_search",
        "description": "Search the live web. Returns titles, URLs and snippets.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}},
                       "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_url",
        "description": "Fetch a URL and return readable text.",
        "parameters": {"type": "object", "properties": {"url": {"type": "string"}},
                       "required": ["url"]}}},
]

UTIL_TOOLS = [
    {"type": "function", "function": {
        "name": "get_time", "description": "Current date and time in UTC.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "calculate", "description": "Evaluate a math expression.",
        "parameters": {"type": "object", "properties": {"expression": {"type": "string"}},
                       "required": ["expression"]}}},
]


def _t(name, desc, props, req=()):
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": list(req)}}}


S = {"type": "string"}
DEVICE_TOOLS = [
    _t("remember", "Save a lasting fact about the user (only when they ask you to remember something).",
       {"text": S}, ["text"]),
    _t("set_reminder", "Remind the user in N minutes. Fires only while the app is open; for a guaranteed alert also use device_action kind=ics.",
       {"minutes": {"type": "number"}, "text": S}, ["minutes", "text"]),
    _t("propose_looks", "Change your own look. Draw 4 distinct faces of the SAME character as complete flat-style SVG strings (viewBox 0 0 100 100, no scripts, no images). The user picks one.",
       {"description": S, "svgs": {"type": "array", "items": S}}, ["svgs"]),
    _t("phone_task", "Operate the user's simulated phone (its apps) to do a task. Describe the goal in plain words, e.g. 'open Notes and add a note called Groceries'. It returns what happened. If it returns NEEDS THE USER, ask the user that question in chat and only call again, saying they agreed, if they say yes.",
       {"goal": S}, ["goal"]),
    _t("device_action", "The ONLY way to act on the phone. The user sees Allow once / Deny first. kind: sms (opens a Messages draft), mail (opens a Mail draft), copy (clipboard), url (open a link), ics (calendar event with alarm).",
       {"kind": {"type": "string", "enum": ["sms", "mail", "copy", "url", "ics"]}, "to": S, "subject": S,
        "text": S, "url": S, "title": S, "start_iso": S, "alarm_minutes": {"type": "number"}}, ["kind"]),
]
CLIENT_NAMES = {t["function"]["name"] for t in DEVICE_TOOLS}
DEVICE_PROMPT = """

You are running inside the NanoMuse web app on the user's iPhone. You cannot control other apps on the user's real phone. When the user's simulated phone is open you can operate its apps with phone_task: give it one clear goal, never claim it succeeded unless the result says so, and for anything irreversible (paying, ordering, sending, deleting) tell the user first and wait for a yes. Use device_action for anything that sends, copies, opens or schedules; it always asks the user first, so never say something was sent unless the result says it was done (message drafts still need the user to tap Send). Call client tools one at a time, alone."""


def build_tools(code_on: bool, web_on: bool, device_on: bool = False) -> list:
    tools = list(UTIL_TOOLS) + (DEVICE_TOOLS if device_on else [])
    if code_on and ENABLE_CODE:
        tools += CODE_TOOLS
    if web_on:
        tools += WEB_TOOLS
    return tools


def run_tool(name: str, args: dict, sid: str) -> dict:
    try:
        if name == "get_time":
            return {"text": datetime.now(timezone.utc).isoformat(), "files": []}
        if name == "calculate":
            return {"text": _safe_eval(args.get("expression", "0")), "files": []}
        if name == "web_search":
            return {"text": json.dumps(web_search(args.get("query", "")), indent=1), "files": []}
        if name == "fetch_url":
            return {"text": fetch_url(args.get("url", "")), "files": []}
        if name == "write_file":
            return write_file(sid, args.get("name", "file.txt"), args.get("content", ""))
        if name == "run_python":
            return run_python(sid, args.get("code", ""))
        if name == "create_zip_archive":
            return make_zip(sid)
        if name == "list_files":
            return list_files(sid)
        if name in CLIENT_NAMES:
            return {"text": "Client tools must be called alone, one per turn. Call it again by itself.", "files": []}
        return {"text": f"Unknown tool: {name}", "files": []}
    except HTTPException as e:
        return {"text": f"Tool error: {e.detail}", "files": []}
    except Exception as e:
        return {"text": f"Tool error: {type(e).__name__}: {e}", "files": []}


# --------------------------------------------------------------------------
# Messages
# --------------------------------------------------------------------------


class Attachment(BaseModel):
    kind: str = "text"
    name: str = ""
    data: str = ""


class ToolCall(BaseModel):
    id: str = ""
    type: str = "function"
    function: dict = {}


class Message(BaseModel):
    role: str = "user"
    content: str = ""
    attachments: list[Attachment] = []
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


class Options(BaseModel):
    model: str = "balanced"
    code: bool = True
    web: bool = True
    local_python: bool = False
    device: bool = False
    memory: list[str] = []
    skills: list[str] = []
    lang: str = "en"
    size: str = "square"


class ChatRequest(BaseModel):
    messages: list[Message] = []
    system: str | None = None
    session: str = "anon"
    options: Options = Options()


def has_image(messages: list) -> bool:
    for m in messages:
        c = m.get("content")
        if isinstance(c, list) and any(p.get("type") == "image_url" for p in c):
            return True
    return False


def to_openai_messages(req: ChatRequest) -> list:
    sys_text = req.system or SYSTEM_PROMPT
    if req.options.device:
        sys_text += DEVICE_PROMPT
        if req.options.memory:
            sys_text += "\n\nWhat you know about the user:\n" + "\n".join(
                "- " + m[:300] for m in req.options.memory[-50:])
        if req.options.skills:
            sys_text += "\n\nSkills the user has added (follow them when relevant):\n" + "\n".join(
                "- " + s[:600] for s in req.options.skills[-20:])
        if req.options.lang == "zh":
            sys_text += "\n\nReply in Simplified Chinese unless the user writes in another language."
    out = [{"role": "system", "content": sys_text}]
    for m in req.messages:
        text = m.content or ""
        for a in m.attachments:
            if a.kind == "text" and a.data:
                text += f"\n\n--- file: {a.name or 'file'} ---\n{a.data[:MAX_FILE_CHARS]}"
        images = [a for a in m.attachments if a.kind == "image" and a.data][:4]

        if m.role == "tool":
            out.append({"role": "tool",
                        "tool_call_id": m.tool_call_id or "call_0",
                        "content": text or "(no output)"})
            continue

        msg: dict = {"role": m.role}
        if images and m.role == "user":
            parts = [{"type": "text", "text": text or "What's in this image?"}]
            for a in images:
                url = a.data
                if not url.startswith("data:"):
                    url = f"data:image/jpeg;base64,{url}"
                if len(url) > MAX_IMAGE_CHARS:
                    continue
                parts.append({"type": "image_url", "image_url": {"url": url}})
            msg["content"] = parts
        else:
            msg["content"] = text if text else None

        if m.tool_calls:
            msg["tool_calls"] = [
                {"id": tc.id or f"call_{i}", "type": tc.type or "function",
                 "function": {"name": tc.function.get("name", ""),
                              "arguments": tc.function.get("arguments", "{}")}}
                for i, tc in enumerate(m.tool_calls)
            ]
        out.append(msg)
    return out


# --------------------------------------------------------------------------
# Streaming
# --------------------------------------------------------------------------


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def llm_stream(messages: list, tools: list | None, profile: str = "balanced"):
    wants_image = has_image(messages)
    order = [PROVIDER_BY_NAME[n] for n in PROFILES.get(profile, PROFILES["balanced"])
             if n in PROVIDER_BY_NAME]
    failures: list[str] = []

    for p in order:
        if wants_image and not p.get("vision"):
            continue
        client = _CLIENTS[p["name"]]
        cands = candidate_models(p, wants_image)
        i = 0
        while i < len(cands):
            model = cands[i]
            i += 1
            if model in _DEAD:
                continue
            for tool_payload in ([tools, None] if tools else [None]):
                emitted = False
                try:
                    kwargs = {"model": model, "messages": messages, "stream": True}
                    if tool_payload:
                        kwargs["tools"] = tool_payload
                    stream = client.chat.completions.create(**kwargs)

                    content, calls = "", {}
                    for chunk in stream:
                        if not getattr(chunk, "choices", None):
                            continue
                        delta = chunk.choices[0].delta
                        if getattr(delta, "content", None):
                            content += delta.content
                            emitted = True
                            yield {"type": "delta", "text": delta.content}
                        for tc in getattr(delta, "tool_calls", None) or []:
                            slot = calls.setdefault(tc.index, {"id": "", "name": "", "args": ""})
                            if tc.id:
                                slot["id"] = tc.id
                            fn = getattr(tc, "function", None)
                            if fn:
                                if fn.name:
                                    slot["name"] += fn.name
                                if fn.arguments:
                                    slot["args"] += fn.arguments

                    yield {"type": "_result", "content": content, "calls": calls,
                           "provider": p["name"], "model": model}
                    return
                except Exception as e:
                    if emitted:
                        yield {"type": "_result", "content": "", "calls": {},
                               "provider": p["name"], "model": model,
                               "partial_error": describe_error(p["name"], e)}
                        return
                    replacement = _suggest_slug(e)
                    if replacement and replacement not in cands:
                        _DEAD.add(model)
                        cands.append(replacement)
                    failures.append(describe_error(p["name"], e))

    raise HTTPException(502, "\n".join(dict.fromkeys(failures)) or "No provider reachable.")


# --------------------------------------------------------------------------
# Run registry — generation survives a client disconnect
# --------------------------------------------------------------------------


class Run:
    def __init__(self, sid: str, rid: str | None = None):
        self.sid = sid
        self.id = rid or uuid.uuid4().hex[:16]
        self.events: list[str] = []
        self.done = False
        self.cancelled = False
        self.terminal = False
        self.started = time.time()
        self.cond = threading.Condition()
        self.path = RUN_DIR / f"{self.id}.jsonl"
        if rid is None:
            try:
                RUN_DIR.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps({"_sid": sid}) + "\n", encoding="utf-8")
                (RUN_DIR / f"latest-{sid}").write_text(self.id, encoding="utf-8")
            except OSError:
                pass

    @classmethod
    def load(cls, sid: str, rid: str):
        rid = re.sub(r"[^A-Za-z0-9]", "", rid or "")[:32]
        path = RUN_DIR / f"{rid}.jsonl"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
            meta = json.loads(lines[0])
        except (OSError, ValueError, IndexError):
            return None
        if meta.get("_sid") != sid:
            return None
        run = cls(sid, rid)
        for ln in lines[1:]:
            try:
                obj = json.loads(ln)
            except ValueError:
                continue
            run.events.append(_sse(obj))
            if obj.get("type") in TERMINAL:
                run.terminal = True
        if not run.terminal:
            run.events.append(_sse({"type": "error",
                                    "text": "Server restarted while this was running. Tap Retry."}))
        run.done = True
        return run

    def emit(self, obj: dict) -> None:
        with self.cond:
            final = obj.get("type") in TERMINAL
            if len(self.events) < MAX_RUN_EVENTS or final:
                self.events.append(_sse(obj))
                try:
                    with self.path.open("a", encoding="utf-8") as f:
                        f.write(json.dumps(obj) + "\n")
                except OSError:
                    pass
            if final:
                self.terminal = True
            self.cond.notify_all()

    def finish(self) -> None:
        with self.cond:
            self.done = True
            self.cond.notify_all()

    def count(self) -> int:
        with self.cond:
            return len(self.events)

    def tail(self, since: int = 0):
        i = max(0, since)
        while True:
            batch = []
            with self.cond:
                if i >= len(self.events) and not self.done:
                    self.cond.wait(timeout=15)
                if i >= len(self.events) and self.done:
                    return
                batch = self.events[i:]
                i = len(self.events)
            if not batch:
                yield ": ping\n\n"
                continue
            for frame in batch:
                yield frame


TERMINAL = ("done", "error", "awaiting_client")
RUN_DIR = SANDBOX_ROOT / ".runs"
RUNS: dict[str, Run] = {}
LATEST: dict[str, str] = {}
_RUN_LOCK = threading.Lock()


def _prune_runs() -> None:
    cutoff = time.time() - RUN_TTL
    with _RUN_LOCK:
        for rid in [r.id for r in RUNS.values() if r.started < cutoff]:
            RUNS.pop(rid, None)
        for sid in [s for s, rid in LATEST.items() if rid not in RUNS]:
            LATEST.pop(sid, None)


def _get_run(sid: str, rid: str) -> Run:
    run = RUNS.get(rid)
    if not run:
        run = Run.load(sid, rid)
        if run:
            RUNS[rid] = run
    if not run or run.sid != sid:
        raise HTTPException(404, "run not found or expired")
    return run


def _is_solo_client(calls: dict, o: Options) -> bool:
    if len(calls) != 1:
        return False
    name = next(iter(calls.values()))["name"]
    return (name == "run_python" and o.local_python) or (name in CLIENT_NAMES and o.device)


def _execute(run: Run, req: ChatRequest, sid: str, tools: list, messages: list) -> None:
    provider = None
    try:
        if req.options.model in GEN_MODES:
            prompt = next((m.content for m in reversed(req.messages)
                           if m.role == "user" and m.content), "")
            run.emit({"type": "tool",
                      "name": "gen_video" if req.options.model == "video" else "gen_image",
                      "args": {"query": prompt[:80], "size": req.options.size}})
            out = (gen_video if req.options.model == "video" else gen_image)(
                sid, prompt, req.options.size)
            for f in out["files"]:
                run.emit({"type": "file", **f})
            if out["files"]:
                run.emit({"type": "delta", "text": out["text"]})
            else:
                run.emit({"type": "error", "text": out["text"]})
            run.emit({"type": "done", "provider": req.options.model})
            return

        for _ in range(MAX_TOOL_ROUNDS):
            result = None
            for ev in llm_stream(messages, tools, req.options.model):
                if run.cancelled:
                    return
                if ev["type"] == "_result":
                    result = ev
                else:
                    run.emit(ev)

            if result is None:
                run.emit({"type": "error", "text": "No result returned."})
                return

            provider = result["provider"]

            if result.get("partial_error"):
                run.emit({"type": "error",
                          "text": f"Stream cut short. {result['partial_error']}"})

            calls = result["calls"]
            if not calls:
                run.emit({"type": "done", "provider": provider, "model": result["model"]})
                return

            if _is_solo_client(calls, req.options):
                c = next(iter(calls.values()))
                try:
                    args = json.loads(c["args"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                run.emit({"type": "tool", "name": c["name"], "args": args})
                run.emit({"type": "awaiting_client", "call_id": c["id"],
                          "name": c["name"], "args": args,
                          "assistant_content": result["content"] or ""})
                return

            messages.append({
                "role": "assistant",
                "content": result["content"] or None,
                "tool_calls": [{"id": c["id"] or f"call_{i}", "type": "function",
                                "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                               for i, c in enumerate(calls.values())],
            })

            for i, c in enumerate(calls.values()):
                if run.cancelled:
                    return
                try:
                    args = json.loads(c["args"] or "{}")
                    if not isinstance(args, dict):
                        args = {}
                except json.JSONDecodeError:
                    args = {}
                run.emit({"type": "tool", "name": c["name"], "args": args})
                out = run_tool(c["name"], args, sid)
                for f in out["files"]:
                    run.emit({"type": "file", **f})
                messages.append({"role": "tool",
                                 "tool_call_id": c["id"] or f"call_{i}",
                                 "content": out["text"][:MAX_TOOL_CHARS]})

        run.emit({"type": "done", "provider": provider})
    except HTTPException as e:
        run.emit({"type": "error", "text": str(e.detail)})
    except Exception as e:
        run.emit({"type": "error", "text": describe_error("agent", e)})
    finally:
        run.finish()


# --------------------------------------------------------------------------
# App
# --------------------------------------------------------------------------

app = FastAPI(title="Uncensored Agent Demo")


@app.exception_handler(HTTPException)
async def _http_error(request: Request, exc: HTTPException):
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    lines = []
    for err in exc.errors():
        loc = ".".join(str(x) for x in err.get("loc", ())[1:]) or "body"
        lines.append(f"{loc}: {err.get('msg', 'invalid')}")
    return JSONResponse({"detail": "\n".join(lines) or "Invalid request"}, status_code=422)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    return JSONResponse({"detail": f"Server error: {type(exc).__name__}: {exc}"[:300]},
                        status_code=500)


STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _page(name: str):
    path = STATIC_DIR / name
    if not path.is_file():
        raise HTTPException(404, f"{name} missing")
    return FileResponse(path, media_type="text/html", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    return {"ok": True, "providers": [p["name"] for p in PROVIDERS]}


@app.get("/profiles")
def profiles():
    return {"profiles": [{"id": k, "label": v} for k, v in PROFILE_LABELS.items()]}


@app.get("/models")
def models():
    out = {}
    for name, p in PROVIDER_BY_NAME.items():
        try:
            out[name] = candidate_models(p, False)
        except Exception as e:
            out[name] = [f"error: {e}"]
    return out


@app.get("/gencheck")
def gencheck():
    acct = _cf_account_id()
    return {
        "pollinations": {"enabled": POLLINATIONS, "token": bool(POLLINATIONS_TOKEN)},
        "cloudflare": {
            "token": bool(CF_API_TOKEN),
            "account_id": acct or None,
            "account_id_shape_ok": bool(
                re.fullmatch(r"[0-9a-fA-F]{32}", (CF_ACCOUNT_ID or "").strip())),
        },
        "huggingface": {
            "token": bool(HF_TOKEN),
            "pinned": HF_VIDEO_MODEL or None,
            "discovered": hf_video_candidates()[:6] if HF_TOKEN else [],
        },
    }


@app.get("/selftest")
def selftest():
    sid = f"selftest-{int(time.time())}"
    script = (
        "from reportlab.pdfgen import canvas\n"
        "from reportlab.lib.pagesizes import A4\n"
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        "c = canvas.Canvas('test.pdf', pagesize=A4)\n"
        "c.drawString(72, 720, 'selftest')\n"
        "c.save()\n"
        "plt.plot([1, 2, 3], [2, 4, 9])\n"
        "plt.savefig('test.png', dpi=120, bbox_inches='tight')\n"
        "print('done')\n"
    )
    out = run_python(sid, script)
    return {"ok": len(out["files"]) == 2, "files": out["files"], "detail": out["text"]}


@app.get("/")
def index(request: Request):
    if request.query_params.get("ui") == "nanomuse":
        return _page("nanomuse.html")
    return _page("index.html")


@app.get("/nanomuse")
def nanomuse():
    return _page("nanomuse.html")


import phone_agent  # noqa: E402
phone_agent.register(app, profiles=PROFILES, provider_by_name=PROVIDER_BY_NAME,
                     clients=_CLIENTS, candidate_models=candidate_models)


@app.get("/phone")
def phone():
    # the MobileGym simulator with the nanoMuse app (built by integrate.sh into static/phone/)
    return _page("phone/index.html")


@app.get("/legacy")
def legacy():
    return _page("index.html")


@app.get("/manifest.webmanifest")
def manifest():
    path = STATIC_DIR / "manifest.webmanifest"
    if not path.is_file():
        raise HTTPException(404, "no manifest")
    return FileResponse(path, media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    path = STATIC_DIR / "sw.js"
    if not path.is_file():
        raise HTTPException(404, "no worker")
    return FileResponse(path, media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/files/{sid}")
def files_index(sid: str):
    return list_files(sid)["files"]


@app.get("/files/{sid}/{name:path}")
def get_file(sid: str, name: str, inline: int = 0):
    ws = workspace(sid).resolve()
    try:
        target = (ws / name).resolve()
    except OSError:
        raise HTTPException(404, "not found")
    if ws not in target.parents and target != ws:
        raise HTTPException(404, "not found")
    if not target.is_file():
        raise HTTPException(404, "not found")

    suffix = target.suffix.lower()
    media = MEDIA_TYPES.get(suffix, "application/octet-stream")
    disposition = "inline" if (inline and suffix in INLINE_TYPES) else "attachment"
    safe_ascii = target.name.replace('"', "").replace("\\", "")
    encoded = urllib.parse.quote(target.name, safe="")

    return FileResponse(target, media_type=media, headers={
        "Content-Disposition": f'{disposition}; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded}',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=0, must-revalidate",
    })


@app.post("/zip/{sid}")
def zip_session(sid: str):
    out = make_zip(sid)
    if not out["files"]:
        raise HTTPException(404, "nothing to zip")
    return out["files"][0]


@app.post("/chat")
def chat(req: ChatRequest):
    if not PROVIDERS:
        raise HTTPException(500, "No API keys configured.")

    _janitor()
    _prune_runs()

    sid = re.sub(r"[^A-Za-z0-9_-]", "", req.session or "")[:64] or "anon"
    tools = build_tools(req.options.code, req.options.web, req.options.device)

    try:
        messages = to_openai_messages(req)
    except Exception as e:
        raise HTTPException(422, f"Could not build message payload: {e}")
    if not messages:
        raise HTTPException(422, "No messages supplied.")

    run = Run(sid)
    with _RUN_LOCK:
        RUNS[run.id] = run
        LATEST[sid] = run.id

    threading.Thread(target=_execute, args=(run, req, sid, tools, messages),
                     daemon=True).start()

    return StreamingResponse(
        run.tail(0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                 "X-Run-Id": run.id},
    )


@app.get("/runs/{sid}")
def latest_run(sid: str):
    sid = re.sub(r"[^A-Za-z0-9_-]", "", sid or "")[:64] or "anon"
    rid = LATEST.get(sid)
    if not rid:
        try:
            rid = (RUN_DIR / f"latest-{sid}").read_text(encoding="utf-8").strip()
        except OSError:
            rid = None
    run = _get_run(sid, rid) if rid else None
    if not run:
        return {"run_id": None, "done": True, "count": 0}
    return {"run_id": run.id, "done": run.done, "count": run.count()}


@app.get("/runs/{sid}/{run_id}/stream")
def resume_run(sid: str, run_id: str, since: int = 0):
    run = _get_run(sid, run_id)
    return StreamingResponse(
        run.tail(since), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/runs/{sid}/{run_id}/cancel")
def cancel_run(sid: str, run_id: str):
    run = _get_run(sid, run_id)
    run.cancelled = True
    if not run.terminal:
        run.emit({"type": "error", "text": "Stopped."})
    run.finish()
    return {"ok": True}