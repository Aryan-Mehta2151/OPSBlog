# ── Stage 1: Build React frontend ──
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python backend + static frontend ──
FROM python:3.11-slim

# System dependencies (Tesseract OCR, poppler for PDFs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY backend/ .

# Copy built frontend into the expected location
# main.py looks for ../../frontend/dist relative to app/main.py
# Since WORKDIR is /app (= backend), that resolves to /frontend/dist
COPY --from=frontend-build /app/frontend/dist /frontend/dist

# Create directories (will use persistent disk in production)
RUN mkdir -p uploads/pdfs uploads/images chroma_db /app/data

# Default env vars (overridden by Render/production)
ENV UPLOAD_DIR=uploads
ENV CHROMA_DB_PATH=./chroma_db

# Run Alembic migrations then start the server
COPY <<'EOF' /app/start.sh
#!/bin/bash
set -e
echo "Running database migrations..."
alembic upgrade head
echo "Starting server on port ${PORT:-8000}..."
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --log-level info 2>&1
EOF
RUN chmod +x /app/start.sh

EXPOSE 8000

CMD ["/app/start.sh"]
