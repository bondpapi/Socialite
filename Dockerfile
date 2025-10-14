# ---------- Dockerfile (API-only) ----------
FROM python:3.11-slim

# System deps (curl only for healthchecks / debugging)
RUN apt-get update && apt-get install -y --no-install-recommends \
  curl \
  && rm -rf /var/lib/apt/lists/*

# Faster, reliable installs
ENV PIP_NO_CACHE_DIR=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

WORKDIR /app

# Install python deps first (for layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Render will inject $PORT; default to 8000 when running locally
ENV PORT=8000

# Expose the (internal) port for local runs; Render maps externally for you
EXPOSE 8000

# Optional healthcheck (switch to /healthz if you have it)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS "http://127.0.0.1:${PORT}/docs" >/dev/null || exit 1

# Start FastAPI with uvicorn on the port Render provides
CMD ["/bin/sh", "-lc", "uvicorn social_agent_ai.main:app --host 0.0.0.0 --port ${PORT}"]
