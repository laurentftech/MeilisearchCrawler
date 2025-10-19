# --- Stage 1: Builder ---
# Utilise une image Python complète pour avoir les outils de compilation nécessaires.
FROM python:3.11 AS builder

LABEL maintainer="KidSearch Team"
LABEL description="Builder stage for KidSearch dependencies"

WORKDIR /app

# Créer un environnement virtuel pour isoler les dépendances.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copier les fichiers de dépendances.
COPY requirements.txt .
COPY requirements-reranking.txt .

# Mettre à jour pip et installer les dépendances dans le venv.
# L'utilisation de --no-cache-dir réduit la taille des couches.
# 1. Installer la version CPU de PyTorch (gain de taille majeur).
# 2. Installer les autres dépendances.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-reranking.txt


# --- Stage 2: Final Image ---
# Utilise une image "slim" qui est beaucoup plus légère.
FROM python:3.11-slim

LABEL maintainer="KidSearch Team"
LABEL description="KidSearch Dashboard & API - Safe search engine for children"

WORKDIR /app

# Installer tini, un init system léger qui gère correctement les signaux et les processus zombies.
RUN apt-get update && apt-get install -y tini && rm -rf /var/lib/apt/lists/*

# Copier l'environnement virtuel complet depuis le stage de build.
COPY --from=builder /opt/venv /opt/venv

# Copier uniquement le code source nécessaire à l'exécution.
# C'est la correction cruciale pour éviter d'embarquer le cache local, .venv, .git, etc.
COPY meilisearchcrawler/ ./meilisearchcrawler
COPY dashboard/ ./dashboard
COPY start.py .
COPY api.py .
COPY crawler.py .
COPY run_api.py .

# Activer l'environnement virtuel pour toutes les commandes suivantes.
ENV PATH="/opt/venv/bin:$PATH"

# Créer les répertoires nécessaires.
RUN mkdir -p data/logs config

# Rendre le script de démarrage exécutable.
RUN chmod +x start.py

# Exposer les ports pour le dashboard et l'API.
EXPOSE 8501 8080

# Définir les variables d'environnement avec des valeurs par défaut.
ENV PYTHONUNBUFFERED=1
ENV SERVICE=all
ENV DASHBOARD_PORT=8501
ENV DASHBOARD_HOST=0.0.0.0
ENV API_PORT=8080
ENV API_HOST=0.0.0.0
ENV API_WORKERS=4
ENV API_ENABLED=true
ENV MEILI_URL=http://meilisearch:7700

# Configurer le health check pour que Docker puisse surveiller l'état de l'application.
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Définir le point d'entrée de l'image.
# Utiliser tini pour lancer le script Python assure une gestion propre des processus.
ENTRYPOINT ["/usr/bin/tini", "--", "python", "start.py"]
CMD ["--docker"]
