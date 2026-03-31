# This code was completed by GRP Team 2025.11.
# Match CI Python version
ARG APT_MIRROR=
ARG FORCE_APT_IPV4=false
ARG PIP_INDEX_URL=
ARG PIP_CERT=

FROM python:3.12-slim-bookworm AS builder

ARG APT_MIRROR
ARG FORCE_APT_IPV4
ARG PIP_INDEX_URL
ARG PIP_CERT

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN if [ -n "$APT_MIRROR" ] && [ -f /etc/apt/sources.list.d/debian.sources ]; then \
            sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
        fi && \
        if [ "$FORCE_APT_IPV4" = "true" ]; then \
            echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4; \
        fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN if [ -n "$PIP_INDEX_URL" ] && [ -n "$PIP_CERT" ]; then \
            pip install --index-url "$PIP_INDEX_URL" --cert "$PIP_CERT" -r requirements.txt; \
        elif [ -n "$PIP_INDEX_URL" ]; then \
            pip install --index-url "$PIP_INDEX_URL" -r requirements.txt; \
        elif [ -n "$PIP_CERT" ]; then \
            pip install --cert "$PIP_CERT" -r requirements.txt; \
        else \
            pip install -r requirements.txt; \
        fi

# --- Runtime stage ---
FROM python:3.12-slim-bookworm

ARG APT_MIRROR
ARG FORCE_APT_IPV4

# Install only the runtime lib needed by psycopg2 / asyncpg
RUN if [ -n "$APT_MIRROR" ] && [ -f /etc/apt/sources.list.d/debian.sources ]; then \
            sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
        fi && \
        if [ "$FORCE_APT_IPV4" = "true" ]; then \
            echo 'Acquire::ForceIPv4 "true";' > /etc/apt/apt.conf.d/99force-ipv4; \
        fi && \
    apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

COPY app ./app
COPY src ./src

# Create runtime directories and set ownership
RUN mkdir -p logs uploads/avatars && chown -R appuser:appuser /app

USER appuser

# Defaults; override in orchestrator / PaaS (many set PORT)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8000 \
    ENVIRONMENT=production \
    RELOAD=false

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${SERVER_PORT:-8000}/health || exit 1

# Single worker default keeps small VMs predictable; scale via replicas or set WORKERS
CMD ["sh", "-c", "exec uvicorn app.main:app --host ${SERVER_HOST} --port ${SERVER_PORT} --workers ${WORKERS:-1}"]
