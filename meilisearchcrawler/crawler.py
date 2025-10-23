# ---------------------------
# KidSearch Crawler - Version Complète avec Indexation Progressive
# ---------------------------
import yaml
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import time
import logging
from urllib.parse import urljoin, urlparse
import hashlib
from urllib.robotparser import RobotFileParser
import json
import os
import re
from datetime import datetime
import sys
from dotenv import load_dotenv
from typing import Dict, List, Optional, Set, Tuple
import ssl
import argparse
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from tqdm.asyncio import tqdm
from tqdm import tqdm as tqdm_sync
import trafilatura
import certifi
import signal

# New SDK Imports
from meilisearch_python_sdk import AsyncClient
from meilisearch_python_sdk.errors import MeilisearchApiError, MeilisearchCommunicationError
from meilisearch_python_sdk.models.task import TaskInfo

from meilisearchcrawler.cache_db import CacheDB
from meilisearchcrawler.embeddings import create_embedding_provider, EmbeddingProvider

# ---------------------------
# Project Structure Setup
# ---------------------------
def get_project_root():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PROJECT_ROOT = get_project_root()
DATA_DIR = os.path.join(PROJECT_ROOT, 'data')
LOGS_DIR = os.path.join(DATA_DIR, 'logs')
CONFIG_DIR = os.path.join(PROJECT_ROOT, 'config')

os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

LOG_FILE_PATH = os.path.join(LOGS_DIR, 'crawler.log')
load_dotenv(os.path.join(PROJECT_ROOT, '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# --- SSL Context Patch for urllib ---
try:
    import urllib.request
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    https_handler = urllib.request.HTTPSHandler(context=ssl_context)
    opener = urllib.request.build_opener(https_handler)
    urllib.request.install_opener(opener)
    logger.info("✓ Contexte SSL patché pour urllib (robots.txt)")
except Exception as e:
    logger.warning(f"⚠️  Impossible de patcher le contexte SSL pour urllib: {e}")

# ---------------------------
# Configuration
# ---------------------------
class Config:
    USER_AGENT = os.getenv('USER_AGENT', 'KidSearch-Crawler/2.0 (+https://github.com/laurentftech/MeilisearchCrawler)')
    MEILI_URL = os.getenv("MEILI_URL")
    MEILI_KEY = os.getenv("MEILI_KEY")
    INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    TIMEOUT = int(os.getenv('TIMEOUT', 15))
    DEFAULT_DELAY = float(os.getenv('DEFAULT_DELAY', 0.5))
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 20))
    INDEXING_BATCH_SIZE = int(os.getenv('INDEXING_BATCH_SIZE', 100))
    CACHE_DAYS = int(os.getenv('CACHE_DAYS', 7))
    CONCURRENT_REQUESTS = int(os.getenv('CONCURRENT_REQUESTS', 5))
    MAX_CONNECTIONS = int(os.getenv('MAX_CONNECTIONS', 100))
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
    EMBEDDING_DIMENSIONS = int(os.getenv("EMBEDDING_DIMENSIONS", 768))
    GEMINI_EMBEDDING_BATCH_SIZE = int(os.getenv("GEMINI_EMBEDDING_BATCH_SIZE", 100))
    MAX_CRAWL_DURATION = int(os.getenv('MAX_CRAWL_DURATION', 3600))
    MAX_QUEUE_SIZE = int(os.getenv('MAX_QUEUE_SIZE', 50000))
    MAX_WORKERS = int(os.getenv('MAX_WORKERS', 20))
    # Patterns to exclude globally from all crawls
    GLOBAL_EXCLUDE_PATTERNS = [
        # Generic
        '/login', '/logout', '/signin', '/signup', '/register',
        '/cart', '/checkout', '/account', '/share', '/print', '/cdn-cgi/',
        # WordPress
        '/wp-admin/', '/wp-json/', '/wp-login.php', '/wp-cron.php',
        'xmlrpc.php', '?rest_route=', '?preview=', '/feed/',
    ]

config = Config()

if not config.MEILI_URL or not config.MEILI_KEY:
    logger.error("❌ Les variables d'environnement MEILI_URL et MEILI_KEY doivent être définies.")
    exit(1)

# Global embedding provider (initialized in main_async)
embedding_provider: Optional[EmbeddingProvider] = None

# ---------------------------
# Shutdown Handler
# ---------------------------
class ShutdownHandler:
    def __init__(self):
        self.shutdown_requested = False
        signal.signal(signal.SIGINT, self._handle_signal)
        signal.signal(signal.SIGTERM, self._handle_signal)

    def _handle_signal(self, signum, frame):
        sig_name = 'SIGINT' if signum == signal.SIGINT else 'SIGTERM'
        logger.warning(f"\n⚠️  Signal {sig_name} reçu - arrêt gracieux en cours...")
        self.shutdown_requested = True

    def should_stop(self) -> bool:
        return self.shutdown_requested

shutdown_handler = ShutdownHandler()

# ---------------------------
# MeiliSearch & Cache Setup
# ---------------------------
cache_db = CacheDB()
logger.info("✅ Cache SQLite initialisé")

