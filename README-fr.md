# Meilisearch Crawler

Ce projet est un crawler web asynchrone et performant, conçu pour peupler une instance Meilisearch avec le contenu de divers sites web. Il sert de compagnon au projet [KidSearch](https://github.com/laurentftech/kidsearch), un moteur de recherche sécurisé pour les enfants.

Le crawler est configurable via un simple fichier YAML (`sites.yml`) et prend en charge les pages HTML, les API JSON et les sites MediaWiki.

## ✨ Fonctionnalités

- **Asynchrone & Parallèle**: Conçu avec `asyncio` et `aiohttp` pour un crawl simultané à haute vitesse.
- **Prêt pour la Recherche Sémantique**: Peut générer et indexer des vecteurs d'embeddings avec l'API Google Gemini pour une recherche sémantique de pointe.
- **Gestion de Quota Intelligente**: Détecte automatiquement lorsque le quota de l'API Gemini est dépassé et arrête le crawl proprement.
- **Tableau de Bord Interactif**: Une interface web basée sur Streamlit pour surveiller, contrôler et configurer le crawler en temps réel.
- **Sources Flexibles**: Prend en charge nativement le crawl de sites web HTML, d'API JSON et de sites sous MediaWiki (comme Wikipedia ou Vikidia).
- **Crawl Incrémentiel**: Utilise un cache local pour ne réindexer que les pages qui ont changé depuis le dernier crawl, économisant temps et ressources.
- **Reprise du Crawl**: Si un crawl est interrompu (manuellement ou par une limite de pages), il peut être repris sans effort.
- **Extraction de Contenu Intelligente**: Utilise `trafilatura` pour une détection robuste du contenu principal depuis le HTML.
- **Respect de `robots.txt`**: Suit les protocoles d'exclusion standards.
- **CLI Avancée**: Options de ligne de commande puissantes pour un contrôle précis.

![screenshot_dashboard.png](media/screenshot_dashboard_fr.png)

## Prérequis

- Python 3.8+
- Une instance Meilisearch en cours d'exécution (v1.0 ou supérieure).
- Une clé API Google Gemini (si vous utilisez la fonction d'embeddings).

## 1. Configuration de Meilisearch

Ce crawler a besoin d'une instance Meilisearch pour y envoyer ses données. La manière la plus simple d'en obtenir une est avec Docker.

1.  **Installez Meilisearch**: Suivez le [guide de démarrage rapide officiel de Meilisearch](https://www.meilisearch.com/docs/learn/getting_started/quick_start).
2.  **Lancez Meilisearch avec une clé principale**:
    ```bash
    docker run -it --rm \
      -p 7700:7700 \
      -e MEILI_MASTER_KEY='une_cle_maitre_longue_et_securisee' \
      -v $(pwd)/meili_data:/meili_data \
      ghcr.io/meilisearch/meilisearch:latest
    ```
3.  **Obtenez votre URL et votre clé API**:
    -   **URL**: `http://localhost:7700`
    -   **Clé API**: La `MEILI_MASTER_KEY` que vous avez définie.

## 2. Configuration du Crawler

1.  **Clonez le dépôt**:
    ```bash
    git clone https://github.com/laurentftech/MeilisearchCrawler.git
    cd MeilisearchCrawler
    ```

2.  **Créez et activez un environnement virtuel**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    ```

3.  **Installez les dépendances**:
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurez les variables d'environnement**:
    Copiez le fichier d'exemple et modifiez-le avec vos informations.
    ```bash
    cp .env.example .env
    ```
    Maintenant, ouvrez `.env` et remplissez :
    - `MEILI_URL`: L'URL de votre instance Meilisearch.
    - `MEILI_KEY`: Votre clé principale Meilisearch.
    - `GEMINI_API_KEY`: Votre clé API Google Gemini (optionnelle, mais requise pour l'option `--embeddings`).

5.  **Configurez les sites à crawler**:
    Copiez le fichier d'exemple des sites.
    ```bash
    cp config/sites.yml.example config/sites.yml
    ```
    Vous pouvez maintenant modifier `config/sites.yml` pour ajouter les sites que vous souhaitez indexer.

## 3. Lancer le Crawler

Vous pouvez lancer le crawler via la ligne de commande ou le tableau de bord interactif.

### Interface en Ligne de Commande

Exécutez simplement le script `crawler.py`:

```sh
python crawler.py # Lance un crawl incrémentiel sur tous les sites
```

**Options courantes:**

-   `--force`: Force une réindexation complète de toutes les pages, en ignorant le cache.
-   `--site "Nom du Site"`: N'explore que le site spécifié.
-   `--embeddings`: Active la génération d'embeddings Gemini pour la recherche sémantique.
-   `--workers N`: Définit le nombre de requêtes parallèles (ex: `--workers 10`).
-   `--stats-only`: Affiche les statistiques du cache sans lancer de crawl.

**Exemple:**
```sh
# Force une réindexation de "Vikidia" avec les embeddings activés
python crawler.py --force --site "Vikidia" --embeddings
```

### Tableau de Bord Interactif

Le projet inclut un tableau de bord web pour surveiller et contrôler le crawler en temps réel.

**Comment le lancer:**

1.  Depuis la racine du projet, exécutez la commande suivante:
    ```bash
    streamlit run dashboard/dashboard.py
    ```
2.  Ouvrez votre navigateur web à l'URL locale fournie par Streamlit (généralement `http://localhost:8501`).

**Fonctionnalités:**

-   **🏠 Vue d'ensemble**: Un résumé en temps réel du crawl en cours.
-   **🔧 Contrôles**: Démarrez ou arrêtez le crawler, sélectionnez des sites, forcez une réindexation et gérez les embeddings.
-   **🔍 Recherche**: Une interface pour tester des requêtes directement sur votre index Meilisearch.
-   **📊 Statistiques**: Des statistiques détaillées sur votre index Meilisearch.
-   **🌳 Arbre des Pages**: Une visualisation interactive de la structure de votre site.
-   **⚙️ Configuration**: Un éditeur interactif pour le fichier `sites.yml`.
-   **🪵 Logs**: Une vue en direct du fichier de log du crawler.

## 4. Configuration de `sites.yml`

Le fichier `config/sites.yml` vous permet de définir une liste de sites à crawler. Chaque site est un objet avec les propriétés suivantes:

- `name`: (String) Le nom du site, utilisé pour le filtrage dans Meilisearch.
- `crawl`: (String) L'URL de départ pour le crawl.
- `type`: (String) Le type de contenu. Peut être `html`, `json`, ou `mediawiki`.
- `max_pages`: (Integer) Le nombre maximum de pages à crawler. Mettre `0` ou omettre pour ne pas avoir de limite.
- `depth`: (Integer) Pour les sites `html`, la profondeur maximale pour suivre les liens.
- `delay`: (Float, optionnel) Un délai spécifique en secondes entre les requêtes pour ce site, ignorant le délai par défaut. Utile pour les serveurs sensibles.
- `selector`: (String, optionnel) Pour les sites `html`, un sélecteur CSS spécifique (ex: `.main-article`) pour cibler le contenu principal.
- `lang`: (String, optionnel) Pour les sources `json`, spécifie la langue du contenu (ex: "fr").
- `exclude`: (Liste de chaînes) Une liste de motifs d'URL à ignorer complètement.
- `no_index`: (Liste de chaînes) Une liste de motifs d'URL à visiter pour découvrir des liens mais à ne pas indexer.

### Type `html`
C'est le type standard pour crawler des sites web classiques. Le crawler commencera à l'URL `crawl` et suivra les liens jusqu'à la `depth` spécifiée.

### Type `json`
Pour ce type, vous devez fournir un objet `json` avec le mappage suivant:
- `root`: La clé dans la réponse JSON qui contient la liste des éléments.
- `title`: La clé du titre de l'élément.
- `url`: Un modèle pour l'URL de l'élément. Vous pouvez utiliser `{{nom_de_la_cle}}` pour substituer une valeur de l'élément.
- `content`: Une liste de clés séparées par des virgules pour le contenu.
- `image`: La clé de l'URL de l'image principale.

### Type `mediawiki`
Ce type est optimisé pour les sites utilisant le logiciel MediaWiki (comme Wikipedia, Vikidia). Il utilise l'API MediaWiki pour récupérer efficacement toutes les pages, évitant un crawl lien par lien.
- L'URL `crawl` doit être l'URL de base du wiki (ex: `https://fr.vikidia.org`).
- `depth` et `selector` ne sont pas utilisés pour ce type.

## 5. Lancer les Tests

Pour exécuter la suite de tests, installez d'abord les dépendances de développement:

```bash
pip install pytest
```

Ensuite, lancez les tests:
```bash
pytest
```
