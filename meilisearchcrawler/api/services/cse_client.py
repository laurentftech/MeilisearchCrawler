"""
Google Custom Search Engine (CSE) client with SQLite caching.
Manages API calls, quota tracking, and result caching.
"""

import logging
import hashlib
import json
import time
import sqlite3
import os
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from pathlib import Path

import aiohttp
from pydantic import ValidationError

from ..models import SearchResult, SearchSource, ImageResult

logger = logging.getLogger(__name__)


class CSEClient:
    """
    Google Custom Search Engine client with caching.
    Reduces API quota usage and improves response times.
    """

    def __init__(
        self,
        api_key: str,
        search_engine_id: str,
        cache_db_path: str = "data/cse_cache.db",
        cache_days: int = 7,
        daily_quota: int = 100,
    ):
        """
        Initialize CSE client.

        Args:
            api_key: Google API key
            search_engine_id: CSE ID
            cache_db_path: Path to SQLite cache database
            cache_days: Days to cache results (default: 7)
            daily_quota: Daily API quota limit (default: 100 for free tier)
        """
        self.api_key = api_key
        self.search_engine_id = search_engine_id
        self.cache_db_path = cache_db_path
        self.cache_days = cache_days
        self.daily_quota = daily_quota

        self.base_url = "https://www.googleapis.com/customsearch/v1"

        # Initialize cache database
        self._init_cache_db()

    def _init_cache_db(self):
        """Initialize SQLite cache database."""
        # Ensure data directory exists
        Path(self.cache_db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        # Cache table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cse_cache (
                query_hash TEXT PRIMARY KEY,
                query TEXT NOT NULL,
                lang TEXT,
                results TEXT NOT NULL,
                cached_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)

        # Quota tracking table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cse_quota (
                date TEXT PRIMARY KEY,
                queries_used INTEGER NOT NULL DEFAULT 0
            )
        """)

        # Index for cleanup
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_expires_at
            ON cse_cache(expires_at)
        """)

        conn.commit()
        conn.close()

        logger.info(f"CSE cache database initialized: {self.cache_db_path}")

    async def search(
        self, query: str, lang: str = "fr", num_results: int = 10
    ) -> tuple[List[SearchResult], bool]:
        """
        Search using Google CSE with caching.

        Args:
            query: Search query
            lang: Language code (fr, en, etc.)
            num_results: Number of results to fetch (max 10 per request)

        Returns:
            Tuple of (results, cache_hit)
        """

        # Check cache first
        cached_results = self._get_cached_results(query, lang)
        if cached_results is not None:
            logger.info(f"CSE cache hit for query: '{query}'")
            return cached_results, True

        # Check quota
        if not self._check_quota():
            logger.warning("CSE daily quota exceeded, returning empty results")
            return [], False

        # Fetch from API
        try:
            results = await self._fetch_from_api(query, lang, num_results)

            # Cache results
            self._cache_results(query, lang, results)

            # Increment quota
            self._increment_quota()

            logger.info(f"CSE API called for query: '{query}', got {len(results)} results")

            return results, False

        except Exception as e:
            logger.error(f"CSE API error: {e}", exc_info=True)
            return [], False

    async def _fetch_from_api(
        self, query: str, lang: str, num_results: int
    ) -> List[SearchResult]:
        """
        Fetch results from Google CSE API.

        Args:
            query: Search query
            lang: Language code
            num_results: Number of results

        Returns:
            List of search results
        """

        params = {
            "key": self.api_key,
            "cx": self.search_engine_id,
            "q": query,
            "lr": f"lang_{lang}",  # Language restriction
            "num": min(num_results, 10),  # Max 10 per request
            "safe": "active",  # Safe search enabled
        }

        # Add Referer header to pass HTTP referrer restrictions
        headers = {
            "Referer": os.environ.get("FRONTEND_URL", ""),
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(self.base_url, params=params, headers=headers) as response:
                response.raise_for_status()
                data = await response.json()

        # Parse results
        results = []
        items = data.get("items", [])

        for item in items:
            # Generate unique ID
            result_id = hashlib.md5(item["link"].encode()).hexdigest()

            # Extract images if available, robustly handling validation errors
            images = []
            if "pagemap" in item and "cse_image" in item["pagemap"]:
                for img in item["pagemap"]["cse_image"][:5]:  # Max 5 images
                    try:
                        src = img.get("src")
                        if src:
                            images.append(
                                ImageResult(
                                    url=src,
                                    alt=None,
                                    description=None,
                                )
                            )
                    except ValidationError:
                        logger.warning(f"Skipping invalid image URL from CSE: {img.get('src')}")
                        continue

            result = SearchResult(
                id=result_id,
                title=item.get("title", ""),
                url=item["link"],
                excerpt=item.get("snippet", ""),
                content=None,  # CSE doesn't provide full content
                site=item.get("displayLink"),
                images=images,
                lang=lang,
                timestamp=None,
                indexed_at=None,
                source=SearchSource.GOOGLE_CSE,
                score=1.0,  # Will be adjusted by merger
            )

            results.append(result)

        return results

    def _get_cached_results(
        self, query: str, lang: str
    ) -> Optional[List[SearchResult]]:
        """Get cached results if available and not expired."""
        query_hash = self._hash_query(query, lang)
        now = int(time.time())

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            SELECT results FROM cse_cache
            WHERE query_hash = ? AND expires_at > ?
            """,
            (query_hash, now),
        )

        row = cursor.fetchone()
        conn.close()

        if row:
            # Deserialize results
            results_data = json.loads(row[0])
            return [SearchResult(**r) for r in results_data]

        return None

    def _cache_results(self, query: str, lang: str, results: List[SearchResult]):
        """Cache search results."""
        query_hash = self._hash_query(query, lang)
        now = int(time.time())
        expires_at = now + (self.cache_days * 86400)

        # Serialize results
        results_json = json.dumps([r.model_dump(mode="json") for r in results])

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT OR REPLACE INTO cse_cache
            (query_hash, query, lang, results, cached_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (query_hash, query, lang, results_json, now, expires_at),
        )

        conn.commit()
        conn.close()

    def _check_quota(self) -> bool:
        """Check if daily quota is available."""
        today = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT queries_used FROM cse_quota WHERE date = ?", (today,)
        )

        row = cursor.fetchone()
        conn.close()

        queries_used = row[0] if row else 0

        return queries_used < self.daily_quota

    def _increment_quota(self):
        """Increment daily quota usage."""
        today = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO cse_quota (date, queries_used)
            VALUES (?, 1)
            ON CONFLICT(date) DO UPDATE SET queries_used = queries_used + 1
            """,
            (today,),
        )

        conn.commit()
        conn.close()

    def get_quota_usage(self) -> Dict[str, int]:
        """Get current quota usage."""
        today = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute(
            "SELECT queries_used FROM cse_quota WHERE date = ?", (today,)
        )

        row = cursor.fetchone()
        conn.close()

        queries_used = row[0] if row else 0

        return {
            "used": queries_used,
            "limit": self.daily_quota,
            "remaining": self.daily_quota - queries_used,
        }

    def cleanup_expired_cache(self):
        """Remove expired cache entries."""
        now = int(time.time())

        conn = sqlite3.connect(self.cache_db_path)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM cse_cache WHERE expires_at < ?", (now,))
        deleted = cursor.rowcount

        conn.commit()
        conn.close()

        if deleted > 0:
            logger.info(f"Cleaned up {deleted} expired CSE cache entries")

    def _hash_query(self, query: str, lang: str) -> str:
        """Generate hash for query + lang combination."""
        return hashlib.md5(f"{query}|{lang}".encode()).hexdigest()
