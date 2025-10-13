# ---- base ----
FROM python:3.11-slim

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  API_PORT=8000 \
  UI_PORT=8501 \
  APP_MODULE="social_agent_ai.main:app" \
  STREAMLIT_ENTRY="ui/app.py" \
  STREAMLIT_SERVER_HEADLESS=true \
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

WORKDIR /app

# System deps: curl for healthcheck, tini as PID1, build tools for wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential curl tini \
  && rm -rf /var/lib/apt/lists/*

# Python deps (cache layer) then install
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install -r requirements.txt

# App code + start script
COPY . .
# Ensure start script is executable
RUN chmod +x ./start.sh

EXPOSE 8000 8501

# Simple curl-based healthcheck (no heredoc)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/docs" >/dev/null || exit 1

# tini forwards signals to our processes
ENTRYPOINT ["/usr/bin/tini","--"]

# Start both processes (uvicorn in background, Streamlit in foreground)
CMD ["/bin/sh", "-c", "/app/start.sh"]
