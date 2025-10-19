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

# Installer les dépendances en une seule fois, en forçant la version CPU de PyTorch
# pour toutes les sous-dépendances (comme sentence-transformers).
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Désinstaller tous les packages NVIDIA/CUDA potentiels
RUN pip uninstall -y nvidia-pip-plugin torch-triton nvidia-cuda-runtime-cu12 nvidia-cuda-nvrtc-cu12 nvidia-cudnn-cu12 2>/dev/null || true

# Nettoyage agressif pour alléger torch et dépendances lourdes
RUN rm -rf /opt/venv/lib/python3.11/site-packages/nvidia* \
           /opt/venv/lib/python3.11/site-packages/triton* \
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
ENV CUDA_VISIBLE_DEVICES=""
ENV FORCE_CUDA=0
ENV FORCE_CPU=1
ENV PYTORCH_ENABLE_MPS_FALLBACK=1
ENV OMP_NUM_THREADS=1
ENV MKL_NUM_THREADS=1

# Exposer les ports
EXPOSE 8501 8080

# Healthcheck
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Entrypoint
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
