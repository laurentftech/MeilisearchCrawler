# Changelog

Toutes les modifications notables apportées à ce projet seront documentées dans ce fichier.

## 2025-10-30

### ✨ Fonctionnalités

- **Support Multilingue WikiClient** : Le client MediaWiki détecte automatiquement la langue depuis l'URL de l'API (en.wikipedia.org, fr.wikipedia.org, etc.) et adapte les headers HTTP (`Accept-Language`) en conséquence.
- **Multi-Wiki Support** : L'API supporte maintenant plusieurs instances MediaWiki simultanément (Wikipedia EN, FR, Vikidia, etc.) via des variables d'environnement `WIKI_2_*`, `WIKI_3_*`, etc.

### 🚀 Performance

- **Compression GZIP** : Ajout du header `Accept-Encoding: gzip, deflate` pour les requêtes vers Google CSE et MediaWiki, réduisant significativement l'utilisation de la bande passante et améliorant les temps de réponse.

### 🐛 Corrections de bugs

- **Dashboard Meilisearch Server** : Correction de l'erreur lors de la suppression d'index (`'Client' object has no attribute 'delete_index'`). La méthode correcte `index.delete()` est maintenant utilisée.
- **Dashboard Embeddings** : Amélioration de la gestion d'erreur pour les versions récentes de Meilisearch où la fonctionnalité `multimodal` est activée par défaut. Ajout d'une méthode de fallback pour compter les documents avec/sans embeddings.

## 2025-10-29

### ✨ Fonctionnalités

- **Dashboard Métriques API** : Ajout de nouvelles métriques pour suivre le temps de recherche moyen global (`avg_search_time`) et le temps de réponse moyen de MediaWiki (`avg_wiki_time_ms`).
- **Dashboard Moniteur API** : Ajout d'un bouton pour réinitialiser toutes les statistiques de l'API, avec une boîte de dialogue de confirmation pour prévenir les suppressions accidentelles.
- **API Stats** : Augmentation de la limite des "requêtes populaires" remontées par l'endpoint `/api/stats` de 10 à 50.

### 🚀 Performance & Refactorisation

- **Architecture des Embeddings** : Refactorisation majeure de la gestion des embeddings pour améliorer les performances et réduire la latence.
    - La logique de calcul des embeddings (batching, cache) a été centralisée dans le service `EmbeddingProvider` (`embeddings.py`).
    - L'endpoint de recherche (`search.py`) calcule désormais les embeddings pour les résultats externes (Google CSE, MediaWiki) de manière asynchrone dès leur réception.
    - Le `Reranker` (`reranker.py`) est maintenant un composant purement calculatoire qui se concentre uniquement sur le classement, en partant du principe que tous les résultats ont déjà leurs vecteurs. Cette modification élimine un goulot d'étranglement majeur.

### 🐛 Corrections de bugs

- **Stabilité de l'API** : Correction d'une dépendance circulaire entre `server.py` et `routes/search.py` qui provoquait le crash de l'application au démarrage.
- **Qualité du code** : Introduction d'une classe `AppState` typée pour l'état de l'application FastAPI, ce qui élimine les avertissements de l'IDE (PyCharm) et améliore la robustesse du code.
- **Dashboard Moniteur API** : Correction d'un bug qui empêchait les données (notamment les requêtes populaires) de se rafraîchir automatiquement ou manuellement.
- **API Stats** : Correction d'un bug où l'endpoint `/api/stats` renvoyait des données mises en cache par le navigateur, empêchant l'affichage des informations à jour.
- **Métriques Prometheus** : Restauration des métriques pour `cse_time_ms`, `wiki_time_ms` et `reranking_time_ms` qui avaient été accidentellement supprimées.
- **Stabilité de l'API** : Correction d'une erreur de validation Pydantic qui survenait lorsque la base de données de statistiques n'était pas disponible.
- **Statistiques de recherche** : Correction d'une régression qui avait supprimé la capture des temps d'exécution individuels pour Meilisearch, CSE et MediaWiki.
