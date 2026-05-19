FROM python:3.11-slim

WORKDIR /app

# Install system deps for scipy/numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (no sounddevice needed for server mode)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy application
COPY . .

# Render provides PORT env variable
ENV PORT=8432
EXPOSE ${PORT}

CMD uvicorn engine.web_server:app --host 0.0.0.0 --port ${PORT} --timeout-keep-alive 300
