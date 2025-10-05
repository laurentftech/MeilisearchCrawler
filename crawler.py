# ---------------------------
# KidSearch Crawler v2.0 - Async Edition
# ---------------------------
import yaml
import aiohttp
import asyncio
from bs4 import BeautifulSoup
import time
from meilisearch import Client
import logging
from urllib.parse import urljoin, urlparse
import hashlib
from urllib.robotparser import RobotFileParser
import json
import os
import re
from datetime import datetime
from dotenv import load_dotenv
from typing import Dict, List, Optional, Set, Tuple
import argparse
from aiohttp import ClientSession, ClientTimeout, TCPConnector

# ---------------------------
# Logger
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('crawler.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ---------------------------
# Charger les variables d'environnement
# ---------------------------
load_dotenv()


# ---------------------------
# Configuration
# ---------------------------
class Config:
    USER_AGENT = os.getenv('USER_AGENT', 'Mozilla/5.0 (compatible; KidSearch-Crawler/2.0)')
    MEILI_URL = os.getenv("MEILI_URL")
    MEILI_KEY = os.getenv("MEILI_KEY")
    INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
    CACHE_FILE = "crawler_cache.json"
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    TIMEOUT = int(os.getenv('TIMEOUT', 15))
    DEFAULT_DELAY = float(os.getenv('DEFAULT_DELAY', 0.5))
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 20))
    CACHE_DAYS = int(os.getenv('CACHE_DAYS', 7))
    CONCURRENT_REQUESTS = int(os.getenv('CONCURRENT_REQUESTS', 5))  # Nombre de requêtes parallèles
    MAX_CONNECTIONS = int(os.getenv('MAX_CONNECTIONS', 100))  # Pool de connexions


config = Config()

# ---------------------------
# Validation
# ---------------------------
if not config.MEILI_URL or not config.MEILI_KEY:
    logger.error("❌ Les variables d'environnement MEILI_URL et MEILI_KEY doivent être définies.")
    exit(1)

# ---------------------------
# MeiliSearch Setup
# ---------------------------
try:
    client = Client(config.MEILI_URL, config.MEILI_KEY)
    client.health()
    logger.info("✅ Connexion MeiliSearch réussie")
except Exception as e:
    logger.error(f"❌ Erreur connexion MeiliSearch: {e}")
    exit(1)


def update_meilisearch_settings(index):
    """Met à jour les paramètres de l'index MeiliSearch."""
    logger.info("⚙️ Mise à jour des paramètres MeiliSearch...")
    settings = {
        'searchableAttributes': ['title', 'excerpt', 'content', 'site', 'images.alt'],
        'displayedAttributes': ['title', 'url', 'site', 'images', 'timestamp', 'excerpt', 'content'],
        'filterableAttributes': ['site', 'timestamp'],
        'sortableAttributes': ['timestamp'],
        'rankingRules': ['words', 'typo', 'proximity', 'attribute', 'sort', 'exactness']
    }
    try:
        task = index.update_settings(settings)
        logger.info(f"   ✓ Paramètres mis à jour (task uid: {task.task_uid})")
    except Exception as e:
        logger.error(f"❌ Échec mise à jour paramètres: {e}")


try:
    indexes = client.get_indexes()
    existing_indexes = [i.uid for i in indexes['results']]

    if config.INDEX_NAME not in existing_indexes:
        logger.info(f"📦 Création de l'index '{config.INDEX_NAME}'...")
        client.create_index(config.INDEX_NAME, {'primaryKey': 'id'})
        time.sleep(2)

    index = client.index(config.INDEX_NAME)
    logger.info(f"✅ Index '{config.INDEX_NAME}' prêt")
    update_meilisearch_settings(index)

except Exception as e:
    logger.error(f"❌ Erreur configuration index: {e}")
    exit(1)

# ---------------------------
# Charger sites.yml
# ---------------------------
try:
    with open("sites.yml", "r", encoding='utf-8') as f:
        sites_data = yaml.safe_load(f)
        sites = sites_data.get("sites", sites_data)
    logger.info(f"📋 {len(sites)} site(s) chargé(s) depuis sites.yml")
except FileNotFoundError:
    logger.error("❌ Fichier sites.yml introuvable")
    exit(1)
except Exception as e:
    logger.error(f"❌ Erreur lecture sites.yml: {e}")
    exit(1)


