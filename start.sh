#!/bin/sh
set -eu

# Start FastAPI (background)
uvicorn "${APP_MODULE}" --host 0.0.0.0 --port "${API_PORT}" &

# Start Streamlit (foreground)
exec streamlit run "${STREAMLIT_ENTRY}" \
  --server.port="${UI_PORT}" \
  --server.address=0.0.0.0
