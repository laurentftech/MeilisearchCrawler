"""
Search results merger service.
Combines and deduplicates results from Meilisearch and Google CSE.
"""

import logging
from typing import List, Set, Tuple
from urllib.parse import urlparse

from ..models import SearchResult, SearchSource

logger = logging.getLogger(__name__)


class SearchMerger:
    """
    Merges search results from multiple sources.
    Handles deduplication, normalization, and initial scoring.
    """

    def __init__(self, meilisearch_weight: float = 0.7, cse_weight: float = 0.3):
        """
        Initialize merger with source weights.

        Args:
            meilisearch_weight: Weight for local Meilisearch results (default: 0.7)
            cse_weight: Weight for Google CSE results (default: 0.3)
        """
        self.meilisearch_weight = meilisearch_weight
        self.cse_weight = cse_weight

    def merge(
        self,
        meilisearch_results: List[SearchResult],
        cse_results: List[SearchResult],
        limit: int = 20,
    ) -> List[SearchResult]:
        """
        Merge results from Meilisearch and Google CSE.

        Process:
        1. Deduplicate by URL (normalize and compare)
        2. Apply source weights to scores
        3. Sort by weighted score
        4. Return top N results

        Args:
            meilisearch_results: Results from Meilisearch
            cse_results: Results from Google CSE
            limit: Maximum results to return

        Returns:
            Merged and deduplicated results
        """

        # Track seen URLs (normalized)
        seen_urls: Set[str] = set()
        merged: List[SearchResult] = []

        # Process Meilisearch results first (higher priority)
        for result in meilisearch_results:
            normalized_url = self._normalize_url(result.url)

            if normalized_url not in seen_urls:
                # Apply Meilisearch weight
                result.score = result.score * self.meilisearch_weight
                merged.append(result)
                seen_urls.add(normalized_url)

        # Process CSE results (deduplicate against Meilisearch)
        for result in cse_results:
            normalized_url = self._normalize_url(result.url)

            if normalized_url not in seen_urls:
                # Apply CSE weight
                result.score = result.score * self.cse_weight
                result.source = SearchSource.GOOGLE_CSE
                merged.append(result)
                seen_urls.add(normalized_url)
            else:
                # URL already in Meilisearch results
                logger.debug(f"Duplicate URL filtered: {result.url}")

        # Sort by score (descending)
        merged.sort(key=lambda r: r.score, reverse=True)

        # Limit results
        merged = merged[:limit]

        logger.info(
            f"Merged {len(meilisearch_results)} Meilisearch + "
            f"{len(cse_results)} CSE results into {len(merged)} unique results"
        )

        return merged

    def _normalize_url(self, url: str) -> str:
        """
        Normalize URL for deduplication.

        Removes:
        - Trailing slashes
        - www. prefix
        - URL fragments (#...)
        - Query parameters (optional, configurable)

        Args:
            url: URL to normalize

        Returns:
            Normalized URL
        """
        parsed = urlparse(str(url))

        # Remove www. prefix
        netloc = parsed.netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        # Remove trailing slash from path
        path = parsed.path.rstrip("/")

        # Reconstruct without fragment
        normalized = f"{parsed.scheme}://{netloc}{path}"

        # Include query params (important for distinguishing pages)
        if parsed.query:
            normalized += f"?{parsed.query}"

        return normalized


# TODO: Implement weighted scoring strategies
# - Recency bonus (newer content ranked higher)
# - Domain authority (trusted domains ranked higher)
# - Content length bonus
# - Image presence bonus (for children-friendly visual results)
