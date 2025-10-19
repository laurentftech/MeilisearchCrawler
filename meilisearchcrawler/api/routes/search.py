"""
Search endpoints.
"""

import logging
import time
import os
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, status, Request
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

from ..models import (
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchStats,
    FeedbackRequest,
    FeedbackResponse,
    APIStats,
    Language,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Global flag to check if CSE is configured
CSE_CONFIGURED = (
    os.getenv("GOOGLE_CSE_API_KEY") and
    os.getenv("GOOGLE_CSE_API_KEY") != "your_google_api_key_here"
)
RERANKING_ENABLED = os.getenv("RERANKING_ENABLED", "false").lower() == "true"


@router.get(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified search",
    description="Search across Meilisearch and Google CSE with optional reranking",
)
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    lang: Language = Query(default=Language.FR, description="Search language"),
    limit: int = Query(default=20, ge=1, le=100, description="Max results"),
    use_cse: bool = Query(default=True, description="Include Google CSE results"),
    use_reranking: bool = Query(default=True, description="Apply semantic reranking"),
) -> SearchResponse:
    """
    Unified search endpoint combining Meilisearch and Google CSE.

    Flow:
    1. Query Meilisearch for local indexed content
    2. Query Google CSE if enabled (with cache check)
    3. Apply safety filters to all results
    4. Merge and deduplicate results
    5. Apply semantic reranking if enabled
    6. Return top N results with statistics
    """

    start_time = time.time()

    logger.info(
        f"Search request: q='{q}', lang={lang}, limit={limit}, "
        f"use_cse={use_cse}, use_reranking={use_reranking}"
    )

    # Get services from app state
    meilisearch_client = request.app.state.meilisearch_client
    cse_client = request.app.state.cse_client if hasattr(request.app.state, "cse_client") else None

    # --- Check Meilisearch availability ---
    if not meilisearch_client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meilisearch client is not initialized.",
        )
    try:
        await meilisearch_client.health()
    except MeilisearchCommunicationError as e:
        logger.error(f"Meilisearch connection check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Meilisearch service is not available. Please check the connection.",
        )
    # --- End check ---

    safety_filter = request.app.state.safety_filter
    merger = request.app.state.merger
    reranker = request.app.state.reranker if hasattr(request.app.state, "reranker") else None

    # Initialize result lists and timing
    meilisearch_results = []
    cse_results = []
    cache_hit = False

    meilisearch_start = time.time()
    meilisearch_time_ms = None
    cse_time_ms = None
    reranking_time_ms = None

    # 1. Search Meilisearch
    try:
        meilisearch_results = await meilisearch_client.search(
            query=q,
            lang=lang.value if lang != Language.ALL else None,
            limit=limit * 2  # Get more results for better merging
        )
        meilisearch_time_ms = (time.time() - meilisearch_start) * 1000
        logger.info(f"Meilisearch returned {len(meilisearch_results)} results in {meilisearch_time_ms:.2f}ms")
    except MeilisearchApiError as e:
        meilisearch_time_ms = (time.time() - meilisearch_start) * 1000
        logger.error(f"Meilisearch API error: {e}", exc_info=True)
        if e.code == "invalid_search_filter":
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Meilisearch index is not configured correctly. "
                    "Filterable attributes are missing. "
                    "Please run the crawler once (`python crawler.py`) to apply settings."
                ),
            )
        # For other Meilisearch errors, continue without results
    except Exception as e:
        logger.error(f"Meilisearch search failed: {e}", exc_info=True)
        meilisearch_time_ms = (time.time() - meilisearch_start) * 1000

    # 2. Search Google CSE (if enabled and configured)
    if use_cse and CSE_CONFIGURED and cse_client:
        cse_start = time.time()
        try:
            cse_results, cache_hit = await cse_client.search(
                query=q,
                lang=lang.value if lang != Language.ALL else "fr",
                num_results=min(limit, 10)  # CSE max 10 per request
            )
            cse_time_ms = (time.time() - cse_start) * 1000
            logger.info(
                f"CSE returned {len(cse_results)} results in {cse_time_ms:.2f}ms "
                f"(cache_hit={cache_hit})"
            )
        except Exception as e:
            logger.error(f"CSE search failed: {e}", exc_info=True)
            cse_time_ms = (time.time() - cse_start) * 1000

    # 3. Apply safety filters
    meilisearch_results = safety_filter.filter_results(meilisearch_results)
    cse_results = safety_filter.filter_results(cse_results)

    # 4. Merge and deduplicate
    merged_results = merger.merge(
        meilisearch_results=meilisearch_results,
        cse_results=cse_results,
        limit=limit * 2  # Get more for reranking
    )

    # 5. Apply reranking if enabled
    reranking_applied = False
    if use_reranking and RERANKING_ENABLED and reranker:
        reranking_start = time.time()
        try:
            merged_results = reranker.rerank(
                query=q,
                results=merged_results,
                top_k=limit
            )
            reranking_time_ms = (time.time() - reranking_start) * 1000
            reranking_applied = True
            logger.info(f"Reranking completed in {reranking_time_ms:.2f}ms")
        except Exception as e:
            logger.error(f"Reranking failed: {e}", exc_info=True)
            reranking_time_ms = (time.time() - reranking_start) * 1000

    # Limit final results
    final_results = merged_results[:limit]

    # Calculate stats
    total_time_ms = (time.time() - start_time) * 1000

    stats = SearchStats(
        total_results=len(final_results),
        meilisearch_results=len(meilisearch_results),
        cse_results=len(cse_results),
        processing_time_ms=total_time_ms,
        meilisearch_time_ms=meilisearch_time_ms,
        cse_time_ms=cse_time_ms,
        reranking_time_ms=reranking_time_ms,
        reranking_applied=reranking_applied,
        cache_hit=cache_hit,
    )

    logger.info(
        f"Search completed in {total_time_ms:.2f}ms: "
        f"{stats.total_results} results "
        f"({stats.meilisearch_results} Meili + {stats.cse_results} CSE)"
    )

    # Log stats to database
    if hasattr(request.app.state, "stats_db"):
        try:
            request.app.state.stats_db.log_search(
                query=q,
                lang=lang.value,
                limit=limit,
                use_cse=use_cse,
                use_reranking=use_reranking,
                stats=stats.model_dump(),
            )
        except Exception as e:
            logger.error(f"Failed to log search stats: {e}")

    return SearchResponse(query=q, results=final_results, stats=stats)


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    status_code=status.HTTP_200_OK,
    summary="Submit feedback",
    description="Report inappropriate or problematic search results",
)
async def submit_feedback(request: Request, feedback: FeedbackRequest) -> FeedbackResponse:
    """
    Submit feedback about a search result.
    Used to report inappropriate content or improve filtering.
    """

    logger.info(
        f"Feedback received: query='{feedback.query}', "
        f"result_id={feedback.result_id}, reason={feedback.reason}"
    )

    # Store feedback in database
    if hasattr(request.app.state, "stats_db"):
        try:
            request.app.state.stats_db.log_feedback(
                query=feedback.query,
                result_id=feedback.result_id,
                result_url=str(feedback.result_url),
                reason=feedback.reason,
                comment=feedback.comment,
            )
        except Exception as e:
            logger.error(f"Failed to log feedback: {e}")

    # TODO: Trigger safety filter update if needed

    return FeedbackResponse(
        success=True, message="Feedback enregistré, merci !"
    )