# ---------------------------
# Cache et indexation incrémentale
# ---------------------------
def load_cache() -> Dict:
    if os.path.exists(config.CACHE_FILE):
        if os.path.getsize(config.CACHE_FILE) == 0:
            return {}
        try:
            with open(config.CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Échec chargement cache: {e}")
    return {}


def save_cache(cache: Dict):
    try:
        with open(config.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ Échec sauvegarde cache: {e}")


def get_content_hash(content: str, title: str, images: List, excerpt: str) -> str:
    images_str = json.dumps(images, sort_keys=True)
    content_str = f"{title}|{excerpt}|{content}|{images_str}"
    return hashlib.md5(content_str.encode()).hexdigest()


def should_skip_page(url: str, content_hash: str, cache: Dict) -> bool:
    if url not in cache:
        return False
    cached_data = cache[url]
    if cached_data.get('content_hash') == content_hash:
        last_crawl = cached_data.get('last_crawl', 0)
        days_ago = (time.time() - last_crawl) / (24 * 3600)
        if days_ago < config.CACHE_DAYS:
            return True
    return False


def update_cache(cache: Dict, url: str, content_hash: str, doc_id: str):
    cache[url] = {
        'content_hash': content_hash,
        'last_crawl': time.time(),
        'doc_id': doc_id,
        'crawl_date': datetime.now().isoformat()
    }


# ---------------------------
# Gestion de robots.txt
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
    """Récupère le délai de crawl depuis robots.txt."""
    parser = get_robot_parser(url)
    if parser:
        delay = parser.crawl_delay(config.USER_AGENT)
        if delay:
            return float(delay)
    return config.DEFAULT_DELAY


# ---------------------------
# Utilitaires
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
        current = current.get(key) if isinstance(current, dict) else None
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


def extract_main_content(soup: BeautifulSoup) -> str:
    best_candidate = None
    best_candidate_len = 0

    for selector in [
        'article', 'main', '[role="main"]',
        '.post-content', '.entry-content', '.article-content',
        '.content-main', '.main-content',
        '#content', '.content', '.mw-parser-output'
    ]:
        content_elem = soup.select_one(selector)
        if content_elem:
            temp_elem = BeautifulSoup(str(content_elem), 'lxml')
            current_len = len(temp_elem.get_text(strip=True))
            if current_len > best_candidate_len:
                best_candidate = content_elem
                best_candidate_len = current_len

    if not best_candidate or best_candidate_len < 150:
        target_element = soup.body
        if not target_element:
            return ""
    else:
        target_element = best_candidate

    for tag in target_element.select(
            'nav, header, footer, aside, form, script, style, iframe, '
            '.sidebar, .widget, .social-share, .related-posts, '
            '.comments, .comment, .advertisement, .ad, .ads, '
            '[class*="share"], [class*="related"], [class*="sidebar"], '
            '[class*="widget"], [class*="promo"], [class*="cookie"], '
            '[aria-hidden="true"]'
    ):
        tag.decompose()

    return target_element.get_text(separator=' ', strip=True)


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
# Statistiques
# ---------------------------
class CrawlStats:
    def __init__(self, site_name: str):
        self.site_name = site_name
        self.start_time = time.time()
        self.pages_visited = 0
        self.pages_indexed = 0
        self.pages_skipped = 0
        self.errors = 0
        self.redirects = 0
        self.lock = asyncio.Lock()

    async def increment(self, attr: str):
        async with self.lock:
            setattr(self, attr, getattr(self, attr) + 1)

    def log_summary(self):
        duration = time.time() - self.start_time
        logger.info(f"\n{'=' * 60}")
        logger.info(f"📊 Résumé du crawl pour '{self.site_name}'")
        logger.info(f"{'=' * 60}")
        logger.info(f"⏱️  Durée: {duration:.2f}s")
        logger.info(f"🌐 Pages visitées: {self.pages_visited}")
        logger.info(f"✅ Pages indexées: {self.pages_indexed}")
        logger.info(f"⏭️  Pages ignorées: {self.pages_skipped}")
        logger.info(f"❌ Erreurs: {self.errors}")
        if self.pages_visited > 0:
            logger.info(f"⚡ Vitesse: {self.pages_visited / duration:.2f} pages/s")
        logger.info(f"{'=' * 60}\n")


# ---------------------------
# Rate Limiter Async
# ---------------------------
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


# ---------------------------
# Crawl HTML Async
# ---------------------------
async def fetch_page(session: ClientSession, url: str, rate_limiter: RateLimiter) -> Optional[Tuple[str, str]]:
    """Récupère une page web de manière asynchrone."""
    await rate_limiter.wait()

    for attempt in range(config.MAX_RETRIES):
        try:
            async with session.get(url) as response:
                response.raise_for_status()
                text = await response.text()
                return (str(response.url), text)
        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout {attempt + 1}/{config.MAX_RETRIES} pour {url}")
        except Exception as e:
            logger.warning(f"⚠️ Tentative {attempt + 1}/{config.MAX_RETRIES} échouée pour {url}: {e}")

        if attempt + 1 < config.MAX_RETRIES:
            await asyncio.sleep(2 ** attempt)

    return None


async def process_page(
        session: ClientSession,
        url: str,
        site: Dict,
        cache: Dict,
        stats: CrawlStats,
        rate_limiter: RateLimiter,
        force_recrawl: bool,
        exclude_patterns: List[str],
        no_index_patterns: List[str]
) -> Tuple[Optional[Dict], List[str]]:
    """Traite une page et retourne le document à indexer + les nouveaux liens."""

    result = await fetch_page(session, url, rate_limiter)
    if not result:
        await stats.increment('errors')
        return None, []

    final_url, html = result
    await stats.increment('pages_visited')

    if final_url != url:
        await stats.increment('redirects')

    try:
        soup = BeautifulSoup(html, "lxml")
        title = soup.title.string.strip() if soup.title and soup.title.string else "Sans titre"

        for tag in soup(["script", "style"]):
            tag.decompose()

        raw_content = extract_main_content(soup)
        content = clean_text(raw_content)
        excerpt = create_excerpt(content, max_length=250)
        images = extract_images(soup, final_url)

        content_hash = get_content_hash(content, title, images, excerpt)
        doc_id = generate_doc_id(final_url)

        is_no_index_page = is_excluded(final_url, no_index_patterns)
        should_index = not is_no_index_page and (
                force_recrawl or not should_skip_page(final_url, content_hash, cache)
        )

        doc = None
        if should_index and len(content) >= 50:
            await stats.increment('pages_indexed')
            logger.info(f"✅ Indexé: {title[:60]}")

            doc = {
                "id": doc_id,
                "site": site["name"],
                "url": final_url,
                "title": title,
                "excerpt": excerpt,
                "content": content,
                "images": images,
                "timestamp": int(time.time()),
                "last_modified": datetime.now().isoformat()
            }
            update_cache(cache, final_url, content_hash, doc_id)
        else:
            await stats.increment('pages_skipped')

        # Extraire les liens
        new_links = []
        for link in soup.find_all("a", href=True):
            href = link.get('href')
            if href:
                full_url = normalize_url(urljoin(final_url, href))
                if is_valid_url(full_url) and is_same_domain(full_url, site["crawl"]):
                    new_links.append(full_url)

        return doc, new_links

    except Exception as e:
        logger.error(f"❌ Erreur traitement {url}: {e}")
        await stats.increment('errors')
        return None, []


async def crawl_site_html_async(site: Dict, force_recrawl: bool = False):
    """Crawl un site HTML de manière asynchrone."""
    stats = CrawlStats(site['name'])
    base_url = site["crawl"].replace("*", "")

    max_pages = site.get("max_pages", 200)
    depth = site.get("depth", 3)
    delay = get_crawl_delay(base_url)
    exclude_patterns = site.get("exclude", [])
    no_index_patterns = site.get("no_index", [])

    logger.info(f"🚀 Démarrage crawl async '{site['name']}' -> {base_url}")
    logger.info(f"   Paramètres: max={max_pages}, depth={depth}, delay={delay}s, workers={config.CONCURRENT_REQUESTS}")

    cache = load_cache()
    documents_to_index = []

    to_visit = {normalize_url(base_url)}
    visited: Set[str] = set()
    in_progress: Set[str] = set()

    rate_limiter = RateLimiter(delay)

    timeout = ClientTimeout(total=config.TIMEOUT)
    connector = TCPConnector(limit=config.MAX_CONNECTIONS, limit_per_host=config.CONCURRENT_REQUESTS)

    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    async with ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        while (to_visit or in_progress) and len(visited) < max_pages:
            # Prendre jusqu'à CONCURRENT_REQUESTS URLs
            batch = []
            while to_visit and len(batch) < config.CONCURRENT_REQUESTS and len(visited) + len(in_progress) < max_pages:
                url = to_visit.pop()

                if url in visited or url in in_progress:
                    continue
                if is_excluded(url, exclude_patterns):
                    continue

                robot_parser = get_robot_parser(url)
                if robot_parser and not robot_parser.can_fetch(config.USER_AGENT, url):
                    continue

                batch.append(url)
                in_progress.add(url)

            if not batch:
                if in_progress:
                    await asyncio.sleep(0.1)
                continue

            # Traiter le batch en parallèle
            tasks = [
                process_page(session, url, site, cache, stats, rate_limiter, force_recrawl, exclude_patterns,
                             no_index_patterns)
                for url in batch
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for url, result in zip(batch, results):
                visited.add(url)
                in_progress.discard(url)

                if isinstance(result, Exception):
                    logger.error(f"❌ Exception pour {url}: {result}")
                    continue

                doc, new_links = result

                if doc:
                    documents_to_index.append(doc)

                    if len(documents_to_index) >= config.BATCH_SIZE:
                        try:
                            index.add_documents(documents_to_index)
                            logger.debug(f"📦 Batch de {len(documents_to_index)} documents indexé")
                        except Exception as e:
                            logger.error(f"❌ Erreur indexation batch: {e}")
                        documents_to_index = []
                        save_cache(cache)

                # Ajouter les nouveaux liens
                for link in new_links:
                    if link not in visited and link not in in_progress and link not in to_visit:
                        if not is_excluded(link, exclude_patterns):
                            to_visit.add(link)

    # Indexer les documents restants
    if documents_to_index:
        try:
            index.add_documents(documents_to_index)
            logger.debug(f"📦 Dernier batch de {len(documents_to_index)} documents indexé")
        except Exception as e:
            logger.error(f"❌ Erreur indexation finale: {e}")

    save_cache(cache)
    stats.log_summary()


# ---------------------------
# Crawl JSON (reste synchrone)
# ---------------------------
async def crawl_json_api_async(site: Dict, force_recrawl: bool = False):
    """Crawl une source JSON (wrapper async pour compatibilité)."""
    import requests

    stats = CrawlStats(site['name'])
    base_url = site["crawl"]
    json_config = site["json"]

    logger.info(f"🚀 Démarrage crawl JSON '{site['name']}' -> {base_url}")

    cache = load_cache()
    documents_to_index = []

    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'application/json',
        **site.get('headers', {})
    }
    exclude_patterns = site.get("exclude", [])

    try:
        response = requests.get(base_url, headers=headers, timeout=config.TIMEOUT)
        response.raise_for_status()
        data = response.json()
        items = get_nested_value(data, json_config['root'])

        if not items:
            logger.error(f"❌ Élément racine '{json_config['root']}' introuvable")
            return

        logger.info(f"📦 {len(items)} éléments trouvés")

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
                    continue

                if is_excluded(url, exclude_patterns):
                    continue

                stats.pages_visited += 1

                title = get_nested_value(item, json_config['title']) or "Sans titre"
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
                should_index = force_recrawl or not should_skip_page(url, content_hash, cache)

                if should_index:
                    stats.pages_indexed += 1
                    logger.info(f"✅ Indexé: {title[:60]}")

                    doc = {
                        "id": doc_id,
                        "site": site["name"],
                        "url": url,
                        "title": title,
                        "excerpt": excerpt,
                        "content": content,
                        "images": images,
                        "timestamp": int(time.time()),
                        "last_modified": datetime.now().isoformat()
                    }

                    documents_to_index.append(doc)
                    update_cache(cache, url, content_hash, doc_id)

                    if len(documents_to_index) >= config.BATCH_SIZE:
                        try:
                            index.add_documents(documents_to_index)
                        except Exception as e:
                            logger.error(f"❌ Erreur indexation batch: {e}")
                            stats.errors += 1
                        documents_to_index = []
                        save_cache(cache)
                else:
                    stats.pages_skipped += 1

            except Exception as e:
                logger.error(f"❌ Erreur traitement item JSON: {e}")
                stats.errors += 1

        if documents_to_index:
            try:
                index.add_documents(documents_to_index)
            except Exception as e:
                logger.error(f"❌ Erreur indexation finale: {e}")

        save_cache(cache)
        stats.log_summary()

    except Exception as e:
        logger.error(f"❌ Erreur traitement JSON pour {site['name']}: {e}")


# ---------------------------
# CLI et Main
# ---------------------------
def parse_arguments():
    """Parse les arguments de ligne de commande."""
    parser = argparse.ArgumentParser(
        description='KidSearch Crawler v2.0 - Async - Moteur d\'indexation pour contenu éducatif',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--force',
        action='store_true',
        help='Force le re-crawl complet (ignore le cache)'
    )

    parser.add_argument(
        '--site',
        type=str,
        help='Crawl uniquement un site spécifique (par nom)'
    )

    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Mode verbose (affiche les messages de debug)'
    )

    parser.add_argument(
        '--clear-cache',
        action='store_true',
        help='Efface le cache avant de démarrer'
    )

    parser.add_argument(
        '--stats-only',
        action='store_true',
        help='Affiche uniquement les statistiques du cache'
    )

    parser.add_argument(
        '--workers',
        type=int,
        default=config.CONCURRENT_REQUESTS,
        help=f'Nombre de requêtes parallèles (défaut: {config.CONCURRENT_REQUESTS})'
    )

    return parser.parse_args()


def show_cache_stats():
    """Affiche les statistiques du cache."""
    cache = load_cache()

    if not cache:
        logger.info("💾 Le cache est vide")
        return

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 Statistiques du cache")
    logger.info(f"{'=' * 60}")
    logger.info(f"📄 Total d'URLs en cache: {len(cache)}")

    sites_count = {}
    oldest_crawl = None
    newest_crawl = None

    for url, data in cache.items():
        parsed = urlparse(url)
        domain = parsed.netloc
        sites_count[domain] = sites_count.get(domain, 0) + 1

        crawl_time = data.get('last_crawl', 0)
        if oldest_crawl is None or crawl_time < oldest_crawl:
            oldest_crawl = crawl_time
        if newest_crawl is None or crawl_time > newest_crawl:
            newest_crawl = crawl_time

    logger.info(f"\n🌐 Répartition par domaine:")
    for domain, count in sorted(sites_count.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"   • {domain}: {count} pages")

    if oldest_crawl and newest_crawl:
        oldest_date = datetime.fromtimestamp(oldest_crawl).strftime('%Y-%m-%d %H:%M:%S')
        newest_date = datetime.fromtimestamp(newest_crawl).strftime('%Y-%m-%d %H:%M:%S')
        logger.info(f"\n⏰ Premier crawl: {oldest_date}")
        logger.info(f"⏰ Dernier crawl: {newest_date}")

    logger.info(f"{'=' * 60}\n")


def clear_cache():
    """Efface le cache."""
    if os.path.exists(config.CACHE_FILE):
        try:
            os.remove(config.CACHE_FILE)
            logger.info("🗑️  Cache effacé avec succès")
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'effacement du cache: {e}")
    else:
        logger.info("💾 Aucun cache à effacer")


async def main_async():
    """Point d'entrée principal asynchrone."""
    args = parse_arguments()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.stats_only:
        show_cache_stats()
        return

    if args.clear_cache:
        clear_cache()

    # Mettre à jour le nombre de workers si spécifié
    if args.workers:
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

    logger.info(f"\n{'=' * 60}")
    logger.info(f"🚀 KidSearch Crawler v2.0 - Async Edition")
    logger.info(f"{'=' * 60}")
    logger.info(f"📋 {len(sites_to_crawl)} site(s) à crawler")
    logger.info(f"🔄 Mode: {'FORCE RECRAWL' if args.force else 'INCREMENTAL'}")
    logger.info(f"⚡ Workers: {config.CONCURRENT_REQUESTS} requêtes parallèles")
    logger.info(f"{'=' * 60}\n")

    start_time = time.time()

    for i, site in enumerate(sites_to_crawl, 1):
        logger.info(f"\n{'=' * 60}")
        logger.info(f"🌐 [{i}/{len(sites_to_crawl)}] {site['name']}")
        logger.info(f"    Type: {site.get('type', 'html').upper()}")
        logger.info(f"{'=' * 60}")

        try:
            if site.get('type') == 'json':
                await crawl_json_api_async(site, force_recrawl=args.force)
            else:
                await crawl_site_html_async(site, force_recrawl=args.force)
        except KeyboardInterrupt:
            logger.warning("\n⚠️  Interruption par l'utilisateur")
            break
        except Exception as e:
            logger.error(f"❌ Erreur critique lors du crawl de {site['name']}: {e}")

        if i < len(sites_to_crawl):
            logger.info("⏸️  Pause de 5 secondes avant le prochain site...\n")
            await asyncio.sleep(5)

    total_duration = time.time() - start_time
    logger.info(f"\n{'=' * 60}")
    logger.info(f"🎉 Crawl terminé !")
    logger.info(f"{'=' * 60}")
    logger.info(f"⏱️  Durée totale: {total_duration / 60:.2f} minutes")
    logger.info(f"{'=' * 60}\n")

    show_cache_stats()


def main():
    """Wrapper synchrone pour le main asynchrone."""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.warning("\n\n⚠️  Arrêt du crawler par l'utilisateur")
    except Exception as e:
        logger.error(f"\n\n❌ Erreur fatale: {e}", exc_info=True)


if __name__ == "__main__":
    main()