async def update_meilisearch_settings(index, with_embeddings=False):
    logger.info("⚙️ Mise à jour des paramètres MeiliSearch...")
    settings = {
        'searchable_attributes': ['title', 'excerpt', 'content', 'site', 'images.alt'],
        'displayed_attributes': [
            'title', 'url', 'site', 'images', 'timestamp', 'excerpt',
            'content', 'lang', 'indexed_at', 'last_crawled_at', 'content_hash'
        ],
        'filterable_attributes': ['site', 'timestamp', 'lang', 'indexed_at', 'last_crawled_at', 'title', 'content', 'embedding_provider', 'embedding_model', 'embedding_dimensions'],
        'sortable_attributes': ['timestamp', 'indexed_at', 'last_crawled_at'],
        'ranking_rules': ['words', 'typo', 'proximity', 'attribute', 'sort', 'exactness']
    }

    if with_embeddings:
        # Use provider's dimension if available, fallback to config
        embedding_dim = config.EMBEDDING_DIMENSIONS
        if embedding_provider and embedding_provider.get_embedding_dim() > 0:
            embedding_dim = embedding_provider.get_embedding_dim()

        logger.info(f"   -> Activation du support des embeddings (vector search, {embedding_dim}D)")
        settings['embedders'] = {
            "default": {
                "source": "userProvided",
                "dimensions": embedding_dim
            }
        }

    try:
        task: TaskInfo = await index.update_settings(settings)
        logger.info(f"   ✓ Paramètres mis à jour (task uid: {task.task_uid})")
    except Exception as e:
        logger.error(f"❌ Échec mise à jour paramètres: {e}")

# ---------------------------
# Load sites.yml
# ---------------------------
try:
    with open(os.path.join(CONFIG_DIR, "sites.yml"), "r", encoding='utf-8') as f:
        sites_data = yaml.safe_load(f)
        sites = sites_data.get("sites", sites_data)
    logger.info(f"📋 {len(sites)} site(s) chargé(s) depuis sites.yml")
except FileNotFoundError:
    logger.error(f"❌ Fichier {os.path.join(CONFIG_DIR, 'sites.yml')} introuvable")
    exit(1)
except Exception as e:
    logger.error(f"❌ Erreur lecture sites.yml: {e}")
    exit(1)

# ---------------------------
# Cache (via CacheDB)
# ---------------------------
def start_crawl_session(site_name: str, domain: str):
    cache_db.start_session(site_name, domain)

def complete_crawl_session(site_name: str, completed: bool = True, resume_urls: Optional[Set[str]] = None):
    resume_list = list(resume_urls) if resume_urls else None
    cache_db.complete_session(site_name, completed, resume_list)

def get_content_hash(content: str, title: str, images: List, excerpt: str) -> str:
    images_str = json.dumps(images, sort_keys=True)
    content_str = f"{title}|{excerpt}|{content}|{images_str}"
    return hashlib.md5(content_str.encode()).hexdigest()

def should_skip_page(url: str, content_hash: str) -> bool:
    return cache_db.should_skip(url, content_hash, config.CACHE_DAYS)

def update_cache(url: str, content_hash: str, doc_id: str, site_name: str, etag: str = None, last_modified: str = None):
    cache_db.set(url, content_hash, doc_id, etag=etag, last_modified=last_modified, site_name=site_name)

# ---------------------------
# Robots.txt
# ---------------------------
robot_parsers: Dict[str, RobotFileParser] = {}

def get_robot_parser(url: str) -> Optional[RobotFileParser]:
    parsed_url = urlparse(url)
    domain = parsed_url.netloc
    if domain in robot_parsers:
        return robot_parsers[domain]
    robots_url = f"{parsed_url.scheme}://{domain}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        parser.read()
        robot_parsers[domain] = parser
        return parser
    except Exception as e:
        logger.warning(f"⚠️ Impossible de lire robots.txt pour {domain}: {e}")
        parser.allow_all = True
        robot_parsers[domain] = parser
        return parser

def get_crawl_delay(url: str) -> float:
    parser = get_robot_parser(url)
    if parser:
        delay = parser.crawl_delay(config.USER_AGENT)
        if delay:
            return float(delay)
    return config.DEFAULT_DELAY

# ---------------------------
# Utilities
# ---------------------------
def get_nested_value(data, key_path: str):
    if not isinstance(data, (dict, list)) or not key_path:
        return None
    keys = key_path.replace('[]', '.[]').split('.')
    current = data
    for i, key in enumerate(keys):
        if current is None:
            return None
        if key == '[]':
            if not isinstance(current, list):
                return None
            remaining_path = '.'.join(keys[i + 1:])
            if not remaining_path:
                return current
            results = []
            for item in current:
                res = get_nested_value(item, remaining_path)
                if res:
                    results.extend(res if isinstance(res, list) else [res])
            return results
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current

def generate_doc_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def normalize_url(url: str) -> str:
    url = url.split('#')[0]
    url = url.rstrip('/')
    return url

def is_same_domain(url1: str, url2: str) -> bool:
    return urlparse(url1).netloc == urlparse(url2).netloc

def is_excluded(url: str, patterns: List[str]) -> bool:
    if not patterns:
        return False
    return any(pattern in url for pattern in patterns)

def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ['http', 'https']:
            return False
        if parsed.netloc in ['localhost', '127.0.0.1', '0.0.0.0']:
            return False
        return True
    except Exception:
        return False

def remove_common_patterns(text: str) -> str:
    patterns_to_remove = [
        r'Partager\s*:.*?(?=\n\n|\Z)',
        r'Publications similaires.*?(?=\n\n|\Z)',
        r'En tant qu\'adhérent.*?(?=\n\n|\Z)',
        r'J\'accède aux.*?(?=\n\n|\Z)',
        r'Suivez-nous sur.*?(?=\n\n|\Z)',
        r'Abonnez-vous.*?(?=\n\n|\Z)',
        r'Rejoignez-nous.*?(?=\n\n|\Z)',
        r'Inscrivez-vous.*?(?=\n\n|\Z)',
        r'Cookies?\s+policy.*?(?=\n\n|\Z)',
        r'Privacy\s+policy.*?(?=\n\n|\Z)',
    ]
    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    return text.strip()

