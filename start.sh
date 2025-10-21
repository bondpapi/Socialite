set -e

# Defaults (Render/Docker can override)
: "${API_PORT:=8000}"
: "${UI_PORT:=8501}"
: "${APP_MODULE:=main:app}"
: "${STREAMLIT_ENTRY:=app.py}"

# Start FastAPI (background)
uvicorn "$APP_MODULE" --host 0.0.0.0 --port "$API_PORT" &
API_PID=$!

# Start Streamlit (foreground)
exec streamlit run "$STREAMLIT_ENTRY" --server.port="$UI_PORT" --server.address=0.0.0.0
