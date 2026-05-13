# Single-image build: backend API + frontend static bundle.

FROM node:20-alpine AS frontend-builder
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS backend-builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY --from=backend-builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=backend-builder /usr/local/bin /usr/local/bin

# Ensure startup logs stream immediately in container terminals.
ENV PYTHONUNBUFFERED=1

# Fix ctranslate2/faster-whisper execstack requirement on Linux/WSL2
RUN apt-get update && apt-get install -y --no-install-recommends patchelf \
    && find /usr/local/lib/python3.11/site-packages/ctranslate2 -name "*.so*" -exec patchelf --clear-execstack {} \; \
    && rm -rf /var/lib/apt/lists/*

# Backend source code
COPY backend/ ./

# Bundled frontend static assets served by FastAPI
COPY --from=frontend-builder /frontend/dist ./frontend_dist

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/docs', timeout=5).read()" || exit 1

CMD ["python", "-u", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8001"]
