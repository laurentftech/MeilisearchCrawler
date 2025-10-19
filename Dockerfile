# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder
WORKDIR /app

# Installer les outils de compilation nécessaires pour pip
RUN apt-get update && apt-get install -y build-essential && rm -rf /var/lib/apt/lists/*

# Créer l'environnement virtuel
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier les dépendances
COPY requirements.txt .
COPY requirements-reranking.txt .

# Installer pip + dépendances
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch==2.2.0+cpu --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-reranking.txt

# --- Stage 2: Final Image ---
FROM python:3.11-slim
WORKDIR /app

# Installer tini et curl (pour healthcheck)
RUN apt-get update && apt-get install -y tini curl && rm -rf /var/lib/apt/lists/*

# Copier venv depuis le builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier uniquement le code nécessaire
COPY meilisearchcrawler/ ./meilisearchcrawler
COPY dashboard/ ./dashboard
COPY start.py api.py crawler.py run_api.py ./

# Créer les répertoires
RUN mkdir -p data/logs config && chmod +x start.py

# Ports
EXPOSE 8501 8080

# Variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV SERVICE=all
ENV DASHBOARD_PORT=8501
ENV DASHBOARD_HOST=0.0.0.0
ENV API_PORT=8080
ENV API_HOST=0.0.0.0
ENV API_WORKERS=4
ENV API_ENABLED=true
ENV MEILI_URL=http://meilisearch:7700

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