def extract_main_content(soup: BeautifulSoup, html_string: str, site_config: Dict) -> str:
    site_selector = site_config.get('selector')
    if site_selector:
        content_element = soup.select_one(site_selector)
        if content_element:
            return content_element.get_text(separator=' ', strip=True)
    extracted_text = trafilatura.extract(html_string, include_comments=False, include_tables=False)
    if extracted_text and len(extracted_text) > 250:
        return extracted_text
    logger.debug("   (Fallback sur l'heuristique maison)")
    best_candidate = None
    best_candidate_len = 0
    for selector in ['article', 'main', '[role="main"]', '.post-content', '.entry-content', '.article-content', '.content-main', '.main-content', '#content', '.content', '.mw-parser-output']:
        content_elem = soup.select_one(selector)
        if content_elem:
            temp_elem = BeautifulSoup(str(content_elem), 'lxml')
            current_len = len(temp_elem.get_text(strip=True))
            if current_len > best_candidate_len:
                best_candidate = content_elem
                best_candidate_len = current_len
    if not best_candidate or best_candidate_len < 250:
        if soup.body:
            all_elements = soup.body.find_all(True, recursive=True)
            max_len = 0
            best_elem = soup.body
            for elem in all_elements:
                if elem.name in ['nav', 'header', 'footer', 'aside', 'script', 'style', 'a', 'form']:
                    continue
                text_len = len(elem.get_text(strip=True))
                if text_len > max_len:
                    max_len = text_len
                    best_elem = elem
            target_element = best_elem
        else:
            return ""
    else:
        target_element = best_candidate
    for tag in target_element.select('nav, header, footer, aside, form, script, style, iframe, .sidebar, .widget, .social-share, .related-posts, .comments, .comment, .advertisement, .ad, .ads, [class*="share"], [class*="related"], [class*="sidebar"], [class*="widget"], [class*="promo"], [class*="cookie"], [aria-hidden="true"]'):
        tag.decompose()
    return target_element.get_text(separator=' ', strip=True)

def get_title(soup: BeautifulSoup) -> str:
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        return og_title['content'].strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find('h1')
    return h1.get_text(strip=True) if h1 else "Sans titre"

def create_excerpt(content: str, max_length: int = 250) -> str:
    if not content:
        return ""
    sentences = re.split(r'(?<=[.!?])\s+', content)
    excerpt = ""
    for sentence in sentences:
        if len(sentence.strip()) < 20:
            continue
        if len(excerpt) + len(sentence) <= max_length:
            excerpt += sentence + " "
        else:
            break
    if not excerpt.strip():
        excerpt = content[:max_length]
    excerpt = excerpt.strip()
    if len(content) > len(excerpt):
        excerpt = excerpt.rstrip('.!?') + '...'
    return excerpt

def clean_text(text: str, max_length: int = 3000) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\r\n\t]', ' ', text)
    text = remove_common_patterns(text)
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    return text.strip()[:max_length]

def extract_images(soup: BeautifulSoup, base_url: str, max_images: int = 5) -> List[Dict]:
    images = []
    seen_urls: Set[str] = set()
    for img in soup.select('img'):
        if len(images) >= max_images:
            break
        src = img.get('src') or img.get('data-src') or img.get('data-lazy-src')
        alt = img.get('alt', '').strip()
        if not src:
            continue
        width = img.get('width')
        height = img.get('height')
        if width and height:
            try:
                if int(width) < 100 or int(height) < 100:
                    continue
            except (ValueError, TypeError):
                pass
        full_url = urljoin(base_url, src)
        if not is_valid_url(full_url):
            continue
        if full_url not in seen_urls:
            images.append({'url': full_url, 'alt': alt or 'Image', 'description': alt or 'Image'})
            seen_urls.add(full_url)
    return images

# ---------------------------
# Embeddings (Multi-Provider)
# ---------------------------
def get_embeddings_batch(texts: List[str]) -> Optional[List[List[float]]]:
    """Generate embeddings using the configured provider"""
    if not embedding_provider or embedding_provider.get_embedding_dim() == 0:
        return None
    try:
        embeddings = embedding_provider.encode(texts)
        # Filter out empty embeddings
        return [emb if emb and len(emb) > 0 else None for emb in embeddings]
    except Exception as e:
        logger.error(f"Erreur génération embeddings: {e}")
        return None

# ---------------------------
# Progressive Indexing
# ---------------------------
async def index_documents_batch(index, documents: List[Dict], stats=None):
    if not documents:
        return
    logger.info(f"📦 Indexation de {len(documents)} documents...")

    # Generate embeddings if provider is configured
    if embedding_provider and embedding_provider.get_embedding_dim() > 0:
        logger.debug(f"   -> Génération de {len(documents)} embeddings ({embedding_provider.get_provider_name()})...")
        all_embeddings = []
        texts_to_embed = [f"{doc.get('title', '')}\n{doc.get('content', '')}".strip() for doc in documents]

        # Use provider-specific batch size or fallback to GEMINI_EMBEDDING_BATCH_SIZE
        batch_size = config.GEMINI_EMBEDDING_BATCH_SIZE

        for i in range(0, len(texts_to_embed), batch_size):
            batch_texts = texts_to_embed[i:i + batch_size]
            batch_embeddings = get_embeddings_batch(batch_texts)
            if batch_embeddings:
                all_embeddings.extend(batch_embeddings)
            else:
                all_embeddings.extend([None] * len(batch_texts))

        if len(all_embeddings) == len(documents):
            provider_name = embedding_provider.get_provider_name()
            model_name = embedding_provider.get_model_name()
            embedding_dim = embedding_provider.get_embedding_dim()

            for doc, embedding in zip(documents, all_embeddings):
                if embedding and len(embedding) == embedding_dim:
                    doc["_vectors"] = {"default": embedding}
                    doc["embedding_provider"] = provider_name
                    doc["embedding_model"] = model_name
                    doc["embedding_dimensions"] = len(embedding)

    try:
        await index.add_documents(documents)
        logger.debug(f"   ✓ {len(documents)} documents indexés")
    except Exception as e:
        logger.error(f"❌ Erreur indexation: {e}")
        if stats:
            await stats.increment('errors', len(documents))

