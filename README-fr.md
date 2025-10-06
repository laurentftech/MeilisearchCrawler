# Meilisearch Crawler

Ce projet est un crawler web asynchrone et performant, conçu pour peupler une instance Meilisearch avec le contenu de divers sites web. Il sert de compagnon au projet [KidSearch](https://github.com/laurentftech/kidsearch), un moteur de recherche sécurisé pour les enfants.

Le crawler est configurable via un simple fichier YAML (`sites.yml`) et prend en charge à la fois les pages HTML et les API JSON comme sources de données.

## Fonctionnalités

- **Asynchrone & Parallèle**: Conçu avec `asyncio` et `aiohttp` pour un crawl simultané à haute vitesse.
- **Crawl multi-sites** : Explore plusieurs sites web définis dans un unique fichier `sites.yml`.
- **Sources flexibles** : Prend en charge les sites web HTML standards et les API JSON.
- **Indexation incrémentielle** : Utilise un cache local pour ne réindexer que les pages qui ont changé depuis le dernier crawl, économisant ainsi du temps et des ressources.
- **Reprise du crawl**: Reprend automatiquement un crawl qui a été arrêté par une limite de pages, permettant une indexation progressive des très grands sites.
- **Extraction de contenu intelligente** : Utilise `trafilatura` pour une détection robuste du contenu principal, avec des heuristiques personnalisées et des sélecteurs CSS manuels en solution de repli.
- **Détection de la langue**: Détecte automatiquement la langue des pages HTML et permet de la spécifier pour les sources JSON, autorisant le filtrage par langue dans les résultats de recherche.
- **Respect de `robots.txt`**: Suit les protocoles d'exclusion standards, y compris la directive `Crawl-delay`, pour être un bon citoyen du web.
- **Exclusions globales et par site**: Intègre une liste de "pièges à crawler" courants (`/login`, `/cart`, etc.) et permet de définir des règles d'exclusion spécifiques à chaque site.
- **CLI avancée**: Options de ligne de commande puissantes pour forcer une réindexation, cibler des sites spécifiques, vider le cache, etc.
- **Configuration facile** : Tous les paramètres sont gérés via un unique fichier `sites.yml` et un fichier `.env` pour les informations d'identification.

## Prérequis

- Python 3.8+
- Une instance Meilisearch en cours d'exécution (v1.0 ou supérieure).

## 1. Configuration de Meilisearch

Ce crawler a besoin d'une instance Meilisearch pour y envoyer ses données. La manière la plus simple d'en obtenir une est avec Docker.

1.  **Installez Meilisearch** : Suivez le guide de démarrage rapide officiel de Meilisearch. Nous recommandons la méthode Docker pour sa simplicité.

2.  **Lancez Meilisearch avec une clé principale** :
    ```bash
    docker run -it --rm \
      -p 7700:7700 \
      -e MEILI_MASTER_KEY='une_cle_maitre_longue_et_securisee' \
      -v $(pwd)/meili_data:/meili_data \
      ghcr.io/meilisearch/meilisearch:latest
    ```

3.  **Obtenez votre URL et votre clé API** :
    -   **URL** : `http://localhost:7700` si vous l'exécutez localement.
    -   **Clé API** : Utilisez la `MEILI_MASTER_KEY` que vous avez définie. Pour la production, il est recommandé d'utiliser une clé API avec des droits plus restreints.

## 2. Configuration du Crawler

1.  **Clonez le dépôt** :
    ```bash
    git clone https://github.com/laurentftech/MeilisearchCrawler.git
    cd MeilisearchCrawler
    ```

2.  **Installez les dépendances** :
    ```bash
    pip install -r requirements.txt
    ```

3.  **Configurez les variables d'environnement** :
    Copiez le fichier d'exemple et modifiez-le avec vos informations d'identification Meilisearch.
    ```bash
    cp .env.example .env
    ```
    Maintenant, ouvrez `.env` et remplissez vos `MEILI_URL` et `MEILI_KEY`.

4.  **Configurez les sites à crawler** :
    Copiez le fichier d'exemple des sites. C'est ici que vous définirez les sites web que le crawler doit visiter.
    ```bash
    cp sites.yml.example sites.yml
    ```
    Vous pouvez maintenant modifier `sites.yml` pour ajouter, supprimer ou modifier les sites que vous souhaitez indexer.

## 3. Lancer le Crawler

Exécutez simplement le script `crawler.py` :

```sh
python crawler.py # Lance un crawl incrémentiel sur tous les sites
```

Le crawler démarrera, lira votre configuration `sites.yml` et commencera à indexer le contenu dans votre instance Meilisearch sous l'index `kidsearch`.

## Lancer les Tests

Pour exécuter la suite de tests, installez d'abord les dépendances de développement :

```bash
pip install pytest
```

## Configuration de `sites.yml`

Le fichier `sites.yml` vous permet de définir une liste de sites à crawler. Chaque site est un objet avec les propriétés suivantes :

- `name` : (String) Le nom du site, utilisé pour le filtrage dans Meilisearch.
- `crawl` : (String) L'URL de départ pour le crawl.
- `type` : (String) Le type de contenu. Peut être `html` ou `json`.
- `max_pages` : (Integer) Le nombre maximum de pages à crawler pour ce site.
- `depth` : (Integer) La profondeur maximale pour suivre les liens à partir de l'URL de départ. Une profondeur de `1` ne crawlera que la page de départ. Une profondeur de `2` crawlera également les pages liées depuis celle-ci.
- `exclude` : (Liste de chaînes de caractères) Une liste de motifs d'URL à exclure du crawl. Toute URL contenant l'une de ces chaînes sera ignorée.

### Configuration spécifique au type JSON

Si `type` est `json`, vous devez également fournir un objet `json` avec le mappage suivant :

- `root` : La clé dans la réponse JSON qui contient la liste des éléments.
- `id` : La clé de l'identifiant unique de chaque élément.
- `title` : La clé du titre de l'élément.
- `url` : La clé de l'URL de l'élément.
-   **URL par template** : Vous pouvez construire des URL en utilisant des valeurs de l'objet JSON. Utilisez `{{nom_de_la_cle}}` pour substituer une valeur. Par exemple : `"https://exemple.com/livres/{{id}}"`.
- `content` : Une liste de clés séparées par des virgules pour le contenu. Vous pouvez utiliser `[]` pour accéder à tous les éléments d'une liste (par exemple, `authors[].name`).
- `image` : La clé de l'URL de l'image principale de l'élément.
-   **URL d'image par template** : Ceci supporte également les templates, comme le champ `url`. Par exemple : `"https://covers.exemple.com/{{cover_id}}.jpg"`.

## Contribuer

Les pull requests sont les bienvenues. Pour les changements majeurs, veuillez d'abord ouvrir une issue pour discuter de ce que vous souhaitez changer.

## Licence

MIT