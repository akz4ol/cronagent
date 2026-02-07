# CronAgent Dockerfile
# Multi-stage build for minimal production image

# ============================================================
# Stage 1: Builder
# ============================================================
FROM python:3.12-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install dependencies first (cached layer)
WORKDIR /build
COPY pyproject.toml README.md ./
COPY src/cronagent/__init__.py src/cronagent/

# Install package with all optional dependencies
RUN pip install --no-cache-dir --upgrade pip wheel && \
    pip install --no-cache-dir ".[all]"

# Copy full source and reinstall
COPY . .
RUN pip install --no-cache-dir .

# ============================================================
# Stage 2: Runtime
# ============================================================
FROM python:3.12-slim AS runtime

# Labels
LABEL org.opencontainers.image.title="CronAgent"
LABEL org.opencontainers.image.description="Autonomous agent system with Claude SDK"
LABEL org.opencontainers.image.version="0.1.0"
LABEL org.opencontainers.image.source="https://github.com/yourname/cronagent"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r cronagent && useradd -r -g cronagent cronagent

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Set up application directory
WORKDIR /app

# Create directories for data persistence
RUN mkdir -p /home/cronagent/.cronagent && \
    mkdir -p /app/skills && \
    chown -R cronagent:cronagent /home/cronagent /app

# Copy entrypoint script
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/

# Environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CRONAGENT_HOME=/home/cronagent/.cronagent \
    # ChromaDB settings for container
    ANONYMIZED_TELEMETRY=false \
    CHROMA_IS_PERSISTENT=true

# Switch to non-root user
USER cronagent

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD cronagent status || exit 1

# Default command
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["daemon"]

# Expose webhook port
EXPOSE 8080
