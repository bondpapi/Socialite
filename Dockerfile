# syntax=docker/dockerfile:1.6

FROM python:3.11-slim

# General Python/pip settings
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100

# App config
ENV API_PORT=8000 \
    UI_PORT=8501 \
    APP_MODULE="social_agent_ai.main:app" \
    STREAMLIT_ENTRY="ui/app.py" \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# System deps (tini for proper signal handling; curl for healthcheck)
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl tini \
 && rm -rf /var/lib/apt/lists/*

# Python deps (with pip cache for faster rebuilds)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# App code
COPY . .

EXPOSE 8000 8501

# Simple healthcheck (no heredoc or complex quoting)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/docs" >/dev/null || exit 1

# tini as PID 1 for proper signal forwarding
ENTRYPOINT ["/usr/bin/tini","--"]

# Start API in background; Streamlit in foreground (exec-form keeps linters happy)
CMD ["bash","-lc","uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$API_PORT\" & exec streamlit run \"$STREAMLIT_ENTRY\" --server.port=\"$UI_PORT\" --server.address=0.0.0.0"]