# ---------------------------
# Stats
# ---------------------------
class CrawlStats:
    def __init__(self, site_name: str):
        self.site_name = site_name
        self.start_time = time.time()
        self.pages_visited = 0
        self.pages_indexed = 0
        self.pages_not_indexed = 0
        self.pages_skipped_cache = 0
        self.pages_not_modified = 0
        self.discovered_but_not_visited = 0
        self.errors = 0
        self.redirects = 0
        self.lock = asyncio.Lock()
        self.pbar = None

    async def increment(self, attr: str, value: int = 1):
        async with self.lock:
            setattr(self, attr, getattr(self, attr) + value)
            if self.pbar and attr == 'pages_visited':
                self.pbar.update(value)
            if self.pbar:
                self.pbar.set_postfix({
                    'indexées': self.pages_indexed,
                    'non-indexées': self.pages_not_indexed,
                    'ignorées(cache)': self.pages_skipped_cache,
                    'non-modifiées': self.pages_not_modified,
                    'erreurs': self.errors
                })

    def log_summary(self):
        duration = time.time() - self.start_time
        logger.info(f"\n{'=' * 60}")
        logger.info(f"📊 Résumé du crawl pour '{self.site_name}'")
        logger.info(f"{'=' * 60}")
        logger.info(f"⏱️  Durée: {duration:.2f}s")
        logger.info(f"🌐 Pages visitées: {self.pages_visited}")
        logger.info(f"✅ Pages indexées: {self.pages_indexed}")
        logger.info(f"⏭️  Pages non indexées: {self.pages_not_indexed}")
        logger.info(f"🗂️  Pages ignorées (cache): {self.pages_skipped_cache}")
        logger.info(f"♻️  Pages non modifiées (304): {self.pages_not_modified}")
        logger.info(f"🗺️  Liens découverts: {self.discovered_but_not_visited}")
        logger.info(f"❌ Erreurs: {self.errors}")
        if self.pages_visited > 0:
            logger.info(f"⚡ Vitesse: {self.pages_visited / duration:.2f} pages/s")
        logger.info(f"{'=' * 60}\n")

STATUS_FILE = os.path.join(DATA_DIR, "status.json")

