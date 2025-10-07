# ---------------------------
# KidSearch Crawler
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
import sys
from dotenv import load_dotenv
from typing import Dict, List, Optional, Set, Tuple
import argparse
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from tqdm.asyncio import tqdm
from tqdm import tqdm as tqdm_sync
import trafilatura

# ---------------------------
# Logger
# ---------------------------
def get_base_path():
    """Retourne le chemin de base pour les fichiers, que le script soit compilé ou non."""
    if getattr(sys, 'frozen', False):
        # Si l'application est compilée (frozen) par PyInstaller
        return os.path.dirname(sys.executable)
    else:
        # Si c'est un script .py normal
        return os.path.dirname(os.path.abspath(__file__))


BASE_PATH = get_base_path()
LOG_FILE_PATH = os.path.join(BASE_PATH, 'crawler.log')

# ---------------------------
# Charger les variables d'environnement
# ---------------------------
load_dotenv(os.path.join(BASE_PATH, '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_FILE_PATH, encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


# ---------------------------
# Configuration
# ---------------------------
class Config:
    USER_AGENT = os.getenv('USER_AGENT', 'Mozilla/5.0 (compatible; KidSearch-Crawler/2.0)')
    MEILI_URL = os.getenv("MEILI_URL")
    MEILI_KEY = os.getenv("MEILI_KEY")
    INDEX_NAME = os.getenv("INDEX_NAME", "kidsearch")
    CACHE_FILE = os.path.join(BASE_PATH, "crawler_cache.json")
    MAX_RETRIES = int(os.getenv('MAX_RETRIES', 3))
    TIMEOUT = int(os.getenv('TIMEOUT', 15))
    DEFAULT_DELAY = float(os.getenv('DEFAULT_DELAY', 0.5))
    BATCH_SIZE = int(os.getenv('BATCH_SIZE', 20))
    CACHE_DAYS = int(os.getenv('CACHE_DAYS', 7))
    CONCURRENT_REQUESTS = int(os.getenv('CONCURRENT_REQUESTS', 5))
    MAX_CONNECTIONS = int(os.getenv('MAX_CONNECTIONS', 100))

    GLOBAL_EXCLUDE_PATTERNS = [
        # Actions utilisateur
        '/login', '/logout', '/signin', '/signup', '/register',
        '/cart', '/checkout', '/account',
        # Actions techniques
        '/share', '/print', '/cdn-cgi/',
        # CMS / API
        '/wp-admin/', '/wp-json/', '?rest_route=',
    ]


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
        'displayedAttributes': ['title', 'url', 'site', 'images', 'timestamp', 'excerpt', 'content', 'lang'],
        'filterableAttributes': ['site', 'timestamp', 'lang'],
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
    with open(os.path.join(BASE_PATH, "sites.yml"), "r", encoding='utf-8') as f:
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
            return {'_meta': {'crawls': {}}}
        try:
            with open(config.CACHE_FILE, 'r', encoding='utf-8') as f:
                cache = json.load(f)
                # Assurer la structure meta
                if '_meta' not in cache:
                    cache['_meta'] = {'crawls': {}}
                if 'crawls' not in cache['_meta']:
                    cache['_meta']['crawls'] = {}

                # Vérifier les crawls incomplets
                incomplete_sites = []
                for site_name, crawl_info in cache['_meta']['crawls'].items():
                    if not crawl_info.get('completed', False):
                        incomplete_sites.append(site_name)

                if incomplete_sites:
                    logger.warning(f"⚠️ Crawls incomplets détectés pour: {', '.join(incomplete_sites)}")
                    logger.warning(f"   Ces pages seront re-crawlées automatiquement")

                    # Invalider les URLs de ces sites
                    urls_to_remove = []
                    for url in list(cache.keys()):
                        if url == '_meta':
                            continue
                        for site_name in incomplete_sites:
                            crawl_info = cache['_meta']['crawls'][site_name]
                            if 'domain' in crawl_info:
                                if crawl_info['domain'] in url:
                                    urls_to_remove.append(url)
                                    break

                    for url in urls_to_remove:
                        del cache[url]

                    # Supprimer les entrées de crawls incomplets
                    for site_name in incomplete_sites:
                        del cache['_meta']['crawls'][site_name]

                    logger.info(f"   ✓ {len(urls_to_remove)} pages invalidées")

                return cache
        except Exception as e:
            logger.warning(f"⚠️ Échec chargement cache: {e}")
    return {'_meta': {'crawls': {}}}


def save_cache(cache: Dict):
    try:
        with open(config.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ Échec sauvegarde cache: {e}")


def start_crawl_session(cache: Dict, site_name: str, domain: str):
    """Marque le début d'un crawl."""
    cache['_meta']['crawls'][site_name] = {
        'started': datetime.now().isoformat(),
        'completed': False,
        'domain': domain
    }
    save_cache(cache)


def complete_crawl_session(cache: Dict, site_name: str, completed: bool = True, resume_urls: Optional[Set[str]] = None):
    """Marque la fin réussie d'un crawl."""
    if site_name in cache['_meta']['crawls']:
        cache['_meta']['crawls'][site_name]['completed'] = completed
        cache['_meta']['crawls'][site_name]['finished'] = datetime.now().isoformat()
        if resume_urls:
            cache['_meta']['crawls'][site_name]['resume_from'] = list(resume_urls)

        save_cache(cache)


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


def update_cache(cache: Dict, url: str, content_hash: str, doc_id: str, etag: str = None, last_modified: str = None):
    cache[url] = {
        'content_hash': content_hash,
        'last_crawl': time.time(),
        'doc_id': doc_id,
        'crawl_date': datetime.now().isoformat(),
        'etag': etag,
        'last_modified': last_modified
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
    # Stratégie 1: Sélecteur manuel (le plus fiable)
    site_selector = site_config.get('selector')
    if site_selector:
        content_element = soup.select_one(site_selector)
        if content_element:
            return content_element.get_text(separator=' ', strip=True)

    # Stratégie 2: Utiliser trafilatura, une librairie spécialisée
    extracted_text = trafilatura.extract(html_string, include_comments=False, include_tables=False)
    if extracted_text and len(extracted_text) > 250:
        return extracted_text

    # Stratégie 3: Heuristique maison comme solution de secours
    logger.debug("   (Fallback sur l'heuristique maison pour l'extraction de contenu)")
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

    # Si aucun candidat idéal n'est trouvé ou s'il est trop court,
    # on utilise une heuristique pour trouver le plus grand bloc de texte.
    if not best_candidate or best_candidate_len < 250: # Seuil relevé pour plus de robustesse
        if soup.body:
            all_elements = soup.body.find_all(True, recursive=True)
            max_len = 0
            best_elem = soup.body  # Fallback sur le body

            for elem in all_elements:
                # Ignorer les balises qui ne contiennent généralement pas de contenu principal
                if elem.name in ['nav', 'header', 'footer', 'aside', 'script', 'style', 'a', 'form']:
                    continue

                text_len = len(elem.get_text(strip=True))
                if text_len > max_len:
                    max_len = text_len
                    best_elem = elem

            target_element = best_elem
        else:
            return "" # Pas de body, pas de contenu
    else:
        target_element = best_candidate # On utilise le meilleur candidat trouvé via les sélecteurs

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

def get_title(soup: BeautifulSoup) -> str:
    """Extrait le titre de la page de manière robuste."""
    # Essayer le titre OpenGraph en premier, souvent plus propre
    og_title = soup.find('meta', property='og:title')
    if og_title and og_title.get('content'):
        return og_title['content'].strip()

    # Essayer le titre de la balise <title>
    if soup.title and soup.title.string:
        return soup.title.string.strip()

    # En dernier recours, chercher le premier <h1>
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
# Statistiques
# ---------------------------
class CrawlStats:
    def __init__(self, site_name: str):
        self.site_name = site_name
        self.start_time = time.time()
        self.pages_visited = 0
        self.pages_indexed = 0
        self.pages_not_indexed = 0
        self.pages_not_modified = 0  # Nouvelles stats
        self.discovered_but_not_visited = 0
        self.errors = 0
        self.redirects = 0
        self.lock = asyncio.Lock()
        self.pbar = None

    async def increment(self, attr: str):
        async with self.lock:
            setattr(self, attr, getattr(self, attr) + 1)
            # Mettre à jour la barre de progression uniquement pour les pages visitées
            if self.pbar and attr == 'pages_visited':
                self.pbar.update(1)
            if self.pbar: # Mettre à jour les stats affichées à chaque fois
                self.pbar.set_postfix({
                    'indexées': self.pages_indexed,
                    'non-indexées': self.pages_not_indexed,
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
        logger.info(f"⏭️  Pages non indexées (doublon, cache, etc.): {self.pages_not_indexed}")
        logger.info(f"♻️  Pages non modifiées (304): {self.pages_not_modified}")
        logger.info(f"🗺️  Liens découverts (non visités): {self.discovered_but_not_visited}")
        logger.info(f"❌ Erreurs: {self.errors}")
        if self.pages_visited > 0:
            logger.info(f"⚡ Vitesse: {self.pages_visited / duration:.2f} pages/s")
        logger.info(f"{'=' * 60}\n")


# ---------------------------
# Contexte de Crawl
# ---------------------------
class CrawlContext:
    """Regroupe tous les paramètres d'une session de crawl."""
    def __init__(self, site: Dict, force_recrawl: bool, cache: Dict):
        self.site = site
        self.force_recrawl = force_recrawl
        self.cache = cache
        self.cache_lock = asyncio.Lock()
        self.processed_hashes: Set[str] = set()
        self.stats = CrawlStats(site['name'])
        self.rate_limiter = RateLimiter(get_crawl_delay(site["crawl"]))
        self.exclude_patterns = config.GLOBAL_EXCLUDE_PATTERNS + site.get("exclude", [])
        self.no_index_patterns = site.get("no_index", [])
        self.max_depth = site.get("depth", 3)


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


async def index_documents_stream(documents: List[Dict], site_name: str):
    """Indexe les documents par streaming pour optimiser la mémoire."""
    if not documents:
        return

    try:
        # Indexer directement sans tout garder en mémoire
        index.add_documents(documents)
        logger.debug(f"📦 Batch de {len(documents)} documents indexé pour {site_name}")
    except Exception as e:
        logger.error(f"❌ Erreur indexation batch pour {site_name}: {e}")


async def fetch_page(session: ClientSession, url: str, rate_limiter: RateLimiter, cache: Dict = None) -> Optional[
    Tuple[str, str, Dict]]:
    """Récupère une page web de manière asynchrone avec support ETag/Last-Modified."""
    await rate_limiter.wait()

    # Préparer les headers conditionnels
    headers = {}
    if cache and url in cache:
        cached_data = cache[url]
        if cached_data.get('etag'):
            headers['If-None-Match'] = cached_data['etag']
        if cached_data.get('last_modified'):
            headers['If-Modified-Since'] = cached_data['last_modified']

    for attempt in range(config.MAX_RETRIES):
        try:
            async with session.get(url, headers=headers) as response:
                # 304 Not Modified
                if response.status == 304:
                    return (url, None, {'status': 304, 'etag': None, 'last_modified': None})

                # Vérifier le Content-Type AVANT de lire le corps de la réponse
                content_type = response.headers.get('Content-Type', '')
                if 'text/html' not in content_type.lower():
                    logger.debug(f"   ↪️ Ignoré (type non-HTML: {content_type}): {url}")
                    # On retourne un tuple spécial pour indiquer que la page a été visitée mais ignorée
                    return (url, None, {'status': 'skipped_content_type'})

                response.raise_for_status()
                text = await response.text()

                # Extraire ETag et Last-Modified
                etag = response.headers.get('ETag')
                last_modified = response.headers.get('Last-Modified')

                return (str(response.url), text, {
                    'status': response.status,
                    'etag': etag,
                    'last_modified': last_modified
                })
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
        context: CrawlContext,
        current_depth: int = 0
) -> Tuple[Optional[Dict], List[Tuple[str, int]]]:
    """Traite une page et retourne le document à indexer + les nouveaux liens avec leur profondeur."""

    result = await fetch_page(session, url, context.rate_limiter, context.cache if not context.force_recrawl else None)
    if not result:
        await context.stats.increment('errors')
        return None, []

    final_url, html, metadata = result

    # Gestion du 304 Not Modified
    if metadata['status'] == 304:
        await context.stats.increment('pages_not_modified')
        await context.stats.increment('pages_visited')
        return None, []

    # Gestion du type de contenu non-HTML
    if metadata['status'] == 'skipped_content_type':
        await context.stats.increment('pages_visited') # On l'a visitée, mais on ne l'indexe pas
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

        should_index = not is_no_index_page and (
                context.force_recrawl or not should_skip_page(final_url, content_hash, context.cache)
        ) and not is_duplicate_content

        doc = None
        if should_index and len(content) >= 50:
            await context.stats.increment('pages_indexed')
            context.processed_hashes.add(content_hash)

            # Détection de la langue pour le HTML
            lang = "fr" # Langue par défaut
            html_tag = soup.find('html')
            if html_tag and html_tag.get('lang'):
                lang = html_tag.get('lang').split('-')[0].lower()

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
                "last_modified": datetime.now().isoformat()
            }
            async with context.cache_lock:
                update_cache(context.cache, final_url, content_hash, doc_id, metadata['etag'], metadata['last_modified'])
                # Sauvegarde immédiate pour que les autres workers voient le changement
                save_cache(context.cache)
        else:
            await context.stats.increment('pages_not_indexed')

        # Extraire les liens avec profondeur
        new_links = []
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


async def crawl_site_html_async(context: CrawlContext):
    """Crawl un site HTML de manière asynchrone."""
    base_url = context.site["crawl"].replace("*", "")
    max_pages = context.site.get("max_pages", 200)

    logger.info(f"🚀 Démarrage crawl async '{context.site['name']}' -> {base_url}")
    logger.info(f"   Paramètres: max={max_pages}, depth={context.max_depth}, delay={context.rate_limiter.delay:.2f}s, workers={config.CONCURRENT_REQUESTS}")

    # Marquer le début du crawl
    # NOTE: La session est maintenant démarrée dans main_async
    # domain = urlparse(base_url).netloc
    # start_crawl_session(context.cache, context.site['name'], domain)
    documents_to_index = []

    # Vérifier s'il faut reprendre un crawl précédent
    crawl_meta = context.cache.get('_meta', {}).get('crawls', {}).get(context.site['name'], {})
    resume_urls = crawl_meta.get('resume_from')

    if resume_urls and not context.force_recrawl:
        logger.info(f"🔄 Reprise du crawl depuis {len(resume_urls)} URLs précédemment découvertes.")
        to_visit = set(resume_urls)
        # Nettoyer la liste de reprise pour ne pas la réutiliser
        del context.cache['_meta']['crawls'][context.site['name']]['resume_from']
    else:
        to_visit = {normalize_url(base_url)}

    visited: Set[str] = set()
    in_progress: Set[str] = set()

    timeout = ClientTimeout(total=config.TIMEOUT)
    connector = TCPConnector(limit=config.MAX_CONNECTIONS, limit_per_host=config.CONCURRENT_REQUESTS)

    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
    }

    # Initialiser la barre de progression
    context.stats.pbar = tqdm(
        total=max_pages,
        desc=f"🔍 {context.site['name']}",
        unit="pages",
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
    )

    async with ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        while (to_visit or in_progress) and len(visited) < max_pages:
            # Prendre jusqu'à CONCURRENT_REQUESTS URLs
            batch = []
            while to_visit and len(batch) < config.CONCURRENT_REQUESTS and len(visited) + len(in_progress) < max_pages:
                url = to_visit.pop()

                if url in visited or url in in_progress:
                    continue
                if is_excluded(url, context.exclude_patterns):
                    continue

                # Vérification rapide de l'extension pour éviter les requêtes inutiles
                ignored_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.svg', '.pdf', '.zip', '.rar', '.mp3', '.mp4', '.avi')
                if url.lower().endswith(ignored_extensions):
                    logger.debug(f"   ↪️ Ignoré (extension de fichier): {url}")
                    visited.add(url) # On la marque comme visitée pour ne pas y revenir
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
                process_page(session, url, context)
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

                # Ajouter les nouveaux liens
                for link_url, link_depth in new_links:
                    if link_depth > context.max_depth:
                        continue

                    if link_url in visited or link_url in in_progress or link_url in to_visit:
                        continue

                    if is_excluded(link_url, context.exclude_patterns):
                        continue

                    to_visit.add(link_url)

    # Fermer la barre de progression
    context.stats.pbar.close()

    # Mettre à jour le nombre de liens découverts mais non visités
    context.stats.discovered_but_not_visited = len(to_visit)

    # Si le crawl est incomplet, sauvegarder les URLs restantes pour une reprise future
    if len(to_visit) > 0 and len(visited) >= max_pages:
        logger.info(f"📝 Sauvegarde de {len(to_visit)} URLs pour une reprise future.")
        complete_crawl_session(context.cache, context.site['name'], completed=False, resume_urls=to_visit)

    # Indexer les documents restants
    if documents_to_index:
        try:
            index.add_documents(documents_to_index)
            logger.debug(f"📦 Dernier batch de {len(documents_to_index)} documents indexé")
        except Exception as e:
            logger.error(f"❌ Erreur indexation finale: {e}")

# ---------------------------
# Crawl JSON
# ---------------------------
async def crawl_json_api_async(context: CrawlContext):
    """Crawl une source JSON (wrapper async pour compatibilité)."""
    base_url = context.site["crawl"]
    json_config = context.site["json"]

    logger.info(f"🚀 Démarrage crawl JSON '{context.site['name']}' -> {base_url}")

    documents_to_index = []

    headers = {
        'User-Agent': config.USER_AGENT,
        'Accept': 'application/json',
        **context.site.get('headers', {})
    }

    # Vérifier robots.txt pour la source JSON
    robot_parser = get_robot_parser(base_url)
    if robot_parser and not robot_parser.can_fetch(config.USER_AGENT, base_url):
        logger.warning(f"🚫 Accès à {base_url} interdit par robots.txt")
        await context.stats.increment('errors')
        return

    try:
        async with aiohttp.ClientSession(headers=headers, timeout=ClientTimeout(total=config.TIMEOUT)) as session:
            async with session.get(base_url) as response:
                response.raise_for_status()
                data = await response.json()

        items = get_nested_value(data, json_config['root'])

        if not items:
            logger.error(f"❌ Élément racine '{json_config['root']}' introuvable")
            return

        logger.info(f"📦 {len(items)} éléments trouvés")

        # Initialiser la barre de progression pour JSON
        context.stats.pbar = tqdm_sync(
            total=len(items),
            desc=f"🔍 {context.site['name']}",
            unit="items",
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]"
        )

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
                should_index = context.force_recrawl or not should_skip_page(url, content_hash, context.cache)

                if should_index:
                    await context.stats.increment('pages_indexed')

                    doc = {
                        "id": doc_id,
                        "site": context.site["name"],
                        "url": url,
                        "title": title,
                        "excerpt": excerpt,
                        "content": content,
                        "images": images,
                        "lang": context.site.get("lang", "fr"), # Utiliser la langue du site ou 'fr' par défaut
                        "timestamp": int(time.time()),
                        "last_modified": datetime.now().isoformat()
                    }

                    documents_to_index.append(doc)
                    update_cache(context.cache, url, content_hash, doc_id)

                    if len(documents_to_index) >= config.BATCH_SIZE:
                        try:
                            index.add_documents(documents_to_index)
                        except Exception as e:
                            logger.error(f"❌ Erreur indexation batch: {e}")
                            await context.stats.increment('errors')
                        documents_to_index = []
                        save_cache(context.cache)
                else:
                    await context.stats.increment('pages_not_indexed')
                
                # Mettre à jour la barre de progression
                context.stats.pbar.update(1)
                context.stats.pbar.set_postfix({
                    'indexées': context.stats.pages_indexed,
                    'non-indexées': context.stats.pages_not_indexed,
                    'erreurs': context.stats.errors
                })

            except Exception as e:
                logger.error(f"❌ Erreur traitement item JSON: {e}")
                await context.stats.increment('errors')
                context.stats.pbar.update(1)

        context.stats.pbar.close()

        if documents_to_index:
            try:
                index.add_documents(documents_to_index)
            except Exception as e:
                logger.error(f"❌ Erreur indexation finale: {e}")
                await context.stats.increment('errors')

    except Exception as e:
        logger.error(f"❌ Erreur traitement JSON pour {context.site['name']}: {e}")
        await context.stats.increment('errors')


# ---------------------------
# CLI et Main
# ---------------------------
def parse_arguments():
    """Parse les arguments de ligne de commande."""
    parser = argparse.ArgumentParser(
        description='KidSearch Crawler - Async - Moteur d\'indexation pour contenu éducatif',
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

    # Exclure les métadonnées du compte
    urls_count = len([k for k in cache.keys() if k != '_meta'])

    if urls_count == 0:
        logger.info("💾 Le cache est vide")
        return

    logger.info(f"\n{'=' * 60}")
    logger.info("📊 Statistiques du cache")
    logger.info(f"{'=' * 60}")
    logger.info(f"📄 Total d'URLs en cache: {urls_count}")

    # Afficher les crawls en cours ou terminés
    if '_meta' in cache and 'crawls' in cache['_meta']:
        crawls = cache['_meta']['crawls']
        if crawls:
            logger.info(f"\n🔄 Historique des crawls:")
            for site_name, crawl_info in crawls.items():
                status = "✅ Complet" if crawl_info.get('completed', False) else "⚠️ Incomplet"
                started = crawl_info.get('started', 'Inconnu')
                logger.info(f"   • {site_name}: {status} (démarré le {started[:19]})")

    sites_count = {}
    oldest_crawl = None
    newest_crawl = None

    for url, data in cache.items():
        if url == '_meta':
            continue
        parsed = urlparse(url)
        domain = parsed.netloc
        sites_count[domain] = sites_count.get(domain, 0) + 1

        crawl_time = data.get('last_crawl', 0)
        if crawl_time:
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

    # Charger le cache une première fois pour la maintenance
    logger.info("⚙️  Vérification de l'intégrité du cache...")
    load_cache()

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
    logger.info(f"🚀 KidSearch Crawler")
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

        cache = load_cache()
        context = CrawlContext(site, args.force, cache)
        start_crawl_session(context.cache, site['name'], urlparse(site['crawl']).netloc)

        completed_successfully = False
        try:
            if site.get('type') == 'json':
                await crawl_json_api_async(context)
            else:
                await crawl_site_html_async(context)
            completed_successfully = True
        except KeyboardInterrupt:
            logger.warning("\n⚠️  Interruption par l'utilisateur")
            break # Sortir de la boucle des sites
        except Exception as e:
            logger.error(f"❌ Erreur critique lors du crawl de {site['name']}: {e}", exc_info=args.verbose)
        finally:
            # Toujours marquer la session et afficher le résumé
            complete_crawl_session(context.cache, site['name'], completed=completed_successfully)
            save_cache(context.cache)
            context.stats.log_summary()

        if completed_successfully and i < len(sites_to_crawl):
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