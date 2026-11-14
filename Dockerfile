# ---- stage 1: build the original phone simulator (MobileGym + nanoMuse app) ----
FROM node:22-bookworm-slim AS phone
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates python3 \
 && rm -rf /var/lib/apt/lists/*
COPY nanomuse/ /nm/
WORKDIR /mg
RUN ref=$(grep -v '^#' /nm/mobilegym.ref | tr -d '[:space:]') \
 && git init -q . \
 && git remote add origin https://github.com/Purewhiter/mobilegym.git \
 && git fetch -q --depth 1 origin "$ref" \
 && git checkout -q --detach FETCH_HEAD
RUN npm ci --no-audit --no-fund
RUN sh /nm/mobilegym/install.sh /mg \
 && python3 /nm/patch_module.py /mg/apps/nanoMuse
ENV VITE_NANOMUSE_EMBED=1 \
    VITE_CDN_BASE=https://cdn.mobilegym.dev \
    NODE_OPTIONS=--max-old-space-size=3072
RUN npm run build -- --base=/static/phone/

# ---- stage 2: your app, unchanged except it now carries static/phone ----
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MPLBACKEND=Agg

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgl1 libglib2.0-0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=phone /mg/dist /app/static/phone

RUN useradd -m -u 10001 agent \
 && mkdir -p /tmp/sandbox \
 && chown -R agent:agent /app /tmp/sandbox
USER agent

ENV PORT=8000
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
