# Uncensored Agent Demo

A minimal, zero-cost AI agent. FastAPI server, provider fallback across free LLM APIs, tool calling, and a built-in chat UI.

## Local run

```bash
git clone <your-repo>
cd uncensored-agent-demo
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# paste at least one API key into .env
export $(grep -v '^#' .env | xargs)
uvicorn main:app --reload --port 8000
```

Then open http://localhost:8000

On Windows PowerShell, set the keys manually instead of exporting:

```powershell
$env:GROQ_API_KEY="your-key"
uvicorn main:app --reload --port 8000
```

Free API keys

At least one is required. Every extra key adds free capacity, because the server falls back down the list whenever a provider fails or rate-limits.

· Groq (no credit card): https://console.groq.com/keys
· Google AI Studio (no credit card): https://aistudio.google.com/apikey
· OpenRouter free models (no credit card): https://openrouter.ai/keys

API

POST a list of messages to /chat:

```bash
curl -X POST https://your-app.onrender.com/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"what time is it in UTC?"}]}'
```

Response:

```json
{
  "reply": "It is 2026-10-26T18:04:11Z",
  "provider": "groq"
}
```

GET /health returns the list of live providers. Useful for uptime pings.

Deploy to Render (free tier)

1. Push this repo to GitHub.
2. In Render: New -> Blueprint -> select the repo. Render reads render.yaml.
3. Paste your API keys into the environment variables when prompted.
4. Deploy. You get a public HTTPS URL.

Free tier notes:

· 512 MB RAM, 0.1 CPU, no GPU.
· The service sleeps after 15 minutes idle. The next request then takes about 30-60 seconds to wake it.
· Add a free cron ping (cron-job.org or UptimeRobot) to /health every 10 minutes to keep it warm.
· Render's free Postgres expires after 30 days. Use Turso or Supabase if you need persistence.

Uncensored notes

Hosted APIs keep some guardrails. To push further:

· Edit SYSTEM_PROMPT to set the tone.
· Lower Gemini safety thresholds to BLOCK_NONE.
· Point OPENROUTER_MODEL at an uncensored finetune from the free pool.
· For full control, self-host open weights on a free GPU notebook (Colab or Kaggle) and point the app at that endpoint instead.

Configuration

Everything is optional. See .env.example. Key settings:

· GROQ_API_KEY, OPENROUTER_API_KEY, GEMINI_API_KEY: provider credentials.
· GROQ_MODEL, OPENROUTER_MODEL, GEMINI_MODEL: override the default model.
· SYSTEM_PROMPT: the agent's system prompt.
· MAX_TOOL_ROUNDS: cap on tool-calling iterations (default 5).
· APP_URL: your public URL, sent to OpenRouter as a referer header.

Project layout

```text
main.py            FastAPI app, provider fallback, tool loop
static/index.html  built-in chat UI
render.yaml        Render blueprint
Dockerfile         optional container build
requirements.txt   dependencies
```

License

MIT. Do whatever you want.