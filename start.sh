#!/usr/bin/env sh
set -euo pipefail

# Defaults (can be overridden by env/.env)
API_PORT="${API_PORT:-8000}"
UI_PORT="${UI_PORT:-8501}"
APP_MODULE="${APP_MODULE:-main:app}"
STREAMLIT_ENTRY="${STREAMLIT_ENTRY:-app.py}"

# If Render provides $PORT, prefer it for the API listener
# (Render exposes only one port; Streamlit is for local dev)
if [ -n "${PORT:-}" ]; then
  API_PORT="$PORT"
fi

echo "Starting API on 0.0.0.0:${API_PORT} (module=${APP_MODULE})"
uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!

# Small wait loop so healthchecks don’t flap and local UI can talk to API
for i in $(seq 1 40); do
  if command -v curl >/dev/null 2>&1; then
    if curl -fsS "http://127.0.0.1:${API_PORT}/ping" >/dev/null 2>&1; then
      echo "API is up ✅"
      break
    fi
  fi
  sleep 0.25
done

# If we're running locally (no $PORT), also launch Streamlit for the UI
if [ -z "${PORT:-}" ]; then
  echo "Starting Streamlit UI on 0.0.0.0:${UI_PORT}"
  exec streamlit run "$STREAMLIT_ENTRY" --server.address 0.0.0.0 --server.port "$UI_PORT"
fi

# On Render: keep the API in foreground by waiting on the API PID
wait "$API_PID"
