FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1

# App ports
ENV API_PORT=8000 \
  UI_PORT=8501

# Entrypoints / names
ENV APP_MODULE="main:app" \
  STREAMLIT_ENTRY="app.py" \
  STREAMLIT_SERVER_HEADLESS=true \
  STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# Make sure Python can import your packages
ENV PYTHONPATH=/app

# Let Streamlit talk to the API in the same container
ENV SOCIALITE_API=http://127.0.0.1:${API_PORT}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
  curl tini build-essential \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.lock.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install --no-cache-dir -r requirements.lock.txt

COPY . .

RUN chmod +x /app/start.sh

EXPOSE 8000 8501

# (lighter than /docs)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD \
  curl -fsS "http://127.0.0.1:${API_PORT}/ping" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["/bin/sh","-lc","/app/start.sh"]