class GlobalCrawlStatus:
    def __init__(self, total_sites: int):
        self.running = False
        self.start_time = None
        self.end_time = None
        self.total_sites = total_sites
        self.sites_crawled = 0
        self.active_site = None
        self.pages_indexed = 0
        self.errors = 0
        self.stats_by_site = []

    def to_dict(self) -> Dict:
        duration = 0
        if self.start_time and self.end_time:
            duration = self.end_time - self.start_time
        elif self.start_time:
            duration = time.time() - self.start_time
        return {
            "running": self.running,
            "timestamp": datetime.now().isoformat(),
            "total_sites": self.total_sites,
            "sites_crawled": self.sites_crawled,
            "active_site": self.active_site,
            "pages_indexed": self.pages_indexed,
            "errors": self.errors,
            "last_crawl_duration_sec": round(duration, 2),
            "stats": self.stats_by_site,
            "queue_length": 0
        }

    def save(self):
        try:
            with open(STATUS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.error(f"❌ Échec sauvegarde statut: {e}")

    def start(self):
        self.running = True
        self.start_time = time.time()
        self.save()

    def stop(self):
        self.running = False
        self.end_time = time.time()
        self.active_site = None
        self.save()

    def start_site(self, site_name: str):
        self.active_site = site_name
        self.save()

    def finish_site(self, site_stats: CrawlStats):
        self.sites_crawled += 1
        self.pages_indexed += site_stats.pages_indexed
        self.errors += site_stats.errors
        self.stats_by_site.append({
            "site": site_stats.site_name,
            "status": "✅ Terminé",
            "pages": site_stats.pages_indexed,
            "errors": site_stats.errors,
            "duration": round(time.time() - site_stats.start_time, 2)
        })
        self.active_site = None
        self.save()

class CrawlContext:
    def __init__(self, site: Dict, force_recrawl: bool):
        self.site = site
        self.force_recrawl = force_recrawl
        self.processed_hashes: Set[str] = set()
        self.stats = CrawlStats(site['name'])
        custom_delay = site.get('delay')
        if custom_delay is not None:
            logger.info(f"   -> Délai personnalisé appliqué: {custom_delay}s")
        self.rate_limiter = RateLimiter(custom_delay if custom_delay is not None else get_crawl_delay(site["crawl"]))
        self.exclude_patterns = config.GLOBAL_EXCLUDE_PATTERNS + site.get("exclude", [])
        self.no_index_patterns = site.get("no_index", [])
        self.max_depth = site.get("depth", 3)

class RateLimiter:
    def __init__(self, delay: float):
        self.delay = delay
        self.last_request = 0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.time()
            time_since_last = now - self.last_request
            if time_since_last < self.delay:
                await asyncio.sleep(self.delay - time_since_last)
            self.last_request = time.time()

async def fetch_page(session: ClientSession, url: str, rate_limiter: RateLimiter) -> Optional[Tuple[str, str, Dict]]:
    await rate_limiter.wait()
    headers = {}
    cached_data = cache_db.get(url)
    if cached_data:
        if cached_data.get('etag'):
            headers['If-None-Match'] = cached_data['etag']
        if cached_data.get('last_modified'):
            headers['If-Modified-Since'] = cached_data['last_modified']
    for attempt in range(config.MAX_RETRIES):
        try:
            async with session.get(url, headers=headers) as response:
                if response.status == 304:
                    return (url, None, {'status': 304, 'etag': None, 'last_modified': None})
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type.lower():
                    logger.debug(f"   ↪️ Ignoré (type non-HTML: {content_type}): {url}")
                    return (url, None, {'status': 'skipped_content_type'})
                response.raise_for_status()
                text = await response.text()
                etag = response.headers.get('ETag')
                last_modified = response.headers.get('Last-Modified')
                return (str(response.url), text, {'status': response.status, 'etag': etag, 'last_modified': last_modified})
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout {attempt + 1}/{config.MAX_RETRIES} pour {url}")
        except Exception as e:
            logger.warning(f"⚠️ Tentative {attempt + 1}/{config.MAX_RETRIES} échouée pour {url}: {e}")
        if attempt + 1 < config.MAX_RETRIES:
            await asyncio.sleep(2 ** attempt)
    return None

async def process_page(session: ClientSession, url: str, context: CrawlContext, current_depth: int = 0) -> Tuple[Optional[Dict], List[Tuple[str, int]]]:
    result = await fetch_page(session, url, context.rate_limiter)
    if not result:
        await context.stats.increment('errors')
        return None, []
    final_url, html, metadata = result
    if metadata['status'] == 304:
        await context.stats.increment('pages_not_modified')
        await context.stats.increment('pages_visited')
        doc_id = generate_doc_id(final_url)
        refresh_doc = {"id": doc_id, "last_crawled_at": datetime.now().isoformat()}
        return refresh_doc, []
    if metadata['status'] == 'skipped_content_type':
        await context.stats.increment('pages_visited')
        await context.stats.increment('pages_not_indexed')
        return None, []
    await context.stats.increment('pages_visited')
    if final_url != url:
        logger.debug(f"   ↪️ Redirection de {url} vers {final_url}")
    try:
        soup = BeautifulSoup(html, "lxml")
        title = get_title(soup)
        raw_content = extract_main_content(soup, html, context.site)
        content = clean_text(raw_content)
        excerpt = create_excerpt(content, max_length=250)
        images = extract_images(soup, final_url)
        content_hash = get_content_hash(content, title, images, excerpt)
        doc_id = generate_doc_id(final_url)
        is_no_index_page = is_excluded(final_url, context.no_index_patterns)
        is_duplicate_content = content_hash in context.processed_hashes
        is_skipped_by_cache = not context.force_recrawl and should_skip_page(final_url, content_hash)
        should_index = not is_no_index_page and not is_skipped_by_cache and not is_duplicate_content
        doc = None
        if should_index and len(content) >= 50:
            context.processed_hashes.add(content_hash)
            lang = "fr"
            html_tag = soup.find('html')
            if html_tag and html_tag.get('lang'):
                lang = html_tag.get('lang').split('-')[0].lower()
            now_iso = datetime.now().isoformat()
            doc = {
                "id": doc_id,
                "site": context.site["name"],
                "url": final_url,
                "title": title,
                "excerpt": excerpt,
                "content": content,
                "images": images,
                "lang": lang,
                "timestamp": int(time.time()),
                "indexed_at": now_iso,
                "last_crawled_at": now_iso,
                "content_hash": content_hash,
            }
            update_cache(final_url, content_hash, doc_id, context.site["name"], metadata['etag'], metadata['last_modified'])
        elif is_skipped_by_cache:
            await context.stats.increment('pages_skipped_cache')
        else:
            await context.stats.increment('pages_not_indexed')
        new_links = []
        if current_depth < context.max_depth:
            for link in soup.find_all("a", href=True):
                href = link.get('href')
                if href:
                    full_url = normalize_url(urljoin(final_url, href))
                    if is_valid_url(full_url) and is_same_domain(full_url, context.site["crawl"]):
                        new_links.append((full_url, current_depth + 1))
        return doc, new_links
    except Exception as e:
        logger.error(f"❌ Erreur traitement {url}: {e}")
        await context.stats.increment('errors')
        return None, []

async def crawl_site_html_async(context: CrawlContext, index):
    base_url = context.site["crawl"].replace("*", "")
    max_pages = context.site.get("max_pages", 0)
    logger.info(f"🚀 Démarrage crawl async '{context.site['name']}' -> {base_url}")
    logger.info(f"   Paramètres: max={max_pages}, depth={context.max_depth}, delay={context.rate_limiter.delay:.2f}s, workers={config.CONCURRENT_REQUESTS}")
    logger.info(f"   📦 Indexation progressive par lots de {config.INDEXING_BATCH_SIZE}")
    crawl_start_time = time.time()
    logger.info(f"   ⏱️  Timeout maximum: {config.MAX_CRAWL_DURATION}s ({config.MAX_CRAWL_DURATION/60:.1f} min)")
    logger.info(f"   🧠 Limite file d'attente: {config.MAX_QUEUE_SIZE} URLs")
    documents_buffer = []
    session_data = cache_db.get_session(context.site['name'])
    resume_urls = session_data.get('resume_urls') if session_data and not session_data.get('completed') else None
    if resume_urls and not context.force_recrawl:
        logger.info(f"🔄 Reprise du crawl depuis {len(resume_urls)} URLs précédemment découvertes.")
        to_visit = {(url, 0) for url in resume_urls}
    else:
        to_visit = {(normalize_url(base_url), 0)}
    visited: Set[str] = set()
    in_progress: Set[str] = set()
    timeout = ClientTimeout(total=config.TIMEOUT)
    ssl_context = ssl.create_default_context(cafile=certifi.where())
    connector = TCPConnector(limit=config.MAX_CONNECTIONS, limit_per_host=config.CONCURRENT_REQUESTS, ssl=ssl_context)
    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    }
    context.stats.pbar = tqdm(total=max_pages if max_pages > 0 else None, desc=f"🔍 {context.site['name']}", unit="pages", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]")
    async with ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        while to_visit or in_progress:
            elapsed_time = time.time() - crawl_start_time
            if elapsed_time > config.MAX_CRAWL_DURATION:
                logger.warning(f"⏱️  Timeout atteint ({elapsed_time/60:.1f} min) - arrêt du crawl")
                break
            if shutdown_handler.should_stop():
                logger.warning("⚠️  Arrêt gracieux demandé - sauvegarde en cours...")
                break
            if len(to_visit) > config.MAX_QUEUE_SIZE:
                logger.warning(f"🧠 Limite de queue atteinte ({len(to_visit)} URLs) - arrêt temporaire")
                break
            if max_pages > 0 and context.stats.pages_visited >= max_pages:
                break
            batch = []
            while to_visit and len(batch) < config.CONCURRENT_REQUESTS:
                if max_pages > 0 and context.stats.pages_visited + len(in_progress) >= max_pages:
                    break
                url, depth = to_visit.pop()
                if url in visited or url in in_progress:
                    continue
                if is_excluded(url, context.exclude_patterns):
                    continue
                ignored_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.pdf', '.zip', '.rar', '.mp3', '.mp4', '.avi')
                if url.lower().endswith(ignored_extensions):
                    logger.debug(f"   ↪️ Ignoré (extension de fichier): {url}")
                    visited.add(url)
                    continue
                robot_parser = get_robot_parser(url)
                if robot_parser and not robot_parser.can_fetch(config.USER_AGENT, url):
                    continue
                batch.append((url, depth))
                in_progress.add(url)
            if not batch:
                if in_progress:
                    await asyncio.sleep(0.1)
                continue
            tasks = [process_page(session, url, context, depth) for url, depth in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for (url, depth), result in zip(batch, results):
                visited.add(url)
                in_progress.discard(url)
                if isinstance(result, Exception):
                    logger.error(f"❌ Exception pour {url}: {result}")
                    await context.stats.increment('errors')
                    continue
                doc, new_links = result
                if doc:
                    documents_buffer.append(doc)
                    if len(documents_buffer) >= config.INDEXING_BATCH_SIZE:
                        await index_documents_batch(index, documents_buffer, context.stats)
                        await context.stats.increment('pages_indexed', len(documents_buffer))
                        documents_buffer.clear()
                for link_url, link_depth in new_links:
                    if link_url not in visited and link_url not in in_progress:
                        to_visit.add((link_url, link_depth))
    context.stats.pbar.close()
    context.stats.discovered_but_not_visited = len(to_visit)
    if documents_buffer:
        logger.info(f"📦 Indexation des {len(documents_buffer)} documents restants...")
        await index_documents_batch(index, documents_buffer, context.stats)
        await context.stats.increment('pages_indexed', len(documents_buffer))
        documents_buffer.clear()
    if len(to_visit) > 0 and (max_pages > 0 and context.stats.pages_visited >= max_pages):
        logger.info(f"📝 Sauvegarde de {len(to_visit)} URLs pour une reprise future.")
        resume_urls_set = {url for url, depth in to_visit}
        complete_crawl_session(context.site['name'], completed=False, resume_urls=resume_urls_set)

async def crawl_json_api_async(context: CrawlContext, index):
    base_url = context.site["crawl"]
    json_config = context.site["json"]
    logger.info(f"🚀 Démarrage crawl JSON '{context.site['name']}' -> {base_url}")
    logger.info(f"   📦 Indexation progressive par lots de {config.INDEXING_BATCH_SIZE}")
    documents_buffer = []
    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'application/json',
        **context.site.get('headers', {})
    }
    await context.rate_limiter.wait()
    try:
        ssl_context = ssl.create_default_context(cafile=certifi.where())
        async with aiohttp.ClientSession(headers=headers, timeout=ClientTimeout(total=config.TIMEOUT), connector=TCPConnector(ssl=ssl_context)) as session:
            async with session.get(base_url) as response:
                response.raise_for_status()
                data = await response.json()
        items = get_nested_value(data, json_config['root'])
        if not items:
            logger.error(f"❌ Élément racine '{json_config['root']}' introuvable")
            return
        logger.info(f"📦 {len(items)} éléments trouvés")
        context.stats.pbar = tqdm_sync(total=len(items), desc=f"🔍 {context.site['name']}", unit="items", bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]")
        for item in items:
            try:
                url_template = json_config['url']
                url = url_template
                template_keys = re.findall(r"\{\{(.*?)\}\}", url_template)
                for t_key in template_keys:
                    value = get_nested_value(item, t_key.strip())
                    if value:
                        url = url.replace(f"{{{{{t_key}}}}}", str(value))
                if not url or "{{" in url or not is_valid_url(url):
                    context.stats.pbar.update(1)
                    continue
                if is_excluded(url, context.exclude_patterns):
                    context.stats.pbar.update(1)
                    continue
                await context.stats.increment('pages_visited')
                title = str(get_nested_value(item, json_config['title']) or "Sans titre")
                doc_id = generate_doc_id(url)
                image_template = json_config.get('image', '')
                image_url = None
                if image_template:
                    image_url = image_template
                    img_template_keys = re.findall(r"\{\{(.*?)\}\}", image_template)
                    for t_key in img_template_keys:
                        value = get_nested_value(item, t_key.strip())
                        if value:
                            image_url = image_url.replace(f"{{{{{t_key}}}}}", str(value))
                    if "{{" in image_url:
                        image_url = None
                images = [{'url': image_url, 'alt': title, 'description': title}] if image_url else []
                content_parts = []
                for content_key in json_config.get('content', '').split(','):
                    if not content_key.strip():
                        continue
                    value = get_nested_value(item, content_key.strip())
                    if isinstance(value, list):
                        content_parts.extend(map(str, value))
                    elif value:
                        content_parts.append(str(value))
                content = ' '.join(content_parts)
                excerpt = create_excerpt(content)
                content_hash = get_content_hash(content, title, images, excerpt)
                should_index = context.force_recrawl or not should_skip_page(url, content_hash)
                if should_index:
                    now_iso = datetime.now().isoformat()
                    doc = {
                        "id": doc_id,
                        "site": context.site["name"],
                        "url": url,
                        "title": title,
                        "excerpt": excerpt,
                        "content": content,
                        "images": images,
                        "lang": context.site.get("lang", "fr"),
                        "timestamp": int(time.time()),
                        "indexed_at": now_iso,
                        "last_crawled_at": now_iso,
                        "content_hash": content_hash,
                    }
                    documents_buffer.append(doc)
                    update_cache(url, content_hash, doc_id, context.site["name"])
                    if len(documents_buffer) >= config.INDEXING_BATCH_SIZE:
                        await index_documents_batch(index, documents_buffer, context.stats)
                        await context.stats.increment('pages_indexed', len(documents_buffer))
                        documents_buffer.clear()
                else:
                    await context.stats.increment('pages_not_indexed')
                context.stats.pbar.update(1)
                context.stats.pbar.set_postfix({'indexées': context.stats.pages_indexed, 'non-indexées': context.stats.pages_not_indexed, 'erreurs': context.stats.errors})
            except Exception as e:
                logger.error(f"❌ Erreur traitement item JSON: {e}")
                await context.stats.increment('errors')
                context.stats.pbar.update(1)
        context.stats.pbar.close()
        if documents_buffer:
            logger.info(f"📦 Indexation des {len(documents_buffer)} documents restants...")
            await index_documents_batch(index, documents_buffer, context.stats)
            await context.stats.increment('pages_indexed', len(documents_buffer))
            documents_buffer.clear()
    except Exception as e:
        logger.error(f"❌ Erreur traitement JSON pour {context.site['name']}: {e}")
        await context.stats.increment('errors')

