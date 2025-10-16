# Dashboard Upgrade - Réorganisation et Intégration API

## Résumé des changements

Le Dashboard a été complètement réorganisé pour séparer clairement les fonctionnalités **Crawler** et **API**, avec un point d'entrée unifié pour le déploiement Docker.

## 🎯 Nouvelle organisation

### Sidebar (Panneau latéral)

Le panneau latéral est maintenant divisé en **deux sections distinctes** :

#### 🕸️ Section CRAWLER
Affiche :
- Statut du Crawler (actif/arrêté)
- URLs en cache
- Liste des pages disponibles

Pages Crawler (10-17) :
- **10_Crawler_Overview** : Vue d'ensemble des crawls
- **11_Crawler_Controls** : Contrôles de démarrage/arrêt
- **12_Crawler_Configuration** : Configuration des sites (sites.yml)
- **13_Crawler_Search** : Recherche dans l'index
- **14_Crawler_Statistics** : Statistiques du cache
- **15_Crawler_Page_Tree** : Arbre hiérarchique des pages
- **16_Crawler_Embeddings** : Gestion des embeddings
- **17_Crawler_Logs** : Logs du crawler

#### 🚀 Section API
Affiche :
- Statut de l'API (actif/désactivé)
- URL de l'API
- Documents dans Meilisearch
- Liste des pages disponibles

Pages API (20-21) :
- **20_API_Documentation** : Documentation complète de l'API FastAPI ⭐ NOUVEAU
- **21_API_Monitor** : Monitoring de l'API

## ⭐ Nouvelle page : API Documentation

Une page complète de documentation intégrée au Dashboard qui présente :

### 📖 Documentation Interactive
- Liens directs vers Swagger UI (`/api/docs`)
- Liens directs vers ReDoc (`/api/redoc`)

### 🛣️ Endpoints disponibles
Documentation complète de tous les endpoints :
- `GET /api/health` - Health check
- `GET /api/search` - Recherche unifiée
- `GET /api/stats` - Statistiques
- `POST /api/feedback` - Feedback utilisateur

Chaque endpoint comprend :
- Description détaillée
- Paramètres
- Exemples cURL

### 🏗️ Architecture
Trois onglets explicatifs :

1. **Components** : Description de tous les composants
   - Meilisearch Client
   - Google CSE Client
   - Search Merger
   - Reranker
   - Safety Filter
   - Stats Database

2. **Workflow** : Diagramme du flux de traitement des requêtes
   - Vérification de sécurité
   - Recherche parallèle
   - Fusion des résultats
   - Reranking optionnel

3. **Configuration** : Toutes les variables d'environnement
   - Avec valeurs actuelles
   - Description de chaque variable

### 🚀 Quick Start
Guide de démarrage rapide en 4 étapes

## 🐳 Déploiement Docker unifié

### Nouveau point d'entrée : `start.py`

Un script Python unifié pour lancer :
- Le Dashboard seul
- L'API seule
- Les deux ensemble

**Usage :**

```bash
# Dashboard + API
python start.py --all

# Dashboard uniquement
python start.py --dashboard

# API uniquement
python start.py --api

# Mode Docker (utilise la variable SERVICE)
python start.py --docker
```

**Options :**
- `--dashboard-port` : Port du dashboard (défaut: 8501)
- `--dashboard-host` : Host du dashboard (défaut: 0.0.0.0)
- `--api-port` : Port de l'API (défaut: 8080)
- `--api-host` : Host de l'API (défaut: 0.0.0.0)
- `--api-workers` : Nombre de workers API (défaut: 4)

### Docker Compose

Trois modes de déploiement supportés :

#### Mode 1 : All-in-One (recommandé)
```yaml
services:
  kidsearch-all:
    environment:
      SERVICE: all  # Dashboard + API dans le même conteneur
```

#### Mode 2 : Services séparés
```yaml
services:
  kidsearch-dashboard:
    environment:
      SERVICE: dashboard

  kidsearch-api:
    environment:
      SERVICE: api
```

**Lancement :**

```bash
# All-in-one
docker-compose up -d

# Accès
http://localhost:8501  # Dashboard
http://localhost:8080/api/docs  # API Documentation
```

