import time
import logging
import os
from typing import List, Optional, Tuple
import numpy as np
import requests
from cachetools import LRUCache


from ..models import SearchResult

logger = logging.getLogger(__name__)


class HuggingFaceAPIReranker:
    """
    Semantic reranker using TEI (Text Embeddings Inference) on Synology DS220+.
    Optimized for CPU inference with multilingual-e5-small model.
    """

    def __init__(self, api_url: str, model_name: Optional[str] = None):
        self.api_url = api_url
        self.model_name = model_name
        # Optimized for DS220+ (Celeron J4025, 2 cores)
        self.batch_size = int(os.getenv("RERANKER_BATCH_SIZE", "4"))
        self.max_chars = int(os.getenv("RERANKER_MAX_CHARS", "256"))
        self.timeout = int(os.getenv("RERANKER_TIMEOUT", "10"))
        self._initialized = False
        # Increase cache for better hit rate
        self._embedding_cache = LRUCache(maxsize=int(os.getenv("RERANKER_CACHE_SIZE", "2048")))

        # Educational domains for KidSearch boost
        self.kid_friendly_domains = [
            'vikidia.org',
            'wikipedia.org',
            'wikimini.org',
            'kiddle.co',
            'education.fr',
            'lumni.fr',
            '1jour1actu.com',
            'jeuxpedago.com',
        ]

        self.initialize()

    def initialize(self):
        """Check TEI API connectivity once at startup."""
        if self._initialized:
            return

        if not self.api_url:
            logger.warning("RERANKER_API_URL is not set. Reranking will be disabled.")
            return

        try:
            # TEI info endpoint
            base_url = self.api_url.rsplit('/', 1)[0]
            info_url = f"{base_url}/info"
            logger.info(f"Connecting to TEI API at {info_url}...")
            response = requests.get(info_url, timeout=5)
            response.raise_for_status()
            info = response.json()

            api_model = info.get('model_id')
            max_batch = info.get('max_client_batch_size', 'unknown')
            max_tokens = info.get('max_input_length', 'unknown')

            logger.info(
                f"TEI API connected - Model: {api_model}, "
                f"Max batch: {max_batch}, Max tokens: {max_tokens}"
            )

            if self.model_name and self.model_name != api_model:
                logger.warning(
                    f"Configured model '{self.model_name}' differs from API model '{api_model}'"
                )

            # Adjust batch size if API has limits
            if isinstance(max_batch, int) and max_batch < self.batch_size:
                logger.info(f"Reducing batch_size from {self.batch_size} to {max_batch}")
                self.batch_size = max_batch

            self._initialized = True

        except Exception as e:
            logger.error(f"Failed to connect to TEI API: {e}")
            self._initialized = False

    def _truncate(self, text: str) -> str:
        """Limit text length to reduce CPU load and stay within token limits."""
        if not text:
            return ""
        # multilingual-e5-small has 512 token limit, be conservative
        return text[:self.max_chars]

    def _get_embeddings_batch(self, texts: List[str]) -> List[Optional[np.ndarray]]:
        """
        Get embeddings for multiple texts in a single API call.
        This is the CORRECT way to use TEI batch API.
        """
        if not texts:
            return []

        # Check cache first
        results = []
        uncached_texts = []
        uncached_indices = []

        for i, text in enumerate(texts):
            if text in self._embedding_cache:
                results.append(self._embedding_cache[text])
            else:
                results.append(None)
                uncached_texts.append(text)
                uncached_indices.append(i)

        # If all cached, return early
        if not uncached_texts:
            logger.debug(f"All {len(texts)} embeddings from cache")
            return results

        # Batch API call for uncached texts
        try:
            logger.debug(f"Fetching {len(uncached_texts)} embeddings (batch)")
            response = requests.post(
                self.api_url,
                json={
                    "inputs": uncached_texts,
                    "normalize": True,
                    "truncate": True
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            embeddings = response.json()

            # Store in cache and results
            for idx, emb_list in zip(uncached_indices, embeddings):
                emb = np.array(emb_list, dtype=np.float32)  # float32 saves memory
                self._embedding_cache[texts[idx]] = emb
                results[idx] = emb

            logger.debug(f"Successfully embedded {len(uncached_texts)} texts")

        except requests.Timeout:
            logger.warning(f"TEI batch timeout ({self.timeout}s) for {len(uncached_texts)} texts")
        except Exception as e:
            logger.error(f"TEI batch embedding failed: {e}")

        return results

    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get single embedding (uses batch API internally)."""
        if not text:
            return None

        results = self._get_embeddings_batch([text])
        return results[0] if results else None

    def rerank(self, query: str, results: List[SearchResult], top_k: int) -> List[SearchResult]:
        """
        Rerank results using semantic similarity.
        Optimized for DS220+ with proper batch processing.
        """
        if not self._initialized or not results:
            return results[:top_k]

        logger.info(f"Reranking {len(results)} results for query: '{query[:50]}...'")

        cache_hits = 0
        api_calls = 0
        start_time = time.time()

        try:
            # 1️⃣ Get query embedding
            query_embedding = self._get_embedding(query)
            if query_embedding is None:
                logger.warning("Query embedding failed, returning original results")
                return results[:top_k]
            api_calls += 1

            # 2️⃣ Prepare document embeddings
            doc_embeddings = [None] * len(results)
            texts_to_embed = []
            indices_to_fill = []

            for i, r in enumerate(results):
                # Use pre-computed vectors if available
                if r.vectors and isinstance(r.vectors, list):
                    emb = np.array(r.vectors, dtype=np.float32)
                    # Ensure normalized
                    norm = np.linalg.norm(emb)
                    doc_embeddings[i] = emb / norm if norm > 0 else emb
                    cache_hits += 1
                else:
                    # Prepare text
                    text = self._truncate(f"{r.title or ''} {r.excerpt or ''}")

                    # Check cache
                    if text in self._embedding_cache:
                        doc_embeddings[i] = self._embedding_cache[text]
                        cache_hits += 1
                    else:
                        texts_to_embed.append(text)
                        indices_to_fill.append(i)

            # 3️⃣ Get missing embeddings using TRUE batch API
            if texts_to_embed:
                # Process in batches (respecting batch_size limit)
                for batch_start in range(0, len(texts_to_embed), self.batch_size):
                    batch_end = min(batch_start + self.batch_size, len(texts_to_embed))
                    batch_texts = texts_to_embed[batch_start:batch_end]
                    batch_indices = indices_to_fill[batch_start:batch_end]

                    # Single batch API call
                    batch_embeddings = self._get_embeddings_batch(batch_texts)
                    api_calls += 1

                    # Assign embeddings
                    for local_idx, global_idx in enumerate(batch_indices):
                        if batch_embeddings[local_idx] is not None:
                            doc_embeddings[global_idx] = batch_embeddings[local_idx]

            # 4️⃣ Compute cosine similarities
            valid_embeddings = [(idx, e) for idx, e in enumerate(doc_embeddings) if e is not None]

            if not valid_embeddings:
                logger.warning("No valid embeddings, returning original results")
                return results[:top_k]

            indices, matrix = zip(*valid_embeddings)
            doc_matrix = np.stack(matrix).astype(np.float32)  # float32 for efficiency

            # Normalized cosine similarity
            query_norm = np.linalg.norm(query_embedding)
            if query_norm > 0:
                query_normalized = (query_embedding / query_norm).astype(np.float32)
                cosine_scores = doc_matrix @ query_normalized
            else:
                cosine_scores = np.zeros(len(indices), dtype=np.float32)

            # 5️⃣ Update scores
            score_changes = []
            for idx, score in zip(indices, cosine_scores):
                results[idx].original_score = results[idx].score
                new_score = float(score)
                results[idx].score = new_score
                score_changes.append(abs(new_score - results[idx].original_score))

            # Documents without embeddings: keep original score with penalty
            for i, e in enumerate(doc_embeddings):
                if e is None:
                    results[i].original_score = results[i].score
                    results[i].score = results[i].score * 0.3

            # 6️⃣ KidSearch boost for educational content
            boost_count = 0
            for r in results:
                if self._is_kid_friendly(r):
                    r.score *= 1.15
                    boost_count += 1

            # 7️⃣ Sort and limit
            results.sort(key=lambda x: x.score, reverse=True)

            # Log metrics
            elapsed_ms = (time.time() - start_time) * 1000
            avg_change = np.mean(score_changes) if score_changes else 0
            cache_rate = cache_hits / len(results) * 100 if results else 0

            logger.info(
                f"Reranking done in {elapsed_ms:.1f}ms: "
                f"cache_hits={cache_hits}/{len(results)} ({cache_rate:.1f}%), "
                f"api_calls={api_calls}, "
                f"kid_boost={boost_count}, "
                f"avg_score_Δ={avg_change:.3f}"
            )

            return results[:top_k]

        except Exception as e:
            logger.error(f"Reranking failed: {e}", exc_info=True)
            return results[:top_k]

    def _is_kid_friendly(self, result: SearchResult) -> bool:
        """Check if result is from educational/kid-friendly domain."""
        url_lower = str(result.url).lower()  # ✅ FIXED
        return any(domain in url_lower for domain in self.kid_friendly_domains)


