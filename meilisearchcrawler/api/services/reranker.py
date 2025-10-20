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


    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Rerank search results based on semantic similarity to query.

        Process:
        1. Generate embeddings for the query and all results in a single API call.
        2. Calculate cosine similarity between query embedding and each result embedding.
        3. Blend with original scores.
        4. Re-sort by blended score.

        Args:
            query: Search query
            results: Results to rerank
            top_k: Return only top K results (None = all)

        Returns:
            Reranked results with updated scores, or original results if reranking fails.
        """

        if not results or not self._initialized:
            if not self._initialized:
                logger.warning("Reranker not initialized, skipping reranking.")
            return results

        try:
            logger.info(f"Reranking {len(results)} results for query: '{query}'")

            # Store original scores
            for result in results:
                if result.original_score is None:
                    result.original_score = result.score

            # Prepare texts for the API
            result_texts = [
                f"{r.title} {r.excerpt if r.excerpt else ''}"
                for r in results
            ]
            all_texts = [query] + result_texts

            # Generate embeddings in one call
            response = requests.post(
                self.api_url,
                json={"inputs": all_texts, "normalize": True, "truncate": True},
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            all_embeddings = np.array(response.json(), dtype=np.float32)

            if len(all_embeddings) != len(all_texts):
                 logger.error(f"Mismatch between number of texts sent ({len(all_texts)}) and embeddings received ({len(all_embeddings)}).")
                 return results

            query_embedding = all_embeddings[0]
            result_embeddings = all_embeddings[1:]

            # Calculate cosine similarities
            # Since embeddings are normalized, dot product is equivalent to cosine similarity
            similarities = np.dot(result_embeddings, query_embedding)

            # Blend semantic similarity with original scores
            for i, result in enumerate(results):
                semantic_score = float(similarities[i])
                # Normalize original score to 0-1 range if needed
                original_norm = min(1.0, max(0.0, result.original_score or 0.5))
                
                # Blend: 50% original + 50% semantic (can be made configurable)
                result.score = 0.5 * original_norm + 0.5 * semantic_score

            # Sort by new blended score
            results.sort(key=lambda r: r.score, reverse=True)

            # Limit to top_k
            if top_k:
                results = results[:top_k]

            logger.info(f"Reranking complete, returning {len(results)} results")

            return results

        except requests.exceptions.RequestException as e:
            logger.error(f"Reranking API call failed: {e}")
            return results # Return original results on error
        except Exception as e:
            logger.error(f"Reranking failed: {e}", exc_info=True)
            return results

# TODO: Implement query expansion
# - Synonym expansion for children's queries
# - Spelling correction
# - Age-appropriate query reformulation

# TODO: Implement caching for common queries
# - Cache embeddings for frequent queries
# - Cache embeddings for stable results (indexed content)
