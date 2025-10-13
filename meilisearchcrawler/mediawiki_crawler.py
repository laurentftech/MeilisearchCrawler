# meilisearchcrawler/mediawiki_crawler.py
# Extension pour crawler Vikidia/Wikipedia via leur API avec embeddings

import aiohttp
import asyncio
from typing import Dict, List, Optional
from urllib.parse import urljoin
import logging
from datetime import datetime
import time
from google import genai

logger = logging.getLogger(__name__)


class MediaWikiCrawler:
    """Crawler optimisé pour les wikis utilisant MediaWiki (Vikidia, Wikipedia)"""

    def __init__(self, context):
        self.context = context
        self.site_config = context.site
        self.api_url = self.site_config.get('api_url', self._build_api_url())
        self.namespaces = self.site_config.get('namespaces', [0])  # 0 = articles principaux
        self.batch_size = self.site_config.get('api_batch_size', 50)

        # Initialiser le client Gemini si disponible
        self.gemini_client = None
        self.embedding_model = "text-embedding-004"

        # Récupérer la clé Gemini depuis les variables d'environnement
        import os
        gemini_api_key = os.getenv('GEMINI_API_KEY')

        if gemini_api_key:
            try:
                self.gemini_client = genai.Client(api_key=gemini_api_key)
                logger.info("✓ Client Gemini initialisé pour les embeddings")
            except Exception as e:
                logger.warning(f"⚠️  Impossible d'initialiser Gemini: {e}")
                logger.warning("   Les documents seront indexés SANS embeddings")
        else:
            logger.warning("⚠️  GEMINI_API_KEY non trouvée - embeddings désactivés")

    def _build_api_url(self) -> str:
        """Construit l'URL de l'API à partir de l'URL du wiki"""
        base_url = self.site_config['crawl']
        # https://fr.vikidia.org/wiki/Accueil -> https://fr.vikidia.org/w/api.php
        if '/wiki/' in base_url:
            return base_url.split('/wiki/')[0] + '/w/api.php'
        return base_url.rstrip('/') + '/w/api.php'

    async def get_all_page_ids(self, session: aiohttp.ClientSession) -> List[int]:
        """Récupère tous les IDs de pages du wiki (SEULEMENT les articles du namespace spécifié)"""
        logger.info(f"📋 Récupération de la liste des articles depuis {self.api_url}")
        logger.info(f"   Namespace(s): {self.namespaces} (0 = articles principaux)")

        all_page_ids = []
        continue_token = None

        while True:
            params = {
                'action': 'query',
                'list': 'allpages',
                'aplimit': 'max',  # 500 par requête
                'apnamespace': '|'.join(map(str, self.namespaces)),
                'apfilterredir': 'nonredirects',  # IMPORTANT: ignorer les redirections
                'format': 'json'
            }

            if continue_token:
                params['apcontinue'] = continue_token

            try:
                await self.context.rate_limiter.wait()
                async with session.get(self.api_url, params=params) as response:
                    response.raise_for_status()
                    data = await response.json()

                    pages = data.get('query', {}).get('allpages', [])
                    page_ids = [page['pageid'] for page in pages]
                    all_page_ids.extend(page_ids)

                    logger.info(f"   → {len(all_page_ids)} articles listés...")

                    # Vérifier s'il y a plus de pages
                    if 'continue' in data:
                        continue_token = data['continue'].get('apcontinue')
                    else:
                        break

            except Exception as e:
                logger.error(f"❌ Erreur lors de la récupération de la liste: {e}")
                break

        logger.info(f"✅ {len(all_page_ids)} articles trouvés (namespace {self.namespaces}, sans redirections)")
        return all_page_ids

    def get_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """Génère des embeddings pour un lot de textes"""
        if not self.gemini_client:
            return [[] for _ in texts]

        try:
            result = self.gemini_client.models.embed_content(
                model=self.embedding_model,
                contents=texts
            )
            return [embedding.values for embedding in result.embeddings]
        except Exception as e:
            if "quota" in str(e).lower():
                logger.error(f"🛑 Quota Gemini dépassé: {e}")
            else:
                logger.error(f"❌ Erreur API Gemini: {e}")
            return [[] for _ in texts]

    async def fetch_pages_batch(self, session: aiohttp.ClientSession,
                                page_ids: List[int]) -> List[Dict]:
        """Récupère le contenu de plusieurs pages en une seule requête"""
        if not page_ids:
            return []

        params = {
            'action': 'query',
            'pageids': '|'.join(map(str, page_ids)),
            'prop': 'extracts|info|pageimages|revisions',
            'explaintext': 1,
            'exsectionformat': 'plain',
            'rvprop': 'content',
            'inprop': 'url',
            'piprop': 'thumbnail',
            'pithumbsize': 500,
            'format': 'json'
        }

        try:
            await self.context.rate_limiter.wait()
            async with session.get(self.api_url, params=params, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                data = await response.json()

                pages = data.get('query', {}).get('pages', {})
                documents = []

                stats = {'total': len(pages), 'missing': 0, 'redirect': 0,
                         'wrong_namespace': 0, 'unsafe': 0, 'stub': 0, 'ok': 0}

                for page_id, page_data in pages.items():
                    if 'missing' in page_data:
                        stats['missing'] += 1
                        continue
                    if 'redirect' in page_data:
                        stats['redirect'] += 1
                        continue

                    title = page_data.get('title', '')
                    content = page_data.get('extract') or \
                              page_data.get('revisions', [{}])[0].get('*', '')
                    url = page_data.get('fullurl', '')

                    namespace = page_data.get('ns', -1)
                    if namespace not in self.namespaces:
                        stats['wrong_namespace'] += 1
                        continue

                    if not self._is_safe_content(title, content):
                        stats['unsafe'] += 1
                        continue

                    content = self._clean_content(content)

                    if len(content.strip()) < 50:
                        stats['stub'] += 1
                        continue

                    stats['ok'] += 1
                    excerpt = self._create_excerpt(content)

                    images = []
                    if 'thumbnail' in page_data:
                        images.append({
                            'url': page_data['thumbnail']['source'],
                            'alt': title,
                            'description': title
                        })

                    documents.append({
                        'page_id': int(page_id),
                        'title': title,
                        'content': content,
                        'excerpt': excerpt,
                        'url': url,
                        'images': images
                    })

                if (stats['stub'] > 10 or stats['unsafe'] > 0) and len(pages) == self.batch_size:
                    logger.info(
                        f"   📊 Batch: {stats['ok']}/{stats['total']} retenus | Stubs/vides: {stats['stub']} | Non sûrs: {stats['unsafe']}")

                return documents

        except asyncio.TimeoutError:
            logger.warning(f"⏱️ Timeout pour le batch de {len(page_ids)} pages")
            return []
        except Exception as e:
            logger.error(f"❌ Erreur fetch batch: {e}")
            return []

    def _is_safe_content(self, title: str, content: str) -> bool:
        """Filtre le contenu inapproprié pour enfants"""
        unsafe_keywords = [
            'catastrophe de', 'accident de', 'attentat',
            'massacre', 'tuerie', 'génocide'
        ]

        title_lower = title.lower()
        content_preview = content[:500].lower() if content else ''

        for keyword in unsafe_keywords:
            if keyword in title_lower:
                return False

        return True

    def _clean_content(self, content: str) -> str:
        """Nettoie le contenu de l'API MediaWiki"""
        import re

        if not content:
            return ""

        # Supprimer les sections de fin (références, liens externes, etc.)
        patterns = [
            r'==\s*Références?\s*==',
            r'==\s*Liens?\s+externes?\s*==',
            r'==\s*Voir\s+aussi\s*==',
            r'==\s*Sources?\s*==',
            r'==\s*Notes?\s+et\s+références?\s*==',
        ]

        min_pos = len(content)
        for pattern in patterns:
            match = re.search(pattern, content, flags=re.IGNORECASE)
            if match and match.start() < min_pos:
                min_pos = match.start()

        if min_pos < len(content) and min_pos > 500:
            content = content[:min_pos]

        content = re.sub(r'\s+', ' ', content)
        content = content.strip()

        if len(content) > 3000:
            content = content[:3000]

        return content

    def _create_excerpt(self, content: str, max_length: int = 250) -> str:
        """Crée un excerpt du contenu"""
        import re

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

    async def crawl(self) -> List[Dict]:
        """Méthode principale de crawl via l'API MediaWiki"""
        from tqdm.asyncio import tqdm
        import hashlib

        logger.info(f"🚀 Crawl MediaWiki de '{self.site_config['name']}'")
        logger.info(f"   API: {self.api_url}")
        logger.info(f"   Namespaces: {self.namespaces}")
        if self.gemini_client:
            logger.info(f"   🤖 Embeddings: Gemini {self.embedding_model}")
        else:
            logger.warning("   ⚠️  Embeddings: DÉSACTIVÉS (pas de clé Gemini)")

        all_documents = []

        headers = {
            'User-Agent': 'KidSearch-Crawler/2.0 (Educational; Contact: your-email@example.com)'
        }

        async with aiohttp.ClientSession(headers=headers) as session:
            # 1. Récupérer tous les IDs de pages
            page_ids = await self.get_all_page_ids(session)

            if not page_ids:
                logger.error("❌ Aucune page trouvée")
                return []

            # Limiter si max_pages est défini
            max_pages = self.site_config.get('max_pages', 0)
            if max_pages > 0 and len(page_ids) > max_pages:
                logger.info(f"⚠️  Limitation à {max_pages} pages (sur {len(page_ids)})")
                page_ids = page_ids[:max_pages]

            # 2. Récupérer le contenu par batches
            logger.info(f"📦 Récupération du contenu par batches de {self.batch_size}...")

            batches = [page_ids[i:i + self.batch_size]
                       for i in range(0, len(page_ids), self.batch_size)]

            self.context.stats.pbar = tqdm(
                total=len(page_ids),
                desc=f"🔍 {self.site_config['name']}",
                unit="pages"
            )

            for batch in batches:
                documents = await self.fetch_pages_batch(session, batch)

                if not documents:
                    await self.context.stats.increment('pages_visited', len(batch))
                    self.context.stats.pbar.update(len(batch))
                    continue

                # Préparer les textes pour les embeddings
                texts_to_embed = []
                docs_for_indexing = []

                for doc in documents:
                    content_hash = hashlib.md5(
                        f"{doc['title']}|{doc['content']}".encode()
                    ).hexdigest()

                    doc_id = hashlib.md5(doc['url'].encode()).hexdigest()

                    should_index = (
                            self.context.force_recrawl or
                            not self._should_skip_page(doc['url'], content_hash)
                    )

                    if should_index:
                        # Texte pour l'embedding : titre + contenu
                        text_for_embedding = f"{doc['title']}\n{doc['content']}"
                        texts_to_embed.append(text_for_embedding)
                        docs_for_indexing.append((doc, doc_id, content_hash))
                    else:
                        await self.context.stats.increment('pages_skipped_cache')

                # Générer tous les embeddings en une seule requête
                embeddings = []
                if texts_to_embed and self.gemini_client:
                    try:
                        embeddings = self.get_embeddings_batch(texts_to_embed)
                        if embeddings and len(embeddings) != len(texts_to_embed):
                            logger.warning(
                                f"⚠️  Nombre d'embeddings ({len(embeddings)}) != documents ({len(texts_to_embed)})")
                            embeddings = []
                    except Exception as e:
                        logger.error(f"❌ Erreur génération embeddings: {e}")
                        embeddings = []

                # Créer les documents finaux avec embeddings
                now_iso = datetime.now().isoformat()

                for idx, (doc, doc_id, content_hash) in enumerate(docs_for_indexing):
                    final_doc = {
                        "id": doc_id,
                        "site": self.site_config["name"],
                        "url": doc['url'],
                        "title": doc['title'],
                        "excerpt": doc['excerpt'],
                        "content": doc['content'],
                        "images": doc['images'],
                        "lang": self.site_config.get("lang", "fr"),
                        "timestamp": int(time.time()),
                        "indexed_at": now_iso,
                        "last_crawled_at": now_iso,
                        "content_hash": content_hash,
                    }

                    # Ajouter l'embedding si disponible
                    if embeddings and idx < len(embeddings) and embeddings[idx]:
                        final_doc["_vectors"] = {
                            "default": embeddings[idx]
                        }

                    all_documents.append(final_doc)
                    await self.context.stats.increment('pages_indexed')

                    # Mettre à jour le cache
                    async with self.context.cache_lock:
                        self.context.cache[doc['url']] = {
                            'content_hash': content_hash,
                            'last_crawl': time.time(),
                            'doc_id': doc_id,
                            'crawl_date': now_iso
                        }

                await self.context.stats.increment('pages_visited', len(batch))
                self.context.stats.pbar.update(len(batch))

            self.context.stats.pbar.close()

        logger.info(f"✅ {len(all_documents)} documents à indexer")
        if self.gemini_client:
            docs_with_embeddings = sum(1 for doc in all_documents if '_vectors' in doc)
            logger.info(f"   🤖 {docs_with_embeddings} documents avec embeddings")

        return all_documents

    def _should_skip_page(self, url: str, content_hash: str) -> bool:
        """Vérifie si la page doit être ignorée (cache)"""
        if url not in self.context.cache:
            return False

        cached_data = self.context.cache[url]
        if cached_data.get('content_hash') == content_hash:
            last_crawl = cached_data.get('last_crawl', 0)
            from meilisearchcrawler.crawler import config
            days_ago = (time.time() - last_crawl) / (24 * 3600)
            if days_ago < config.CACHE_DAYS:
                return True

        return False