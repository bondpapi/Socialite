# Use a mirror for the official python image to avoid Docker Hub 503/limits
ARG BASE_IMAGE=public.ecr.aws/docker/library/python:3.11-slim
FROM ${BASE_IMAGE}

ENV PYTHONUNBUFFERED=1 \
  PYTHONDONTWRITEBYTECODE=1 \
  API_PORT=8000 \
  UI_PORT=8501

# Workdir
WORKDIR /app

# System deps and tini for PID 1
RUN apt-get update && apt-get install -y --no-install-recommends \
  build-essential curl tini \
  && rm -rf /var/lib/apt/lists/*

# Python deps (cache layer) then install
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
  pip install --upgrade pip \
  && pip install -r requirements.txt

# App code
COPY . .

# Healthcheck (curl the API docs)
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD curl -fsS "http://127.0.0.1:${API_PORT}/docs" >/dev/null || exit 1

# tini forwards signals to our processes
ENTRYPOINT ["/usr/bin/tini","--"]

# Start API (background) and Streamlit in the foreground
CMD ["/bin/sh","-lc", \
  "uvicorn main:app --host 0.0.0.0 --port $API_PORT & \
  exec streamlit run app.py --server.port=$UI_PORT --server.address=0.0.0.0" \
  ]
