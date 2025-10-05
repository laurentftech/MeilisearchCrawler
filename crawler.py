# ---------------------------
# Fonctions utilitaires
# ---------------------------
import yaml
import requests
from bs4 import BeautifulSoup
import time
from meilisearch import Client
import logging
from urllib.parse import urljoin, urlparse
import hashlib
import json
import os
import re
from datetime import datetime
from dotenv import load_dotenv

# ---------------------------
# Logger
# ---------------------------
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ---------------------------
# Charger les variables d'environnement
# ---------------------------
load_dotenv()

# ---------------------------
# Config MeiliSearch
# ---------------------------
MEILI_URL = os.getenv("MEILI_URL")
MEILI_KEY = os.getenv("MEILI_KEY")
INDEX_NAME = "kidsearch"

if not MEILI_URL or not MEILI_KEY:
    logger.error("❌ Les variables d'environnement MEILI_URL et MEILI_KEY doivent être définies.")
    logger.error("   Créez un fichier .env ou exportez-les dans votre shell.")
    exit(1)

try:
    client = Client(MEILI_URL, MEILI_KEY)
    client.health()
    logger.info("✅ Connexion MeiliSearch réussie")
except Exception as e:
    logger.error(f"❌ Erreur connexion MeiliSearch: {e}")
    exit(1)


def update_meilisearch_settings(index):
    """Met à jour les paramètres de l'index MeiliSearch."""
    logger.info("⚙️ Updating MeiliSearch index settings...")
    settings = {
        'searchableAttributes': [
            'title',
            'excerpt',  # Priorisé pour la recherche
            'content',
            'site',
            'images.alt'
        ],
        'displayedAttributes': [
            'title',
            'url',
            'site',
            'images',
            'timestamp',
            'excerpt',  # Pour l'affichage dans les résultats
            'content'  # Gardé pour référence
        ],
        'filterableAttributes': [
            'site'
        ],
        'sortableAttributes': [
            'timestamp'
        ]
    }
    try:
        task = index.update_settings(settings)
        logger.info(f"   - Task enqueued to update settings (uid: {task.task_uid})")
    except Exception as e:
        logger.error(f"❌ Failed to update MeiliSearch settings: {e}")


try:
    indexes = client.get_indexes()
    existing_indexes = [i.uid for i in indexes['results']]

    if INDEX_NAME not in existing_indexes:
        logger.info(f"Index '{INDEX_NAME}' not found. Creating it...")
        client.create_index(INDEX_NAME, {'primaryKey': 'id'})
        time.sleep(2)

    index = client.index(INDEX_NAME)
    logger.info(f"✅ Index '{INDEX_NAME}' ready")
    update_meilisearch_settings(index)

except Exception as e:
    logger.error(f"❌ Erreur lors de la configuration de l'index: {e}")
    exit(1)

# ---------------------------
# Charger sites.yml
# ---------------------------
try:
    with open("sites.yml", "r", encoding='utf-8') as f:
        sites_data = yaml.safe_load(f)
        sites = sites_data["sites"] if "sites" in sites_data else sites_data
    logger.info(f"Loaded {len(sites)} site(s) from sites.yml")
except FileNotFoundError:
    logger.error("❌ Fichier sites.yml introuvable")
    exit(1)
except Exception as e:
    logger.error(f"❌ Erreur lecture sites.yml: {e}")
    exit(1)

# ---------------------------
# Cache et indexation incrémentale
# ---------------------------
CACHE_FILE = "crawler_cache.json"


def load_cache():
    if os.path.exists(CACHE_FILE):
        if os.path.getsize(CACHE_FILE) == 0:
            return {}
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"⚠️ Failed to load cache: {e}")
    return {}


def save_cache(cache):
    try:
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"❌ Failed to save cache: {e}")


def get_content_hash(content, title, images, excerpt):
    """Génère un hash incluant l'excerpt"""
    images_str = json.dumps(images, sort_keys=True)
    content_str = f"{title}|{excerpt}|{content}|{images_str}"
    return hashlib.md5(content_str.encode()).hexdigest()


def should_skip_page(url, content_hash, cache):
    if url not in cache:
        return False
    cached_data = cache[url]
    if cached_data.get('content_hash') == content_hash:
        last_crawl = cached_data.get('last_crawl', 0)
        days_ago = (time.time() - last_crawl) / (24 * 3600)
        if days_ago < 7:
            logger.debug(f"⏭️ Skipping {url} (no changes, crawled {days_ago:.1f} days ago)")
            return True
    return False


