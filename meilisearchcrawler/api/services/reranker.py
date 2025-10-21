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
        """Rerank results using embeddings similarity."""
        try:
            # Encoder la requête
            query_response = requests.post(
                self.api_url.replace('/rerank', '/embed'),  # Utiliser /embed
                json={"inputs": [query], "normalize": True},
                timeout=5
            )
            query_response.raise_for_status()
            query_embedding = query_response.json()[0]

            # Encoder tous les documents
            texts = [f"{r.title} {r.excerpt}" for r in results]
            docs_response = requests.post(
                self.api_url.replace('/rerank', '/embed'),
                json={"inputs": texts, "normalize": True},
                timeout=10
            )
            docs_response.raise_for_status()
            doc_embeddings = docs_response.json()

            # Calculer similarité cosinus
            import numpy as np
            query_vec = np.array(query_embedding)
            scores = [np.dot(query_vec, np.array(doc_emb)) for doc_emb in doc_embeddings]

            # Réordonner par score
            for idx, result in enumerate(results):
                result.original_score = result.score
                result.score = float(scores[idx])

            results.sort(key=lambda x: x.score, reverse=True)
            return results[:top_k]

        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            return results[:top_k]  # Fallback sans reranking

# TODO: Implement query expansion
# - Synonym expansion for children's queries
# - Spelling correction
# - Age-appropriate query reformulation

# TODO: Implement caching for common queries
# - Cache embeddings for frequent queries
# - Cache embeddings for stable results (indexed content)
