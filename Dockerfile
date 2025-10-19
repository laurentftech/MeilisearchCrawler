# KidSearch - Unified Docker Image for Dashboard & API
# Supports multi-service deployment with flexible configuration

FROM python:3.11-slim

LABEL maintainer="KidSearch Team"
LABEL description="KidSearch Dashboard & API - Safe search engine for children"

# Set working directory
WORKDIR /app

# Install system dependencies
# tini is a lightweight init system that reaps zombie processes and forwards signals
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    git \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
COPY requirements-reranking.txt .

# Install Python dependencies
# Base requirements (crawler, API, dashboard)
RUN pip install --no-cache-dir -r requirements.txt

# Optional: Install reranking dependencies (PyTorch, sentence-transformers)
# Uncomment if you want reranking support in the Docker image
# RUN pip install --no-cache-dir -r requirements-reranking.txt

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p data/logs config

# Make start script executable
RUN chmod +x start.py

# Expose ports
# 8501: Dashboard (Streamlit)
# 8080: API (FastAPI)
EXPOSE 8501 8080

# Environment variables with defaults
ENV PYTHONUNBUFFERED=1
ENV SERVICE=all
ENV DASHBOARD_PORT=8501
ENV DASHBOARD_HOST=0.0.0.0
ENV API_PORT=8080
ENV API_HOST=0.0.0.0
ENV API_WORKERS=4
ENV API_ENABLED=true

# Meilisearch URL default for Docker environments
# Assumes Meilisearch is running in a container named 'meilisearch' on the same network
# This can be overridden by docker-compose.
ENV MEILI_URL=http://meilisearch:7700

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entry point
# Use tini to properly handle signals and manage child processes
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
