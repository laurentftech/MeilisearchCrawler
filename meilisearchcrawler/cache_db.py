# meilisearchcrawler/cache_db.py
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, List
import hashlib


class CacheDB:
    def __init__(self, db_path: str = "data/crawler_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialise la base de données"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    url TEXT PRIMARY KEY,
                    content_hash TEXT NOT NULL,
                    doc_id TEXT NOT NULL,
                    last_crawl REAL NOT NULL,
                    crawl_date TEXT NOT NULL,
                    etag TEXT,
                    last_modified TEXT,
                    site_name TEXT,
                    indexed_at TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_sessions (
                    site_name TEXT PRIMARY KEY,
                    started TEXT NOT NULL,
                    completed INTEGER NOT NULL,
                    finished TEXT,
                    domain TEXT,
                    resume_urls TEXT
                )
            """)

            # Index pour les requêtes fréquentes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_site ON cache(site_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hash ON cache(content_hash)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_crawl ON cache(last_crawl)")

            conn.commit()

    def get(self, url: str) -> Optional[Dict]:
        """Récupère une entrée du cache"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM cache WHERE url = ?", (url,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_all_urls(self) -> List[Dict]:
        """Récupère toutes les entrées du cache (url, last_crawl, site_name)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT url, last_crawl, site_name FROM cache")
            rows = cursor.fetchall()
            return [dict(row) for row in rows] if rows else []

    def set(self, url: str, content_hash: str, doc_id: str,
            etag: str = None, last_modified: str = None, site_name: str = None):
        """Ajoute ou met à jour une entrée"""
        import time
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO cache 
                (url, content_hash, doc_id, last_crawl, crawl_date, etag, last_modified, site_name, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                url, content_hash, doc_id, time.time(),
                datetime.now().isoformat(), etag, last_modified,
                site_name, datetime.now().isoformat()
            ))
            conn.commit()

    def should_skip(self, url: str, content_hash: str, cache_days: int = 7) -> bool:
        """Vérifie si une page doit être ignorée"""
        import time
        cached = self.get(url)
        if not cached:
            return False

        if cached['content_hash'] == content_hash:
            days_ago = (time.time() - cached['last_crawl']) / (24 * 3600)
            return days_ago < cache_days
        return False

    def get_stats(self) -> Dict:
        """Statistiques du cache"""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]

            sites = conn.execute("""
                SELECT site_name, COUNT(*) as count 
                FROM cache 
                WHERE site_name IS NOT NULL
                GROUP BY site_name
            """).fetchall()

            oldest = conn.execute(
                "SELECT MIN(last_crawl) FROM cache"
            ).fetchone()[0]

            newest = conn.execute(
                "SELECT MAX(last_crawl) FROM cache"
            ).fetchone()[0]

            return {
                'total_urls': total,
                'sites': dict(sites) if sites else {},
                'oldest_crawl': oldest,
                'newest_crawl': newest
            }

    def clear_site(self, site_name: str):
        """Efface le cache d'un site"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE site_name = ?", (site_name,))
            conn.commit()

    def clear_all(self):
        """Efface tout le cache"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache")
            conn.execute("DELETE FROM crawl_sessions")
            conn.commit()

    # Sessions de crawl
    def start_session(self, site_name: str, domain: str):
        """Démarre une session de crawl"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO crawl_sessions 
                (site_name, started, completed, domain)
                VALUES (?, ?, 0, ?)
            """, (site_name, datetime.now().isoformat(), domain))
            conn.commit()

    def get_session(self, site_name: str) -> Optional[Dict]:
        """Récupère une session de crawl."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM crawl_sessions WHERE site_name = ?", (site_name,)
            )
            row = cursor.fetchone()
            if not row:
                return None
            
            session_data = dict(row)
            if session_data.get('resume_urls'):
                try:
                    # Les URLs sont stockées en JSON
                    resume_urls = json.loads(session_data['resume_urls'])
                    session_data['resume_urls'] = resume_urls
                except (json.JSONDecodeError, TypeError):
                    session_data['resume_urls'] = None
            return session_data

    def complete_session(self, site_name: str, completed: bool = True,
                         resume_urls: list = None):
        """Termine une session de crawl"""
        with sqlite3.connect(self.db_path) as conn:
            resume_json = json.dumps(resume_urls) if resume_urls else None
            conn.execute("""
                UPDATE crawl_sessions 
                SET completed = ?, finished = ?, resume_urls = ?
                WHERE site_name = ?
            """, (
                1 if completed else 0,
                datetime.now().isoformat(),
                resume_json,
                site_name
            ))
            conn.commit()