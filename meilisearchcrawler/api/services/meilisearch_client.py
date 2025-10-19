"""
Meilisearch client service for KidSearch API.
Handles search queries against local indexed content.
"""

import logging
import hashlib
import os
import sys
from pathlib import Path
from typing import List, Optional
import meilisearch
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from meilisearchcrawler.embeddings import create_embedding_provider, EmbeddingProvider, NoEmbeddingProvider

from ..models import SearchResult, SearchSource, ImageResult

logger = logging.getLogger(__name__)


class MeilisearchClient:
    """
    Client for searching local Meilisearch index.
    """

    def __init__(self, url: str, api_key: str, index_name: str):
        """
        Initialize Meilisearch client.

        Args:
            url: Meilisearch server URL
            api_key: Meilisearch API key
            index_name: Index to search
        """
        self.url = url
        self.api_key = api_key
        self.index_name = index_name
        self.client = None
        self.index = None

        # Initialiser le provider d'embeddings pour les requêtes
        # (utilisé uniquement si EMBEDDING_PROVIDER != gemini)
        self.embedding_provider = None
        self.use_vector_search = False

        embedding_provider = os.getenv("EMBEDDING_PROVIDER", "none").lower()
        if embedding_provider == "snowflake":
            try:
                self.embedding_provider = create_embedding_provider(embedding_provider)
                self.use_vector_search = self.embedding_provider.get_embedding_dim() > 0
                if self.use_vector_search:
                    logger.info(f"✓ Vector search enabled with {embedding_provider.title()} ({self.embedding_provider.get_embedding_dim()}D)")
            except Exception as e:
                logger.warning(f"Failed to initialize embedding provider for queries: {e}")
                self.use_vector_search = False
        elif embedding_provider == "gemini":
            # Gemini utilise le REST embedder configuré dans MeiliSearch
            logger.info("✓ Vector search enabled with Gemini (REST embedder)")
            self.use_vector_search = True
        else:
            # S'assurer que self.embedding_provider n'est jamais None
            if self.embedding_provider is None:
                self.embedding_provider = NoEmbeddingProvider()
            logger.info("Vector search disabled (no embedding provider)")

    def connect(self):
        """Connect to Meilisearch and get index."""
        try:
            self.client = meilisearch.Client(self.url, self.api_key)
            self.index = self.client.index(self.index_name)

            # Test connection
            self.client.health()
            logger.info(f"Connected to Meilisearch at {self.url}, index: {self.index_name}")

        except MeilisearchCommunicationError as e:
            # Intercepter spécifiquement l'erreur de connexion pour un log propre
            logger.error(f"Failed to connect to Meilisearch at {self.url}. Please check if the service is running and accessible.")
            raise  # Renvoyer l'exception pour que le serveur puisse démarrer en mode dégradé
        except Exception as e:
            logger.error(f"An unexpected error occurred while connecting to Meilisearch: {e}")
            raise

    def is_healthy(self) -> bool:
        """Check if Meilisearch is healthy."""
        try:
            if not self.client:
                return False
            health = self.client.health()
            return health.get("status") == "available"
        except Exception:
            return False

    async def search(
        self, query: str, lang: Optional[str] = None, limit: int = 20
    ) -> List[SearchResult]:
        """
        Search Meilisearch index.

        Args:
            query: Search query
            lang: Language filter (optional)
            limit: Maximum results to return

        Returns:
            List of search results
        """
        if not self.index:
            logger.error("Meilisearch client not connected")
            return []

        try:
            # Build search parameters optimized for speed
            search_params = {
                "limit": limit,
                "attributesToRetrieve": [
                    "id", "title", "url", "excerpt",  # Don't retrieve full content
                    "site", "images", "lang", "timestamp", "indexed_at"
                ],
                "attributesToSearchOn": ["title", "excerpt"],  # Search only in title/excerpt
                "showRankingScore": True,
            }

            # Add language filter if specified
            if lang:
                search_params["filter"] = f"lang = {lang}"

            # Add vector search if enabled and provider is Snowflake
            if self.use_vector_search and self.embedding_provider:
                try:
                    # Générer l'embedding de la requête avec Snowflake
                    query_embeddings = self.embedding_provider.encode([query])
                    if query_embeddings and len(query_embeddings) > 0:
                        search_params["vector"] = query_embeddings[0]
                        # Paramètre hybrid requis quand on utilise vector search
                        search_params["hybrid"] = {
                            "semanticRatio": 0.5,  # 50% sémantique, 50% texte
                            "embedder": "default"
                        }
                        logger.debug(f"Added vector search for query: '{query}'")
                except Exception as e:
                    logger.warning(f"Failed to generate query embedding: {e}")
                    # Continue without vector search

            # Execute search
            results = self.index.search(query, search_params)

            # Convert to SearchResult models
            search_results = []
            for hit in results.get("hits", []):
                # Parse images
                images = []
                for img_data in hit.get("images", [])[:5]:  # Max 5 images
                    if isinstance(img_data, dict):
                        images.append(
                            ImageResult(
                                url=img_data.get("url", ""),
                                alt=img_data.get("alt"),
                                description=img_data.get("description"),
                            )
                        )

                # Calculate score (Meilisearch returns scores, normalize to 0-1)
                # Meilisearch _rankingScore is between 0 and 1
                score = hit.get("_rankingScore", 0.5)

                # Create result (content=None for speed - not retrieved)
                result = SearchResult(
                    id=hit.get("id", self._generate_id(hit.get("url", ""))),
                    title=hit.get("title", ""),
                    url=hit.get("url", ""),
                    excerpt=hit.get("excerpt", ""),
                    content=None,  # Not retrieved for performance
                    site=hit.get("site"),
                    images=images,
                    lang=hit.get("lang"),
                    timestamp=hit.get("timestamp"),
                    indexed_at=hit.get("indexed_at"),
                    source=SearchSource.MEILISEARCH,
                    score=score,
                )

                search_results.append(result)

            logger.info(
                f"Meilisearch search for '{query}' (lang={lang}): "
                f"{len(search_results)} results"
            )

            return search_results

        except MeilisearchApiError as e:
            logger.error(f"Meilisearch API error: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Meilisearch search error: {e}", exc_info=True)
            return []

    def _generate_id(self, url: str) -> str:
        """Generate unique ID from URL."""
        return hashlib.md5(url.encode()).hexdigest()

    def get_index_stats(self) -> dict:
        """Get index statistics."""
        try:
            if not self.index:
                return {}

            stats = self.index.get_stats()
            return {
                "numberOfDocuments": stats.get("numberOfDocuments", 0),
                "isIndexing": stats.get("isIndexing", False),
                "fieldDistribution": stats.get("fieldDistribution", {}),
            }
        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            return {}
