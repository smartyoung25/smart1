# Smart Farm AI Platform — production Dockerfile
# Multi-stage build: builder installs deps, runner is lean

# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.api.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runner

LABEL maintainer="smart-farm-team"
LABEL description="Smart Farm AI Platform API"

# Runtime libs for LightGBM / XGBoost
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy source code (exclude heavy/unnecessary paths via .dockerignore)
COPY api/        ./api/
COPY engine/     ./engine/
COPY models/     ./models/
COPY pipeline/   ./pipeline/
COPY adapters/   ./adapters/

# Frontend served by api/main.py from the app root (_SMARTOS_ROOT = /app):
#   /screens, /components mounts + /index.html, /console, /intro, PWA assets.
# Without these the user-facing pages 404 (previously worked around by a
# docker-compose volume mount — now baked into the image).
COPY screens/    ./screens/
COPY components/ ./components/
COPY index.html console.html sw.js manifest.webmanifest icon.svg og-image.png ./

# Pre-create writable directories
RUN mkdir -p logs pipeline/state

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--log-level", "info", \
     "--access-log"]
