FROM python:3.11-slim

WORKDIR /app

# Install system deps for scipy/numpy and git for version reporting
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (no sounddevice needed for server mode)
COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

# Copy application
COPY . .

# Railway provides PORT at runtime; fall back to 8432 for local Docker runs.
EXPOSE 8432

CMD uvicorn engine.web_server:app --host 0.0.0.0 --port ${PORT:-8432} --timeout-keep-alive 300
