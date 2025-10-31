"""
Search endpoints.
"""

import asyncio
import logging
import time
import os
from typing import Optional, List, Tuple
import numpy as np

from fastapi import APIRouter, Query, HTTPException, status, Request
from fastapi.responses import JSONResponse
from meilisearch_python_sdk.errors import MeilisearchApiError

from ..models import (
    SearchResponse,
    SearchStats,
    FeedbackRequest,
    FeedbackResponse,
    APIStats,
    Language,
    SearchResult
)
from ..state import AppState

logger = logging.getLogger(__name__)
router = APIRouter()

CSE_CONFIGURED = os.getenv("GOOGLE_CSE_API_KEY") and os.getenv("GOOGLE_CSE_API_KEY") != "your_google_api_key_here"
RERANKING_ENABLED = os.getenv("RERANKING_ENABLED", "false").lower() == "true"

def _truncate(text: str, max_chars: int = 256) -> str:
    return text[:max_chars]

async def _embed_results(embedding_provider, results: List[SearchResult]):
    """Asynchronously embeds a list of search results in place."""
    texts_to_embed = [_truncate(f"{r.title or ''} {r.excerpt or ''}") for r in results if not r.vectors]
    if not texts_to_embed:
        return

    embeddings = await asyncio.to_thread(embedding_provider.encode, texts_to_embed)
    
    text_idx = 0
    for result in results:
        if not result.vectors:
            result.vectors = embeddings[text_idx]
            text_idx += 1

@router.get(
    "/search",
    response_model=SearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Unified search",
)
async def search(
    request: Request,
    q: str = Query(..., min_length=1, max_length=200, description="Search query"),
    lang: Language = Query(default=Language.FR, description="Search language"),
    limit: int = Query(default=20, ge=1, le=100, description="Max results"),
    use_cse: bool = Query(default=True, description="Include Google CSE results"),
    use_hybrid: bool = Query(default=True, description="Use hybrid vector search"),
    use_reranking: bool = Query(default=True, description="Apply semantic reranking"),
) -> SearchResponse:
    state: AppState = request.app.state
    start_time = time.time()
    logger.info(f"Search request: q='{q}', lang={lang.value}, use_cse={use_cse}, use_reranking={use_reranking}")

    meilisearch_client = state.meilisearch_client
    cse_client = state.cse_client
    wiki_clients = state.wiki_clients
    safety_filter = state.safety_filter
    merger = state.merger
    reranker = state.reranker
    embedding_provider = state.embedding_provider

    if not meilisearch_client or not await meilisearch_client.is_healthy():
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Meilisearch is not available.")

    async def search_meilisearch() -> Tuple[List[SearchResult], float]:
        s = time.time()
        try:
            res = await meilisearch_client.search(query=q, lang=lang.value, limit=limit * 2, use_hybrid=use_hybrid)
            return res, (time.time() - s) * 1000
        except MeilisearchApiError as e:
            logger.error(f"Meilisearch API error: {e}")
            if e.code == "invalid_search_filter":
                raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Meilisearch index not configured.")
            return [], (time.time() - s) * 1000
        except Exception as e:
            logger.error(f"Meilisearch search failed: {e}")
            return [], (time.time() - s) * 1000

    async def search_cse() -> Tuple[List[SearchResult], bool, float]:
        if not (use_cse and CSE_CONFIGURED and cse_client):
            return [], False, 0.0
        s = time.time()
        res, hit = await cse_client.search(query=q, lang=lang.value, num_results=min(limit, 10))
        if embedding_provider:
            await _embed_results(embedding_provider, res)
        return res, hit, (time.time() - s) * 1000

    async def search_wiki() -> Tuple[List[SearchResult], float]:
        """Search all configured wiki instances in parallel."""
        if not wiki_clients:
            return [], 0.0

        s = time.time()

        # Search all wikis in parallel
        async def search_single_wiki(client: 'WikiClient') -> List[SearchResult]:
            try:
                return await client.search(query=q, lang=lang.value, limit=5)
            except Exception as e:
                logger.error(f"Error searching wiki {client.site_name}: {e}")
                return []

        # Execute all wiki searches concurrently
        wiki_results_list = await asyncio.gather(*[search_single_wiki(client) for client in wiki_clients])

        # Flatten and combine results from all wikis
        all_wiki_results = []
        for results in wiki_results_list:
            all_wiki_results.extend(results)

        # Embed results if provider is available
        if embedding_provider and all_wiki_results:
            await _embed_results(embedding_provider, all_wiki_results)

        return all_wiki_results, (time.time() - s) * 1000

    query_embedding_task = asyncio.to_thread(embedding_provider.encode, [q]) if RERANKING_ENABLED and embedding_provider else None

    (meili_res, meili_time), (cse_res, cache_hit, cse_time), (wiki_res, wiki_time), query_emb_list = await asyncio.gather(
        search_meilisearch(), search_cse(), search_wiki(), query_embedding_task or asyncio.sleep(0, result=[None])
    )

    query_embedding = np.array(query_emb_list[0]) if query_emb_list and query_emb_list[0] else None

    meili_res = safety_filter.filter_results(meili_res)
    cse_res = safety_filter.filter_results(cse_res)
    wiki_res = safety_filter.filter_results(wiki_res)

    # Deduplicate wiki results by ID to avoid duplicates from multiple wikis
    seen_ids = set()
    deduped_wiki_res = []
    for r in wiki_res:
        if r.id not in seen_ids:
            deduped_wiki_res.append(r)
            seen_ids.add(r.id)

    merged_results = deduped_wiki_res + merger.merge(meilisearch_results=meili_res, cse_results=cse_res, limit=limit * 2)

    reranking_applied, reranking_time_ms = False, None
    if use_reranking and RERANKING_ENABLED and reranker and query_embedding is not None:
        rerank_start = time.time()
        merged_results = reranker.rerank(query=q, results=merged_results, top_k=limit, query_embedding=query_embedding)
        reranking_time_ms = (time.time() - rerank_start) * 1000
        reranking_applied = True

    final_results = merged_results[:limit]

    # Remove embeddings from results before sending to client (waste of bandwidth)
    for result in final_results:
        result.vectors = None

    total_time_ms = (time.time() - start_time) * 1000

    stats = SearchStats(
        total_results=len(final_results),
        meilisearch_results=len(meili_res),
        cse_results=len(cse_res),
        wiki_results=len(wiki_res),
        processing_time_ms=total_time_ms,
        meilisearch_time_ms=meili_time,
        cse_time_ms=cse_time,
        wiki_time_ms=wiki_time,
        reranking_time_ms=reranking_time_ms,
        reranking_applied=reranking_applied,
        cache_hit=cache_hit,
    )

    if state.stats_db:
        state.stats_db.log_search(q, lang.value, limit, use_cse, use_hybrid, use_reranking, stats.model_dump())

    return SearchResponse(query=q, results=final_results, stats=stats)

