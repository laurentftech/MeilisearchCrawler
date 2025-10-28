"""
Statistics database service for API monitoring.
Tracks search queries, performance metrics, and user feedback.
"""

import logging
import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class StatsDatabase:
    """
    SQLite database for storing API statistics.
    """

    def __init__(self, db_path: str = "data/api_stats.db"):
        """
        Initialize stats database.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self._init_database()

    def _init_database(self):
        """Initialize database schema."""
        # Ensure data directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Search queries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS search_queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                lang TEXT,
                limit_requested INTEGER,
                use_cse BOOLEAN,
                use_reranking BOOLEAN,
                use_hybrid BOOLEAN,
                total_results INTEGER,
                meilisearch_results INTEGER,
                cse_results INTEGER,
                wiki_results INTEGER,
                processing_time_ms REAL,
                meilisearch_time_ms REAL,
                cse_time_ms REAL,
                wiki_time_ms REAL,
                reranking_time_ms REAL,
                reranking_applied BOOLEAN,
                cache_hit BOOLEAN,
                timestamp INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Create index on timestamp for fast queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_queries_timestamp
            ON search_queries(timestamp)
        """)

        # Create index on query for top queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_search_queries_query
            ON search_queries(query)
        """)

        # Feedback table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                result_id TEXT NOT NULL,
                result_url TEXT NOT NULL,
                reason TEXT NOT NULL,
                comment TEXT,
                timestamp INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Create index on timestamp
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_feedback_timestamp
            ON feedback(timestamp)
        """)

        # --- Migration: Add new columns if they are missing ---
        try:
            cursor.execute("PRAGMA table_info(search_queries)")
            columns = [column[1] for column in cursor.fetchall()]

            if 'use_hybrid' not in columns:
                logger.info("Updating stats.db schema: adding 'use_hybrid' column")
                cursor.execute("ALTER TABLE search_queries ADD COLUMN use_hybrid BOOLEAN")

            if 'use_reranking' not in columns:
                logger.info("Updating stats.db schema: adding 'use_reranking' column")
                cursor.execute("ALTER TABLE search_queries ADD COLUMN use_reranking BOOLEAN")
            
            if 'wiki_results' not in columns:
                logger.info("Updating stats.db schema: adding 'wiki_results' column")
                cursor.execute("ALTER TABLE search_queries ADD COLUMN wiki_results INTEGER")

            if 'wiki_time_ms' not in columns:
                logger.info("Updating stats.db schema: adding 'wiki_time_ms' column")
                cursor.execute("ALTER TABLE search_queries ADD COLUMN wiki_time_ms REAL")


        except Exception as e:
            logger.error(f"Failed to migrate stats_db schema: {e}")

        conn.commit()
        conn.close()

        logger.info(f"Stats database initialized: {self.db_path}")

    def log_search(
        self,
        query: str,
        lang: str,
        limit: int,
        use_cse: bool,
        use_reranking: bool,
        use_hybrid: bool,
        stats: Dict[str, Any],
    ):
        """
        Log a search query.

        Args:
            query: Search query
            lang: Language
            limit: Limit requested
            use_cse: Whether CSE was used
            use_reranking: Whether reranking was used
            use_hybrid: Whether hybrid search was used
            stats: Search statistics dict
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.utcnow()
            timestamp = int(now.timestamp())

            cursor.execute("""
                INSERT INTO search_queries (
                    query, lang, limit_requested, use_cse, use_reranking, use_hybrid,
                    total_results, meilisearch_results, cse_results, wiki_results,
                    processing_time_ms, meilisearch_time_ms, cse_time_ms, wiki_time_ms,
                    reranking_time_ms, reranking_applied, cache_hit,
                    timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                query, lang, limit, use_cse, use_reranking, use_hybrid,
                stats.get("total_results", 0),
                stats.get("meilisearch_results", 0),
                stats.get("cse_results", 0),
                stats.get("wiki_results", 0),
                stats.get("processing_time_ms", 0),
                stats.get("meilisearch_time_ms"),
                stats.get("cse_time_ms"),
                stats.get("wiki_time_ms"),
                stats.get("reranking_time_ms"),
                stats.get("reranking_applied", False),
                stats.get("cache_hit", False),
                timestamp,
                now.isoformat(),
            ))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Failed to log search: {e}", exc_info=True)

    def log_feedback(
        self,
        query: str,
        result_id: str,
        result_url: str,
        reason: str,
        comment: Optional[str] = None,
    ):
        """
        Log user feedback.

        Args:
            query: Original search query
            result_id: Result ID
            result_url: Result URL
            reason: Feedback reason
            comment: Optional comment
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            now = datetime.utcnow()
            timestamp = int(now.timestamp())

            cursor.execute("""
                INSERT INTO feedback (
                    query, result_id, result_url, reason, comment,
                    timestamp, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (query, result_id, result_url, reason, comment, timestamp, now.isoformat()))

            conn.commit()
            conn.close()

        except Exception as e:
            logger.error(f"Failed to log feedback: {e}", exc_info=True)

    def get_total_searches(self) -> int:
        """Get total number of searches."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM search_queries")
            count = cursor.fetchone()[0]

            conn.close()
            return count

        except Exception as e:
            logger.error(f"Failed to get total searches: {e}")
            return 0

    def get_searches_last_hour(self) -> int:
        """Get number of searches in last hour."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            one_hour_ago = int((datetime.utcnow() - timedelta(hours=1)).timestamp())

            cursor.execute(
                "SELECT COUNT(*) FROM search_queries WHERE timestamp > ?",
                (one_hour_ago,)
            )
            count = cursor.fetchone()[0]

            conn.close()
            return count

        except Exception as e:
            logger.error(f"Failed to get searches last hour: {e}")
            return 0

    def get_avg_search_time(self) -> float:
        """Get average search time in ms."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT AVG(processing_time_ms) FROM search_queries")
            avg = cursor.fetchone()[0]

            conn.close()
            return avg or 0.0

        except Exception as e:
            logger.error(f"Failed to get avg response time: {e}")
            return 0.0

    def get_avg_meilisearch_time(self) -> float:
        """Get average Meilisearch query time in ms."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(meilisearch_time_ms) FROM search_queries WHERE meilisearch_time_ms IS NOT NULL")
            avg = cursor.fetchone()[0]
            conn.close()
            return avg or 0.0
        except Exception as e:
            logger.error(f"Failed to get avg meilisearch time: {e}")
            return 0.0

    def get_avg_cse_time(self) -> float:
        """Get average CSE query time in ms."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(cse_time_ms) FROM search_queries WHERE cse_time_ms IS NOT NULL")
            avg = cursor.fetchone()[0]
            conn.close()
            return avg or 0.0
        except Exception as e:
            logger.error(f"Failed to get avg cse time: {e}")
            return 0.0
            
    def get_avg_wiki_time(self) -> float:
        """Get average MediaWiki query time in ms."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(wiki_time_ms) FROM search_queries WHERE wiki_time_ms IS NOT NULL")
            avg = cursor.fetchone()[0]
            conn.close()
            return avg or 0.0
        except Exception as e:
            logger.error(f"Failed to get avg wiki time: {e}")
            return 0.0

    def get_avg_reranking_time(self) -> float:
        """Get average reranking time in ms."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("SELECT AVG(reranking_time_ms) FROM search_queries WHERE reranking_time_ms IS NOT NULL")
            avg = cursor.fetchone()[0]
            conn.close()
            return avg or 0.0
        except Exception as e:
            logger.error(f"Failed to get avg reranking time: {e}")
            return 0.0

    def get_cache_hit_rate(self) -> float:
        """Get CSE cache hit rate (0-1)."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Count queries with CSE results
            cursor.execute("SELECT COUNT(*) FROM search_queries WHERE cse_results > 0")
            total_cse = cursor.fetchone()[0]

            if total_cse == 0:
                conn.close()
                return 0.0

            # Count cache hits
            cursor.execute(
                "SELECT COUNT(*) FROM search_queries WHERE cse_results > 0 AND cache_hit = 1"
            )
            cache_hits = cursor.fetchone()[0]

            conn.close()
            return cache_hits / total_cse

        except Exception as e:
            logger.error(f"Failed to get cache hit rate: {e}")
            return 0.0

    def get_top_queries(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get most popular queries.

        Args:
            limit: Number of top queries to return

        Returns:
            List of {query, count} dicts
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT query, COUNT(*) as count
                FROM search_queries
                GROUP BY query
                ORDER BY count DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            return [{"query": row[0], "count": row[1]} for row in rows]

        except Exception as e:
            logger.error(f"Failed to get top queries: {e}")
            return []

    def get_error_rate(self) -> float:
        """
        Get error rate (0-1).
        Defined as searches with 0 results / total searches.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM search_queries")
            total = cursor.fetchone()[0]

            if total == 0:
                conn.close()
                return 0.0

            cursor.execute("SELECT COUNT(*) FROM search_queries WHERE total_results = 0")
            errors = cursor.fetchone()[0]

            conn.close()
            return errors / total

        except Exception as e:
            logger.error(f"Failed to get error rate: {e}")
            return 0.0

    def cleanup_old_stats(self, days: int = 30):
        """
        Delete stats older than specified days.

        Args:
            days: Keep stats from last N days
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cutoff = int((datetime.utcnow() - timedelta(days=days)).timestamp())

            cursor.execute("DELETE FROM search_queries WHERE timestamp < ?", (cutoff,))
            deleted_searches = cursor.rowcount

            cursor.execute("DELETE FROM feedback WHERE timestamp < ?", (cutoff,))
            deleted_feedback = cursor.rowcount

            conn.commit()
            conn.close()

            logger.info(
                f"Cleaned up old stats: {deleted_searches} searches, "
                f"{deleted_feedback} feedback entries"
            )

        except Exception as e:
            logger.error(f"Failed to cleanup old stats: {e}")

    def reset_stats(self):
        """Reset all statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("DELETE FROM search_queries")
            deleted_searches = cursor.rowcount

            cursor.execute("DELETE FROM feedback")
            deleted_feedback = cursor.rowcount

            conn.commit()
            conn.close()

            logger.info(
                f"Reset stats: {deleted_searches} searches, "
                f"{deleted_feedback} feedback entries deleted"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to reset stats: {e}")
            return False