@router.get(
    "/stats",
    response_model=APIStats,
    status_code=status.HTTP_200_OK,
    summary="API statistics",
    description="Get API usage statistics for dashboard monitoring",
)
async def get_stats(request: Request) -> APIStats:
    """
    Get API usage statistics.
    Used by Streamlit dashboard for monitoring.
    """

    stats_db = request.app.state.stats_db if hasattr(request.app.state, "stats_db") else None
    cse_client = request.app.state.cse_client if hasattr(request.app.state, "cse_client") else None

    if not stats_db:
        # Return empty stats if database not initialized
        return APIStats(
            total_searches=0,
            searches_last_hour=0,
            avg_response_time_ms=0.0,
            cse_quota_used=0,
            cse_quota_limit=100,
            cache_hit_rate=0.0,
            top_queries=[],
            error_rate=0.0,
        )

    # Get stats from database
    total_searches = stats_db.get_total_searches()
    searches_last_hour = stats_db.get_searches_last_hour()
    avg_response_time = stats_db.get_avg_response_time()
    cache_hit_rate = stats_db.get_cache_hit_rate()
    top_queries = stats_db.get_top_queries(limit=10)
    error_rate = stats_db.get_error_rate()

    # Get CSE quota info
    cse_quota_used = 0
    cse_quota_limit = 100

    if cse_client:
        quota_info = cse_client.get_quota_usage()
        cse_quota_used = quota_info.get("used", 0)
        cse_quota_limit = quota_info.get("limit", 100)

    return APIStats(
        total_searches=total_searches,
        searches_last_hour=searches_last_hour,
        avg_response_time_ms=avg_response_time,
        cse_quota_used=cse_quota_used,
        cse_quota_limit=cse_quota_limit,
        cache_hit_rate=cache_hit_rate,
        top_queries=top_queries,
        error_rate=error_rate,
    )
