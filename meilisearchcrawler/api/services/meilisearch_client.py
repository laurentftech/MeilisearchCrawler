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

from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.errors import MeilisearchApiError, MeilisearchCommunicationError
from meilisearch_python_sdk.models.search import SearchResults

# Ajouter le répertoire racine au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
from meilisearchcrawler.embeddings import create_embedding_provider, EmbeddingProvider, NoEmbeddingProvider
from ..models import SearchResult, SearchSource, ImageResult

logger = logging.getLogger(__name__)


class MeilisearchClient:
    """
    Client for searching a local Meilisearch index.
    Supports keyword and vector (semantic) search if embeddings are configured.
    """

    def __init__(self, url: str, api_key: str, index_name: str):
        """
        Initialize Meilisearch client.
        """
        self.url = url
        self.api_key = api_key
        self.index_name = index_name
        self.client: Optional[AsyncClient] = None
        self.index = None

        self.embedding_provider: EmbeddingProvider = NoEmbeddingProvider()
        self.use_vector_search = False
        self.is_rest_embedder = False

        embedding_provider_name = os.getenv("EMBEDDING_PROVIDER", "none").lower()

        if embedding_provider_name == "gemini":
            logger.info("✓ Vector search enabled with Gemini (REST embedder)")
            self.use_vector_search = True
            self.is_rest_embedder = True
        elif embedding_provider_name in ["huggingface", "sentence_transformer"]:
            try:
                self.embedding_provider = create_embedding_provider(embedding_provider_name)
                if self.embedding_provider.get_embedding_dim() > 0:
                    self.use_vector_search = True
                    logger.info(
                        f"✓ Vector search enabled with {embedding_provider_name.title()} "
                        f"({self.embedding_provider.get_embedding_dim()}D)"
                    )
            except Exception as e:
                logger.warning(f"Failed to initialize embedding provider for queries: {e}")
        else:
            logger.info("Vector search disabled (no embedding provider)")

    async def connect(self):
        """Connect to Meilisearch and initialize the index."""
        try:
            self.client = AsyncClient(self.url, self.api_key)
            self.index = self.client.index(self.index_name)
            await self.client.health()
            logger.info(f"Connected to Meilisearch at {self.url}, index: {self.index_name}")
        except MeilisearchCommunicationError:
            logger.error(f"Failed to connect to Meilisearch at {self.url}. Service may be down.")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while connecting to Meilisearch: {e}")
            raise

    async def is_healthy(self) -> bool:
        """Check if Meilisearch is healthy."""
        if not self.client:
            return False
        try:
            health = await self.client.health()
            return health.status == "available"
        except Exception:
            return False

    async def search(
        self, query: str, lang: Optional[str] = None, limit: int = 20
    ) -> List[SearchResult]:
        """Search Meilisearch index using keyword or hybrid vector search."""
        if not self.index:
            logger.error("Meilisearch client not connected")
            return []

        try:
            search_params = {
                "limit": limit,
                "attributes_to_retrieve": [
                    "id", "title", "url", "excerpt", "site", "images", "lang", "timestamp", "indexed_at"
                ],
                "attributes_to_search_on": ["title", "excerpt"],
                "show_ranking_score": True,
            }

            if lang:
                search_params["filter"] = f"lang = {lang}"

            if self.use_vector_search:
                search_params["hybrid"] = {"semantic_ratio": 0.5}
                if not self.is_rest_embedder:
                    try:
                        query_embeddings = self.embedding_provider.encode([query])
                        if query_embeddings and query_embeddings[0]:
                            search_params["vector"] = query_embeddings[0]
                            logger.debug(f"Added vector for query: '{query}'")
                    except Exception as e:
                        logger.warning(f"Failed to generate query embedding, falling back to keyword search: {e}")
                        del search_params["hybrid"]

            results: SearchResults = await self.index.search(query, **search_params)

            search_results: List[SearchResult] = []
            for hit in results.hits:
                images = [
                    ImageResult(**img_data)
                    for img_data in hit.get("images", [])[:5]
                    if isinstance(img_data, dict)
                ]
                score = hit.get("_rankingScore", 0.5)

                result = SearchResult(
                    id=hit.get("id", self._generate_id(hit.get("url", ""))),
                    title=hit.get("title", ""),
                    url=hit.get("url", ""),
                    excerpt=hit.get("excerpt", ""),
                    content=None,
                    site=hit.get("site"),
                    images=images,
                    lang=hit.get("lang"),
                    timestamp=hit.get("timestamp"),
                    indexed_at=hit.get("indexed_at"),
                    source=SearchSource.MEILISEARCH,
                    score=score,
                )
                search_results.append(result)

            logger.info(f"Meilisearch search for '{query}' (lang={lang}): {len(search_results)} results")
            return search_results

        except MeilisearchApiError as e:
            logger.error(f"Meilisearch API error: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"Meilisearch search error: {e}", exc_info=True)
            return []

    def _generate_id(self, url: str) -> str:
        """Generate a consistent unique ID from a URL."""
        return hashlib.md5(url.encode()).hexdigest()

    async def get_index_stats(self) -> dict:
        """Get statistics for the index."""
        if not self.index:
            return {}
        try:
            stats = await self.index.get_stats()
            return {
                "numberOfDocuments": stats.number_of_documents,
                "isIndexing": stats.is_indexing,
                "fieldDistribution": stats.field_distribution,
            }
        except Exception as e:
            logger.error(f"Failed to get index stats: {e}")
            return {}