def update_cache(cache, url, content_hash, doc_id):
    cache[url] = {
        'content_hash': content_hash,
        'last_crawl': time.time(),
        'doc_id': doc_id,
        'crawl_date': datetime.now().isoformat()
    }


# ---------------------------
# Fonctions Utilitaires améliorées
# ---------------------------
def generate_doc_id(url):
    return hashlib.md5(url.encode()).hexdigest()


def normalize_url(url):
    """Normalise une URL en supprimant le fragment."""
    return url.split('#')[0]


def is_same_domain(url1, url2):
    return urlparse(url1).netloc == urlparse(url2).netloc


def is_excluded(url, patterns):
    """Vérifie si une URL contient l'un des motifs d'exclusion."""
    if not patterns:
        return False
    for pattern in patterns:
        if pattern in url:
            return True
    return False


def remove_common_patterns(text):
    """Supprime les patterns répétitifs non pertinents"""
    patterns_to_remove = [
        r'Partager\s*:.*?(?=\n\n|\Z)',
        r'Publications similaires.*?(?=\n\n|\Z)',
        r'En tant qu\'adhérent.*?(?=\n\n|\Z)',
        r'J\'accède aux.*?(?=\n\n|\Z)',
        r'Suivez-nous sur.*?(?=\n\n|\Z)',
        r'Abonnez-vous.*?(?=\n\n|\Z)',
        r'Rejoignez-nous.*?(?=\n\n|\Z)',
        r'Inscrivez-vous.*?(?=\n\n|\Z)',
    ]

    for pattern in patterns_to_remove:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)

    return text.strip()


def extract_main_content(soup):
    """
    Extrait le contenu principal en trouvant le meilleur conteneur,
    puis en nettoyant les éléments non pertinents à l'intérieur de celui-ci.
    """
    best_candidate = None
    best_candidate_len = 0

    # Chercher le contenu principal dans l'ordre de priorité
    for selector in ['article', 'main', '[role="main"]',
                     '.post-content', '.entry-content', '.article-content',
                     '#content', '.content', '.mw-parser-output']:
        content_elem = soup.select_one(selector)
        if content_elem:
            # Utiliser une copie pour ne pas modifier le soup original prématurément
            temp_elem = BeautifulSoup(str(content_elem), 'lxml')
            current_len = len(temp_elem.get_text(strip=True))
            if current_len > best_candidate_len:
                best_candidate = content_elem
                best_candidate_len = current_len

    # Si aucun bon candidat n'est trouvé, on se rabat sur le body
    if not best_candidate or best_candidate_len < 150:
        target_element = soup.body
        if not target_element: return ""
    else:
        target_element = best_candidate

    # Maintenant, on nettoie l'élément cible (le meilleur candidat ou le body)
    # C'est plus sûr car on ne risque pas de supprimer le conteneur principal.
    for tag in target_element.select(
        'nav, header, footer, aside, form, script, style, '
        '.sidebar, .widget, .social-share, .related-posts, '
        '.comments, .comment, .advertisement, .ad, .ads, '
        '[class*="share"], [class*="related"], [class*="sidebar"], '
        '[class*="widget"], [class*="promo"], [aria-hidden="true"]'
    ):
        tag.decompose()

    return target_element.get_text(separator=' ', strip=True)


def create_excerpt(content, max_length=250):
    """Crée un extrait court et pertinent du contenu"""
    if not content:
        return ""

    # Divise en phrases
    sentences = re.split(r'(?<=[.!?])\s+', content)
    excerpt = ""

    for sentence in sentences:
        # Ignore les phrases trop courtes (probablement du bruit)
        if len(sentence.strip()) < 20:
            continue

        # Ajoute la phrase si on ne dépasse pas la limite
        if len(excerpt) + len(sentence) <= max_length:
            excerpt += sentence + " "
        else:
            break

    # Si aucune phrase valide trouvée, prend le début
    if not excerpt.strip():
        excerpt = content[:max_length]

    # Nettoie et ajoute des points de suspension si tronqué
    excerpt = excerpt.strip()
    if len(content) > len(excerpt):
        excerpt = excerpt.rstrip('.!?') + '...'

    return excerpt


def clean_text(text, max_length=3000):
    """Nettoie le texte extrait"""
    if not text:
        return ""

    # Supprime les espaces multiples et les sauts de ligne
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[\r\n\t]', ' ', text)

    # Supprime les patterns répétitifs
    text = remove_common_patterns(text)

    return text.strip()[:max_length]


