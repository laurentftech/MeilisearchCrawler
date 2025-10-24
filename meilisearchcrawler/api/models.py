"""
Pydantic models for API request/response schemas.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl, validator


class SearchSource(str, Enum):
    """Source of search result."""
    MEILISEARCH = "meilisearch"
    GOOGLE_CSE = "google_cse"
    WIKI = "wiki"
    MERGED = "merged"


class Language(str, Enum):
    """Supported languages."""
    FR = "fr"
    EN = "en"
    ALL = "all"


class SearchRequest(BaseModel):
    """Search request parameters."""
    q: str = Field(..., min_length=1, max_length=200, description="Search query")
    lang: Language = Field(default=Language.FR, description="Search language")
    limit: int = Field(default=20, ge=1, le=100, description="Maximum results to return")
    use_cse: bool = Field(default=True, description="Include Google CSE results")
    use_reranking: bool = Field(default=True, description="Apply semantic reranking")

    class Config:
        json_schema_extra = {
            "example": {
                "q": "dinosaures",
                "lang": "fr",
                "limit": 20,
                "use_cse": True,
                "use_reranking": True
            }
        }


class ImageResult(BaseModel):
    """Image in search result."""
    url: HttpUrl
    alt: Optional[str] = None
    description: Optional[str] = None


class SearchResult(BaseModel):
    """Individual search result."""
    id: str = Field(..., description="Unique result ID")
    title: str = Field(..., description="Result title")
    url: HttpUrl = Field(..., description="Result URL")
    excerpt: str = Field(..., description="Result excerpt/description")
    content: Optional[str] = Field(None, description="Full content (optional)")
    site: Optional[str] = Field(None, description="Site name")
    images: List[ImageResult] = Field(default_factory=list, description="Associated images")
    lang: Optional[str] = Field(None, description="Content language")
    timestamp: Optional[int] = Field(None, description="Content timestamp")
    indexed_at: Optional[datetime] = Field(None, description="When indexed")
    source: SearchSource = Field(..., description="Result source")
    score: float = Field(..., ge=0.0, le=1.0, description="Relevance score (0-1)")
    original_score: Optional[float] = Field(None, description="Score before reranking")
    vectors: Optional[List[float]] = Field(default=None, alias="_vectors", description="Embeddings vectors from Meilisearch")

class SearchStats(BaseModel):
    """Search statistics."""
    total_results: int = Field(..., description="Total results returned")
    meilisearch_results: int = Field(default=0, description="Results from Meilisearch")
    cse_results: int = Field(default=0, description="Results from Google CSE")
    wiki_results: int = Field(default=0, description="Results from Wiki")
    processing_time_ms: float = Field(..., description="Total processing time in ms")
    meilisearch_time_ms: Optional[float] = Field(None, description="Meilisearch query time")
    cse_time_ms: Optional[float] = Field(None, description="CSE query time")
    wiki_time_ms: Optional[float] = Field(None, description="Wiki query time")
    reranking_time_ms: Optional[float] = Field(None, description="Reranking time")
    reranking_applied: bool = Field(default=False, description="Whether reranking was applied")
    cache_hit: bool = Field(default=False, description="Whether CSE results from cache")


class SearchResponse(BaseModel):
    """Search response with results and metadata."""
    query: str = Field(..., description="Original search query")
    results: List[SearchResult] = Field(..., description="Search results")
    stats: SearchStats = Field(..., description="Search statistics")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "dinosaures",
                "results": [
                    {
                        "id": "abc123",
                        "title": "Les Dinosaures - Vikidia",
                        "url": "https://fr.vikidia.org/wiki/Dinosaure",
                        "excerpt": "Les dinosaures sont des reptiles qui ont vécu...",
                        "site": "Vikidia",
                        "images": [],
                        "lang": "fr",
                        "source": "meilisearch",
                        "score": 0.95
                    }
                ],
                "stats": {
                    "total_results": 20,
                    "meilisearch_results": 15,
                    "cse_results": 5,
                    "wiki_results": 2,
                    "processing_time_ms": 245.3,
                    "reranking_applied": True,
                    "cache_hit": False
                }
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Current time")
    services: Dict[str, bool] = Field(..., description="Status of dependent services")


class FeedbackRequest(BaseModel):
    """User feedback on search result."""
    query: str = Field(..., description="Original search query")
    result_id: str = Field(..., description="Result ID")
    result_url: HttpUrl = Field(..., description="Result URL")
    reason: str = Field(..., description="Reason for feedback")
    comment: Optional[str] = Field(None, max_length=500, description="Optional comment")

    class Config:
        json_schema_extra = {
            "example": {
                "query": "dinosaures",
                "result_id": "abc123",
                "result_url": "https://example.com/page",
                "reason": "inappropriate",
                "comment": "Contenu non adapté aux enfants"
            }
        }


class FeedbackResponse(BaseModel):
    """Feedback submission response."""
    success: bool = Field(..., description="Whether feedback was recorded")
    message: str = Field(..., description="Response message")


class APIStats(BaseModel):
    """API usage statistics for dashboard."""
    total_searches: int = Field(..., description="Total searches")
    searches_last_hour: int = Field(..., description="Searches in last hour")
    avg_response_time_ms: float = Field(..., description="Average response time")
    cse_quota_used: int = Field(..., description="Google CSE queries used today")
    cse_quota_limit: int = Field(..., description="Google CSE daily limit")
    cache_hit_rate: float = Field(..., ge=0.0, le=1.0, description="CSE cache hit rate")
    top_queries: List[Dict[str, Any]] = Field(..., description="Most frequent queries")
    error_rate: float = Field(..., ge=0.0, le=1.0, description="Error rate")
