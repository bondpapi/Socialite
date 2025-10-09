# syntax=docker/dockerfile:1
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OS deps (curl for healthcheck, build tools for wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl \
 && rm -rf /var/lib/apt/lists/*

# --- Install Python deps (better caching) ---
# If your requirements file is not at repo root, adjust the path in COPY.
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt

# Copy the rest of your app
COPY . .

# Runtime config
ENV API_PORT=8000 \
    UI_PORT=8501 \
    APP_MODULE="social_agent_ai.main:app" \
    STREAMLIT_ENTRY="ui/app.py" \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

EXPOSE 8000 8501

# Simple healthcheck: API must serve its OpenAPI spec
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/openapi.json" || exit 1

# Start API (background) + Streamlit (foreground)
CMD bash -lc " \
  uvicorn \"$APP_MODULE\" --host 0.0.0.0 --port \"$API_PORT\" & \
  streamlit run \"$STREAMLIT_ENTRY\" --server.port=\"$UI_PORT\" --server.address=0.0.0.0 \
"