def extract_images(soup, base_url):
    """Extrait les images avec leurs descriptions."""
    images = []
    seen_urls = set()
    for img in soup.select('img[alt]'):
        if len(images) >= 5:
            break
        src = img.get('src') or img.get('data-src')
        alt = img.get('alt', '').strip()
        if src and alt and len(alt) > 3:
            full_url = urljoin(base_url, src)
            if full_url not in seen_urls:
                images.append({
                    'url': full_url,
                    'alt': alt,
                    'description': alt
                })
                seen_urls.add(full_url)
    return images


# ---------------------------
# Crawl + envoi MeiliSearch
# ---------------------------
def crawl_site(site):
    base_url = site["crawl"].replace("*", "")
    to_visit = [normalize_url(base_url)]
    visited = set()
    max_pages = site.get("max_pages", 200)
    depth = site.get("depth", 3)
    exclude_patterns = site.get("exclude", [])

    logger.info(f"Starting crawl for '{site['name']}' -> {base_url}")

    cache = load_cache()
    pages_crawled, pages_skipped, pages_updated = 0, 0, 0
    documents_to_index = []

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; KidSearch-Crawler/1.0)',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    }

    while to_visit and pages_crawled < max_pages:
        url = to_visit.pop(0)
        if url in visited:
            continue

        # Vérifier si l'URL est exclue
        if is_excluded(url, exclude_patterns):
            logger.debug(f"🚫 Excluded URL: {url}")
            continue

        logger.debug(f"Fetching: {url}")
        try:
            response = requests.get(url, timeout=10, headers=headers)
            if response.status_code != 200:
                continue
        except requests.exceptions.RequestException as e:
            logger.error(f"Exception fetching {url}: {e}")
            continue

        visited.add(url)
        pages_crawled += 1

        try:
            soup = BeautifulSoup(response.content, "lxml")
            title = soup.title.string.strip() if soup.title and soup.title.string else "Sans titre"

            # Ne supprimer que les scripts et styles, le reste est géré par extract_main_content
            for tag in soup(["script", "style"]):
                tag.decompose()

            # Extraire et nettoyer le contenu
            raw_content = extract_main_content(soup)
            content = clean_text(raw_content)

            # Créer l'excerpt
            excerpt = create_excerpt(content, max_length=250)

            # Extraire les images
            images = extract_images(soup, url)

            # Générer le hash
            content_hash = get_content_hash(content, title, images, excerpt)
            doc_id = generate_doc_id(url)

            # Vérifier si on doit indexer
            should_index = not should_skip_page(url, content_hash, cache)

            if should_index and len(content) >= 50:
                pages_updated += 1
                logger.info(f"Indexed ({pages_updated}/{max_pages}): {url}")

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

                # Indexation par batch
                if len(documents_to_index) >= 10:
                    index.add_documents(documents_to_index)
                    documents_to_index = []
                    save_cache(cache)
            else:
                if should_index:
                    # Si c'est la première page du crawl et qu'elle est trop courte, c'est bon à savoir.
                    if url == base_url:
                        logger.warning(f"⚠️  Skipped entrypoint (content too short, < 50 chars): {url}")
                    else:
                        logger.debug(f"Skipped (content too short): {url}")
                else:
                    pages_skipped += 1
                    logger.debug(f"Skipped (cached): {url}")

            # IMPORTANT : Extraire les liens MÊME SI LA PAGE EST EN CACHE
            if depth > 1:
                for link in soup.find_all("a", href=True):
                    href = link.get('href')
                    if href:
                        # Normaliser l'URL pour supprimer les fragments (#)
                        full_url = normalize_url(urljoin(url, href))
                        if (is_same_domain(full_url, base_url) and
                                full_url not in visited and
                                full_url not in to_visit and
                                not is_excluded(full_url, exclude_patterns)):
                            to_visit.append(full_url)

        except Exception as e:
            logger.error(f"Error processing {url}: {e}")
            continue

        time.sleep(1)

    # Indexer les documents restants
    if documents_to_index:
        index.add_documents(documents_to_index)

    save_cache(cache)
    logger.info(f"Finished crawling '{site['name']}'")
    logger.info(f"   Total pages visited: {pages_crawled}, Indexed: {pages_updated}, Skipped: {pages_skipped}")


# ---------------------------
# Boucle principale
# ---------------------------
if __name__ == "__main__":
    for i, site in enumerate(sites, 1):
        logger.info(f"\n{'=' * 50}")
        logger.info(f"🌐 [{i}/{len(sites)}] Crawling: {site['name']}")
        logger.info(f"{'=' * 50}")
        try:
            crawl_site(site)
        except Exception as e:
            logger.error(f"❌ Error crawling {site['name']}: {e}")
        if i < len(sites):
            time.sleep(5)

    logger.info("\n🎉 All sites processed!")