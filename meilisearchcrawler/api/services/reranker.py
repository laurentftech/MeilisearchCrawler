"""
Semantic reranking service using an external Hugging Face Inference API.
Reranks search results based on semantic similarity to the query.
"""

import logging
import os
from typing import List, Optional
import numpy as np
import requests

from ..models import SearchResult

logger = logging.getLogger(__name__)


class HuggingFaceAPIReranker:
    """
    Semantic reranker using a Hugging Face Inference API endpoint.
    """

    def __init__(self, api_url: str, model_name: Optional[str] = None):
        """
        Initialize reranker with an API URL.

        Args:
            api_url: URL of the /embed endpoint for the inference API.
            model_name: Optional, name of the expected HuggingFace model for logging.
        """
        self.api_url = api_url
        self.model_name = model_name
        self.batch_size = int(os.getenv("RERANKER_BATCH_SIZE", "32"))
        self._initialized = False
        self.initialize()

    def initialize(self):
        """
        Lazy load and check the connection to the API.
        """
        if self._initialized:
            return

        if not self.api_url:
            logger.warning("RERANKER_API_URL is not set. Reranking will be disabled.")
            self._initialized = False
            return

        try:
            # Get base url from http://.../embed
            base_url = self.api_url.rsplit('/', 1)[0]
            info_url = f"{base_url}/info"
            
            logger.info(f"Connecting to Reranker API at {info_url}...")
            response = requests.get(info_url, timeout=5)
            response.raise_for_status()
            info = response.json()
            
            api_model = info.get('model_id')
            logger.info(f"Reranker API connected. Model: {api_model}")

            if self.model_name and self.model_name != api_model:
                logger.warning(f"Configured reranker model '{self.model_name}' differs from API model '{api_model}'.")

            self._initialized = True
            logger.info("Hugging Face API Reranker initialized successfully.")

        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to connect to reranker API at {self.api_url}: {e}")
            self._initialized = False # Ensure it stays uninitialized
            # We don't raise here, so the app can start. Reranking will be skipped.
        except Exception as e:
            logger.error(f"Failed to initialize reranker: {e}", exc_info=True)
            self._initialized = False

    def rerank(self, query: str, results: List[SearchResult], top_k: int) -> List[SearchResult]:
        """Rerank results using embeddings similarity, using MeiliSearch _vectors if available and caching API calls."""
        if not self._initialized or not results:
            return results[:top_k]

        logger.info(f"Reranking {len(results)} results for query: '{query[:50]}...'")
        try:
            # 1️⃣ Obtenir l'embedding de la query via l'API
            query_response = requests.post(
                self.api_url,
                json={"inputs": [query], "normalize": True},
                timeout=10
            )
            query_response.raise_for_status()
            query_embedding = np.array(query_response.json()[0])

            # 2️⃣ Préparer les embeddings des documents
            # On sépare les documents qui ont déjà un vecteur de ceux qui n'en ont pas.
            doc_embeddings = [None] * len(results)
            texts_to_embed = []
            indices_to_fill = []

            for i, r in enumerate(results):
                # a) Si _vectors de MeiliSearch est disponible, on l'utilise en priorité
                if r.vectors and isinstance(r.vectors, list):
                    doc_embeddings[i] = np.array(r.vectors)
                else:
                    # b) Sinon, on prépare le texte pour une requête groupée (batch)
                    texts_to_embed.append(f"{r.title} {r.excerpt}")
                    indices_to_fill.append(i)

            # 3️⃣ Si des embeddings sont manquants, on les génère en une seule requête API
            if texts_to_embed:
                logger.debug(f"Fetching {len(texts_to_embed)} missing embeddings in one batch...")
                # Diviser en plusieurs batches si nécessaire pour éviter "Payload Too Large"
                for i in range(0, len(texts_to_embed), self.batch_size):
                    batch_texts = texts_to_embed[i:i + self.batch_size]
                    batch_indices = indices_to_fill[i:i + self.batch_size]
                    
                    logger.debug(f"  - Processing batch {i//self.batch_size + 1} of size {len(batch_texts)}")
                    try:
                        doc_response = requests.post(
                            self.api_url,
                            json={"inputs": batch_texts, "normalize": True, "truncate": True},
                            timeout=20  # Timeout plus long pour les gros batches
                        )
                        doc_response.raise_for_status()
                        generated_embeddings = doc_response.json()

                        # On remplit les "trous" dans notre liste d'embeddings
                        for j, emb_values in enumerate(generated_embeddings):
                            original_index = batch_indices[j]
                            doc_embeddings[original_index] = np.array(emb_values)
                    except Exception as api_error:
                        logger.error(f"API call for batch embeddings failed: {api_error}")
                        # En cas d'échec sur un batch, on continue avec ce qu'on a,
                        # plutôt que de tout abandonner.
                        continue

            # 4️⃣ Calculer les similarités cosinus
            # On filtre les embeddings qui n'ont pas pu être générés
            scores = [float(np.dot(query_embedding, doc_emb)) if doc_emb is not None else -1.0 for doc_emb in doc_embeddings]

            # 5️⃣ Appliquer le reranking
            for idx, result in enumerate(results):
                result.original_score = result.score
                result.score = scores[idx]

            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.error(f"Reranking failed: {e}", exc_info=True)
            return results[:top_k]

# TODO: Implement query expansion
# - Synonym expansion for children's queries
# - Spelling correction
# - Age-appropriate query reformulation

# TODO: Implement caching for common queries
# - Cache embeddings for frequent queries
# - Cache embeddings for stable results (indexed content)