## 📦 Nouveaux fichiers

### Fichiers créés
1. **`start.py`** : Point d'entrée unifié
2. **`Dockerfile`** : Image Docker multi-service
3. **`docker-compose.yml`** : Configuration Docker Compose
4. **`.dockerignore`** : Optimisation de l'image
5. **`DOCKER_README.md`** : Guide de déploiement Docker complet
6. **`dashboard/pages/20_API_Documentation.py`** : Page de documentation API

### Fichiers modifiés
1. **`dashboard/dashboard.py`** : Sidebar réorganisée en sections
2. **`.env.example`** : Nouvelles variables ajoutées
3. **`dashboard/locales/en.yml`** : Traductions anglaises
4. **`dashboard/locales/fr.yml`** : Traductions françaises

### Pages renommées
Toutes les pages ont été renommées avec des préfixes numériques :
- `01_Overview.py` → `10_Crawler_Overview.py`
- `02_Controls.py` → `11_Crawler_Controls.py`
- etc.

## 🌍 Internationalisation

Toutes les nouvelles fonctionnalités sont entièrement traduites en :
- 🇬🇧 Anglais
- 🇫🇷 Français

Les clés de traduction ajoutées :
- `section_crawler` / `section_api`
- `api_status` / `api_pages_info`
- `api_doc.*` (tous les textes de la page de documentation)

## 🚀 Comment utiliser

### Mode développement (sans Docker)

```bash
# Dashboard seul
python start.py --dashboard

# API seule
python start.py --api

# Les deux
python start.py --all
```

### Mode production (avec Docker)

```bash
# Configuration
cp .env.example .env
# Éditer .env avec vos clés

# Démarrage
docker-compose up -d

# Vérification
docker-compose ps
docker-compose logs -f
```

### Accès aux services

- **Dashboard** : http://localhost:8501
- **API Swagger** : http://localhost:8080/api/docs
- **API ReDoc** : http://localhost:8080/api/redoc
- **Meilisearch** : http://localhost:7700

## 📝 Variables d'environnement ajoutées

```bash
# Dashboard
DASHBOARD_HOST=0.0.0.0
DASHBOARD_PORT=8501

# Docker
SERVICE=all  # Options: all, dashboard, api
```

## 🔧 Gestion avancée

### Logs
```bash
# Tous les services
docker-compose logs -f

# Dashboard uniquement
docker-compose logs -f kidsearch-all | grep "streamlit"

# API uniquement
docker-compose logs -f kidsearch-all | grep "uvicorn"
```

### Redémarrage
```bash
docker-compose restart
```

### Mise à jour
```bash
git pull
docker-compose build --no-cache
docker-compose up -d
```

## 🎨 Améliorations visuelles

1. **Sections claires** dans la sidebar avec titres visuels
2. **Métriques pertinentes** par section
3. **Navigation intuitive** avec préfixes numériques
4. **Documentation riche** avec onglets et expandeurs
5. **Liens interactifs** vers Swagger UI et ReDoc

## 🔍 Compatibilité

- ✅ Compatible avec l'existant (pas de breaking changes)
- ✅ Toutes les fonctionnalités existantes préservées
- ✅ Nouvelles fonctionnalités optionnelles
- ✅ Déploiement flexible (Docker ou standalone)

## 📚 Documentation

Pour plus de détails :
- **Déploiement Docker** : Voir `DOCKER_README.md`
- **Configuration générale** : Voir `CLAUDE.md`
- **API Backend** : Voir `API_README.md`

## 🎯 Prochaines étapes suggérées

1. **Tester le nouveau dashboard** :
   ```bash
   python start.py --dashboard
   ```

2. **Explorer la documentation API** :
   - Aller dans la section API > API Documentation
   - Cliquer sur "Open Swagger UI"

3. **Déployer avec Docker** :
   ```bash
   docker-compose up -d
   ```

4. **Configuration pour production** :
   - Changer les clés par défaut dans `.env`
   - Activer le reranking si souhaité
   - Configurer Google CSE pour la recherche étendue

---

**Auteur** : Claude Code
**Date** : 2025-10-16
**Version** : 2.0
