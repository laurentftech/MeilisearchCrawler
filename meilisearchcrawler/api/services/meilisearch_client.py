"""
Meilisearch client service for KidSearch API.
Handles search queries against local indexed content.
"""

import logging
import hashlib
from typing import List, Optional
import meilisearch
from meilisearch.errors import MeilisearchApiError

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

    def connect(self):
        """Connect to Meilisearch and get index."""
        try:
            self.client = meilisearch.Client(self.url, self.api_key)
            self.index = self.client.index(self.index_name)

            # Test connection
            self.client.health()
            logger.info(f"Connected to Meilisearch at {self.url}, index: {self.index_name}")

        except Exception as e:
            logger.error(f"Failed to connect to Meilisearch: {e}", exc_info=True)
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
