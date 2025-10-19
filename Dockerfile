# --- Stage 1: Builder ---
FROM python:3.11-slim AS builder

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
COPY requirements-reranking.txt .

# Installer dépendances avec nettoyage et version CPU de torch
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-reranking.txt && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu


# Nettoyage agressif pour alléger torch et dépendances lourdes
RUN rm -rf /opt/venv/lib/python3.11/site-packages/nvidia* \
           /opt/venv/lib/python3.11/site-packages/triton* \
           /opt/venv/lib/python3.11/site-packages/torch/lib/*.a \
           /opt/venv/lib/python3.11/site-packages/torch/include \
           /opt/venv/lib/python3.11/site-packages/torch/share \
           /opt/venv/lib/python3.11/site-packages/torch/test \
           /opt/venv/lib/python3.11/site-packages/torch/_inductor \
           /opt/venv/lib/python3.11/site-packages/torch/utils/benchmark \
           /root/.cache /tmp/* /var/tmp/*


# --- Stage 2: Final Image ---
FROM python:3.11-slim

LABEL maintainer="KidSearch Team"
LABEL description="KidSearch Dashboard & API - Safe search engine for children"

WORKDIR /app

# Installer tini et dépendances minimales
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
    # Créer les fichiers __init__.py pour transformer les répertoires en packages
    # Ceci est crucial pour que les imports relatifs de Streamlit fonctionnent
    touch dashboard/__init__.py && \
    touch dashboard/src/__init__.py

# Nettoyage final
RUN find /opt/venv/lib/python3.11/site-packages -type d -name "__pycache__" -exec rm -rf {} + && \
    find /opt/venv/lib/python3.11/site-packages -type f -name "*.pyc" -delete && \
    rm -rf /root/.cache /tmp/* /var/tmp/*

# Variables d'environnement
ENV SERVICE=all
ENV DASHBOARD_PORT=8501
ENV DASHBOARD_HOST=0.0.0.0
ENV API_PORT=8080
ENV API_HOST=0.0.0.0
ENV API_WORKERS=4
ENV API_ENABLED=true
ENV MEILI_URL=http://meilisearch:7700
# Forcer PyTorch à utiliser le CPU et ignorer les dépendances CUDA
ENV CUDA_VISIBLE_DEVICES=-1

# Exposer les ports
EXPOSE 8501 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