async def crawl_mediawiki_async(context: CrawlContext, index):
    from meilisearchcrawler.mediawiki_crawler import MediaWikiCrawler
    crawler = MediaWikiCrawler(context)
    use_embeddings = embedding_provider and embedding_provider.get_embedding_dim() > 0
    await crawler.crawl_and_index_progressive(meilisearch_index=index, use_embeddings=use_embeddings, indexing_batch_size=config.INDEXING_BATCH_SIZE)

def parse_arguments():
    parser = argparse.ArgumentParser(description='KidSearch Crawler', formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--force', action='store_true', help='Force le re-crawl complet')
    parser.add_argument('--site', type=str, help='Crawl un site spécifique')
    parser.add_argument('--verbose', action='store_true', help='Mode verbose')
    parser.add_argument('--clear-cache', action='store_true', help='Efface le cache')
    parser.add_argument('--stats-only', action='store_true', help='Affiche les stats du cache')
    parser.add_argument('--workers', type=int, default=config.CONCURRENT_REQUESTS, help=f'Nombre de workers (défaut: {config.CONCURRENT_REQUESTS})')
    parser.add_argument('--embeddings', action='store_true', help='Active la génération d\'embeddings (provider configuré dans .env)')
    return parser.parse_args()

def show_cache_stats():
    stats = cache_db.get_stats()
    if not stats or stats['total_urls'] == 0:
        logger.info("💾 Le cache est vide")
        return
    logger.info(f"\n{'=' * 60}")
    logger.info("📊 Statistiques du cache (SQLite)")
    logger.info(f"{'=' * 60}")
    logger.info(f"📄 Total d'URLs en cache: {stats['total_urls']}")
    if stats.get('sites'):
        logger.info(f"\n🌐 Répartition par site:")
        for site, count in sorted(stats['sites'].items(), key=lambda x: x[1], reverse=True):
            logger.info(f"   • {site}: {count} pages")
    if stats.get('oldest_crawl') and stats.get('newest_crawl'):
        oldest_date = datetime.fromtimestamp(stats['oldest_crawl']).strftime('%Y-%m-%d %H:%M:%S')
        newest_date = datetime.fromtimestamp(stats['newest_crawl']).strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"\n⏰ Premier crawl: {oldest_date}")
        logger.info(f"⏰ Dernier crawl: {newest_date}")
    logger.info(f"{'=' * 60}\n")

