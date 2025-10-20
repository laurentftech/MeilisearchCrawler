# --- Stage 1: Builder ---
FROM python:3.13-slim AS builder

LABEL maintainer="KidSearch Team"
LABEL description="Builder stage for KidSearch dependencies"

WORKDIR /app

# Installer les outils minimaux nécessaires à la compilation de certaines libs (comme curl_cffi)
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl && \
    rm -rf /var/lib/apt/lists/*

# Créer l'environnement virtuel
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier les requirements
COPY requirements.txt .

# Installer les dépendances
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt


# --- Stage 2: Final Image ---
FROM python:3.13-slim

LABEL maintainer="KidSearch Team"
LABEL description="KidSearch Dashboard & API - Safe search engine for children"

WORKDIR /app

# Installer tini pour la gestion des signaux et curl pour le healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends tini curl && \
    rm -rf /var/lib/apt/lists/*

# Copier l'environnement virtuel depuis le builder
COPY --from=builder /opt/venv /opt/venv

# Copier le code source
COPY meilisearchcrawler/ ./meilisearchcrawler
COPY dashboard/ ./dashboard
COPY start.py .
COPY api.py .
COPY crawler.py .
COPY run_api.py .

# Activer le venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

# Créer répertoires nécessaires
RUN mkdir -p data/logs config && \
    touch dashboard/__init__.py && \
    touch dashboard/src/__init__.py

# Nettoyage final des caches
RUN find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + && \
    find /opt/venv -type f -name "*.pyc" -delete && \
    rm -rf /root/.cache /tmp/* /var/tmp/*

# Variables d'environnement de base
ENV SERVICE=all
ENV DASHBOARD_PORT=8501
ENV DASHBOARD_HOST=0.0.0.0
ENV API_PORT=8080
ENV API_HOST=0.0.0.0
ENV API_WORKERS=4
ENV API_ENABLED=true
ENV MEILI_URL=http://meilisearch:7700

# Exposer les ports
EXPOSE 8501 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
