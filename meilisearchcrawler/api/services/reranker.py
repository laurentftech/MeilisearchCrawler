"""
Semantic reranking service using Sentence Transformer models.
Reranks search results based on semantic similarity to query.
"""

import logging
from typing import List, Optional
import numpy as np

from ..models import SearchResult

logger = logging.getLogger(__name__)


class SentenceTransformerReranker:
    """
    Semantic reranker using Sentence Transformer models.
    Runs on CPU for local deployment without GPU requirements.
    """

    def __init__(self, model_name: str = "intfloat/multilingual-e5-base"):
        """
        Initialize reranker with a Sentence Transformer model.

        Args:
            model_name: HuggingFace model name (e.g., 'intfloat/multilingual-e5-base')
        """
        self.model_name = model_name
        self.model = None
        self.tokenizer = None
        self._initialized = False

    def initialize(self):
        """
        Lazy load the model and tokenizer.
        Called on first use to avoid slowing down API startup.
        """
        if self._initialized:
            return

        try:
            logger.info(f"Loading Sentence Transformer model: {self.model_name}")

            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name, trust_remote_code=True, device='cpu')

            self._initialized = True
            logger.info("Sentence Transformer model loaded successfully")

        except Exception as e:
            logger.error(f"Failed to load reranker model: {e}", exc_info=True)
            raise

    def rerank(
        self,
        query: str,
        results: List[SearchResult],
        top_k: Optional[int] = None,
    ) -> List[SearchResult]:
        """
        Rerank search results based on semantic similarity to query.

        Process:
        1. Generate query embedding
        2. Generate embeddings for each result (title + excerpt)
        3. Calculate cosine similarity
        4. Blend with original scores (0.5 semantic + 0.5 original)
        5. Re-sort by blended score

        Args:
            query: Search query
            results: Results to rerank
            top_k: Return only top K results (None = all)

        Returns:
            Reranked results with updated scores
        """

        if not results:
            return results

        # Lazy load model
        if not self._initialized:
            self.initialize()

        try:
            logger.info(f"Reranking {len(results)} results for query: '{query}'")

            # Store original scores
            for result in results:
                if result.original_score is None:
                    result.original_score = result.score

            # Generate query embedding
            query_embedding = self.model.encode(query, convert_to_numpy=True)

            # Generate embeddings for results (title + excerpt)
            result_texts = [
                f"{r.title} {r.excerpt if r.excerpt else ''}"
                for r in results
            ]
            result_embeddings = self.model.encode(result_texts, convert_to_numpy=True)

            # Calculate cosine similarities
            similarities = []
            for result_emb in result_embeddings:
                similarity = self._cosine_similarity(query_embedding, result_emb)
                similarities.append(similarity)

            # Blend semantic similarity with original scores (50/50)
            for i, result in enumerate(results):
                semantic_score = float(similarities[i])
                # Normalize original score to 0-1 range if needed
                original_norm = min(1.0, max(0.0, result.original_score or 0.5))
                # Blend: 50% original + 50% semantic
                result.score = 0.5 * original_norm + 0.5 * semantic_score

            # Sort by new blended score
            results.sort(key=lambda r: r.score, reverse=True)

            # Limit to top_k
            if top_k:
                results = results[:top_k]

            logger.info(f"Reranking complete, returning {len(results)} results")

            return results

        except Exception as e:
            logger.error(f"Reranking failed: {e}", exc_info=True)
            # Return original results on error
            return results

    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Calculate cosine similarity between two vectors.

        Args:
            a: First vector
            b: Second vector

        Returns:
            Cosine similarity (0-1)
        """
        return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


# TODO: Implement query expansion
# - Synonym expansion for children's queries
# - Spelling correction
# - Age-appropriate query reformulation

# TODO: Implement caching for common queries
# - Cache embeddings for frequent queries
# - Cache embeddings for stable results (indexed content)