def clear_cache():
    logger.info("🗑️  Effacement du cache SQLite...")
    try:
        cache_db.clear_all()
        logger.info("   ✓ Cache effacé avec succès")
    except Exception as e:
        logger.error(f"❌ Erreur lors de l'effacement du cache: {e}")

async def main_async():
    args = parse_arguments()
    global embedding_provider

    # Initialize embedding provider if requested
    if args.embeddings:
        provider_name = os.getenv('EMBEDDING_PROVIDER', 'gemini')
        logger.info(f"✨ Activation de la génération d'embeddings (provider: {provider_name})")
        try:
            embedding_provider = create_embedding_provider(provider_name)
            if embedding_provider.get_embedding_dim() == 0:
                logger.warning("⚠️  Embeddings désactivés - provider non disponible")
            else:
                logger.info(f"   ✓ Provider: {embedding_provider.get_provider_name()} ({embedding_provider.get_embedding_dim()}D)")
                logger.info(f"   ✓ Model: {embedding_provider.get_model_name()}")
        except Exception as e:
            logger.error(f"❌ Erreur initialisation provider d'embeddings: {e}")
            embedding_provider = None

    if args.verbose:
        logger.setLevel(logging.DEBUG)
    if args.stats_only:
        show_cache_stats()
        return
    if args.clear_cache:
        clear_cache()
    
    async with AsyncClient(config.MEILI_URL, config.MEILI_KEY) as client:
        try:
            await client.health()
            logger.info("✅ Connexion MeiliSearch réussie")
            indexes = await client.get_indexes()
            if config.INDEX_NAME not in [i.uid for i in indexes]:
                logger.info(f"📦 Création de l'index '{config.INDEX_NAME}'...")
                await client.create_index(config.INDEX_NAME, primary_key='id')
                await asyncio.sleep(2)
            index = await client.get_index(config.INDEX_NAME)
            logger.info(f"✅ Index '{config.INDEX_NAME}' prêt")
            has_embeddings = embedding_provider and embedding_provider.get_embedding_dim() > 0
            await update_meilisearch_settings(index, with_embeddings=has_embeddings)
            if args.workers:
                if args.workers > config.MAX_WORKERS:
                    logger.warning(f"⚠️  Nombre de workers limité de {args.workers} à {config.MAX_WORKERS} (MAX_WORKERS)")
                    logger.warning(f"    Pour augmenter cette limite, définissez MAX_WORKERS dans .env")
                    config.CONCURRENT_REQUESTS = config.MAX_WORKERS
                else:
                    config.CONCURRENT_REQUESTS = args.workers
            sites_to_crawl = sites
            if args.site:
                sites_to_crawl = [s for s in sites if s['name'].lower() == args.site.lower()]
                if not sites_to_crawl:
                    logger.error(f"❌ Site '{args.site}' introuvable dans sites.yml")
                    logger.info("Sites disponibles:")
                    for s in sites:
                        logger.info(f"   • {s['name']}")
                    return
            global_status = GlobalCrawlStatus(total_sites=len(sites_to_crawl))
            global_status.start()
            logger.info(f"\n{'=' * 60}")
            logger.info(f"🚀 KidSearch Crawler")
            logger.info(f"{'=' * 60}")
            logger.info(f"📋 {len(sites_to_crawl)} site(s) à crawler")
            logger.info(f"🔄 Mode: {'FORCE RECRAWL' if args.force else 'INCREMENTAL'}")
            logger.info(f"⚡ Workers: {config.CONCURRENT_REQUESTS} requêtes parallèles")
            logger.info(f"📦 Indexation: par lots de {config.INDEXING_BATCH_SIZE} documents")
            if embedding_provider and embedding_provider.get_embedding_dim() > 0:
                logger.info(f"✨ Embeddings: Activés")
                logger.info(f"   Provider: {embedding_provider.get_provider_name()} ({embedding_provider.get_embedding_dim()}D)")
                logger.info(f"   Model: {embedding_provider.get_model_name()}")
            logger.info(f"{'=' * 60}\n")
            for i, site in enumerate(sites_to_crawl, 1):
                global_status.start_site(site['name'])
                logger.info(f"\n{'=' * 60}")
                logger.info(f"🌐 [{i}/{len(sites_to_crawl)}] {site['name']}")
                logger.info(f"    Type: {site.get('type', 'html').upper()}")
                logger.info(f"{'=' * 60}")
                context = CrawlContext(site, args.force)
                start_crawl_session(site['name'], urlparse(site['crawl']).netloc)
                completed_successfully = False
                try:
                    site_type = site.get('type', 'html')
                    if site_type == 'mediawiki':
                        await crawl_mediawiki_async(context, index)
                    elif site_type == 'json':
                        await crawl_json_api_async(context, index)
                    else:
                        await crawl_site_html_async(context, index)
                    completed_successfully = True
                except KeyboardInterrupt:
                    logger.warning("\n⚠️  Interruption par l'utilisateur")
                    break
                except Exception as e:
                    logger.error(f"❌ Erreur critique lors du crawl de {site['name']}: {e}", exc_info=args.verbose)
                finally:
                    complete_crawl_session(site['name'], completed=completed_successfully)
                    context.stats.log_summary()
                    global_status.finish_site(context.stats)
                if completed_successfully and i < len(sites_to_crawl):
                    logger.info("⏸️  Pause de 5 secondes avant le prochain site...\n")
                    await asyncio.sleep(5)
        finally:
            total_duration = time.time() - (global_status.start_time or time.time())
            global_status.stop()
            logger.info(f"\n{'=' * 60}")
            logger.info(f"🎉 Crawl terminé !")
            logger.info(f"{'=' * 60}")
            logger.info(f"⏱️  Durée totale: {total_duration / 60:.2f} minutes")
            logger.info(f"{'=' * 60}\n")
            show_cache_stats()

def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Arrêt du crawler par l'utilisateur")
    except Exception as e:
        logger.error(f"\n\n❌ Erreur fatale: {e}", exc_info=True)

if __name__ == "__main__":
    main()