@router.post("/feedback", response_model=FeedbackResponse, status_code=status.HTTP_200_OK)
async def submit_feedback(request: Request, feedback: FeedbackRequest) -> FeedbackResponse:
    state: AppState = request.app.state
    if state.stats_db:
        state.stats_db.log_feedback(**feedback.model_dump())
    return FeedbackResponse(success=True, message="Feedback received.")

@router.get("/stats", status_code=status.HTTP_200_OK)
async def get_stats(request: Request) -> JSONResponse:
    state: AppState = request.app.state
    stats_db = state.stats_db
    cse_client = state.cse_client
    
    if not stats_db:
        api_stats = APIStats(
            total_searches=0, searches_last_hour=0, avg_response_time_ms=0.0,
            cache_hit_rate=0.0, top_queries=[], error_rate=0.0,
            cse_quota_used=0, cse_quota_limit=100
        )
    else:
        cse_quota = cse_client.get_quota_usage() if cse_client else {}
        api_stats = APIStats(
            total_searches=stats_db.get_total_searches(),
            searches_last_hour=stats_db.get_searches_last_hour(),
            avg_response_time_ms=stats_db.get_avg_search_time(),
            cache_hit_rate=stats_db.get_cache_hit_rate(),
            top_queries=stats_db.get_top_queries(limit=50),
            error_rate=stats_db.get_error_rate(),
            cse_quota_used=cse_quota.get("used", 0),
            cse_quota_limit=cse_quota.get("limit", 100),
        )
        
    headers = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
    return JSONResponse(content=api_stats.model_dump(), headers=headers)

@router.post("/stats/reset", status_code=status.HTTP_200_OK)
async def reset_stats(request: Request):
    state: AppState = request.app.state
    if not state.stats_db or not state.stats_db.reset_stats():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reset API statistics.")
    logger.info("API statistics have been reset.")
    return {"message": "API statistics reset successfully."}
