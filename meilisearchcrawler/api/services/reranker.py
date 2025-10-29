import time
import logging
import os
from typing import List, Optional
import numpy as np

from ..models import SearchResult

logger = logging.getLogger(__name__)


class HuggingFaceAPIReranker:
    """
    Semantic reranker that computes cosine similarity between a query and documents.
    It assumes that embeddings are already computed and present in the SearchResult objects.
    """

    def __init__(self):
        # This class no longer connects to the API, it just does computation.
        # Configuration can be simplified or removed if not needed for other purposes.
        logger.info("Reranker initialized. Ready to perform calculations.")

    def rerank(self, query: str, results: List[SearchResult], top_k: int, query_embedding: Optional[np.ndarray] = None) -> List[SearchResult]:
        """
        Rerank results using semantic similarity.

        Args:
            query: The search query string (used for logging).
            results: A list of SearchResult objects, expected to have embeddings.
            top_k: The number of results to return.
            query_embedding: The pre-computed embedding for the query.

        Returns:
            A sorted list of SearchResult objects.
        """
        if query_embedding is None or not results:
            logger.warning("Query embedding not provided or no results to rerank. Returning original order.")
            return results[:top_k]

        logger.info(f"Reranking {len(results)} results for query: '{query[:50]}...'")
        start_time = time.time()

        try:
            # 1. Prepare document embeddings matrix
            doc_embeddings = []
            valid_indices = []
            for i, r in enumerate(results):
                if r.vectors and isinstance(r.vectors, list):
                    doc_embeddings.append(r.vectors)
                    valid_indices.append(i)
            
            if not doc_embeddings:
                logger.warning("No valid document embeddings found. Returning original order.")
                return results[:top_k]

            doc_matrix = np.array(doc_embeddings, dtype=np.float32)

            # 2. Normalize embeddings for cosine similarity
            query_norm = np.linalg.norm(query_embedding)
            doc_norms = np.linalg.norm(doc_matrix, axis=1)

            # Avoid division by zero
            doc_norms[doc_norms == 0] = 1e-9

            query_normalized = (query_embedding / query_norm).astype(np.float32)
            doc_matrix_normalized = (doc_matrix / doc_norms[:, np.newaxis]).astype(np.float32)

            # 3. Compute cosine similarities
            cosine_scores = doc_matrix_normalized @ query_normalized

            # 4. Update scores
            for i, score in enumerate(cosine_scores):
                original_index = valid_indices[i]
                results[original_index].original_score = results[original_index].score
                results[original_index].score = float(score)

            # Penalize results without embeddings
            for i, r in enumerate(results):
                if not r.vectors:
                    r.score *= 0.1 # Penalize heavily

            # 5. Sort and limit
            results.sort(key=lambda x: x.score, reverse=True)

            elapsed_ms = (time.time() - start_time) * 1000
            logger.info(f"Reranking calculation finished in {elapsed_ms:.1f}ms.")

            return results[:top_k]

        except Exception as e:
            logger.error(f"Reranking calculation failed: {e}", exc_info=True)
            return results[:top_k]
