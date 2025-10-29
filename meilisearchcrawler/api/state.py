from typing import Optional, List

from .services.meilisearch_client import MeilisearchClient
from .services.cse_client import CSEClient
from .services.wiki_client import WikiClient
from .services.safety import SafetyFilter
from .services.merger import SearchMerger
from .services.reranker import HuggingFaceAPIReranker
from .services.stats_db import StatsDatabase
from ..embeddings import EmbeddingProvider


class AppState:
    """A class to hold the application state with type hints for static analysis."""
    meilisearch_client: Optional[MeilisearchClient] = None
    wiki_clients: List[WikiClient] = []  # Support multiple wiki instances
    safety_filter: Optional[SafetyFilter] = None
    merger: Optional[SearchMerger] = None
    cse_client: Optional[CSEClient] = None
    reranker: Optional[HuggingFaceAPIReranker] = None
    embedding_provider: Optional[EmbeddingProvider] = None
    stats_db: Optional[StatsDatabase] = None
