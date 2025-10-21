FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# App ports
ENV API_PORT=8000 \
  UI_PORT=8501

# Entrypoints / names
# main.py lives at /app/main.py
# package folder is /app/social_agent_ai
ENV APP_MODULE="main:app" \
  STREAMLIT_ENTRY="app.py" \
  STREAMLIT_SERVER_HEADLESS=true \
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false


ENV PYTHONPATH=/app

WORKDIR /app

# System deps we need (curl for healthcheck; tini for PID 1)
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl tini build-essential \
  && rm -rf /var/lib/apt/lists/*

# Python deps (cache wheels)
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Make start script executable
RUN chmod +x /app/start.sh

EXPOSE 8000 8501

# Simple healthcheck against FastAPI docs page
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD \
  curl -fsS "http://127.0.0.1:${API_PORT}/docs" >/dev/null || exit 1

# tini forwards signals properly to both processes
ENTRYPOINT ["/usr/bin/tini","--"]

# Start API (background), then Streamlit in foreground
CMD ["/bin/sh","-lc","/app/start.sh"]
