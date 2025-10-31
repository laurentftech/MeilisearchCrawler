"""
FastAPI server for KidSearch backend.
Provides unified search API combining Meilisearch and Google CSE with reranking.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Dict, Optional
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from meilisearch_python_sdk.errors import MeilisearchCommunicationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge

from .routes import health, search, metrics, auth
from .services.meilisearch_client import MeilisearchClient
from .services.cse_client import CSEClient
from .services.wiki_client import WikiClient
from .services.safety import SafetyFilter
from .services.merger import SearchMerger
from .services.reranker import HuggingFaceAPIReranker
from .services.stats_db import StatsDatabase
from .services.crawler_status import get_crawl_status
from ..embeddings import create_embedding_provider
from .state import AppState

logger = logging.getLogger(__name__)


def get_crawler_avg_embedding_time_per_page() -> float:
    """Calculate average embedding time per page from crawler status."""
    status = get_crawl_status()
    total_time = status.get("total_embedding_time_ms", 0)
    pages = status.get("pages_indexed", 0)
    return total_time / pages if pages > 0 else 0


def get_crawler_avg_indexing_time_per_page() -> float:
    """Calculate average indexing time per page from crawler status."""
    status = get_crawl_status()
    total_time = status.get("total_indexing_time_ms", 0)
    pages = status.get("pages_indexed", 0)
    return total_time / pages if pages > 0 else 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app."""
    app.state = AppState()
    logger.info("Starting KidSearch API backend...")

    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)

    # Initialize services
    try:
        meili_url = os.getenv("MEILI_URL", "http://localhost:7700")
        meili_key = os.getenv("MEILI_KEY", "")
        index_name = os.getenv("INDEX_NAME", "kidsearch")
        app.state.meilisearch_client = MeilisearchClient(meili_url, meili_key, index_name)
        await app.state.meilisearch_client.connect()
        logger.info("✓ Meilisearch client initialized")
    except Exception as e:
        logger.critical(f"✗✗✗ CRITICAL: Meilisearch initialization failed: {e}")

    # Initialize multiple wiki clients (support WIKI_1_*, WIKI_2_*, etc.)
    app.state.wiki_clients = []
    wiki_index = 1
    while True:
        prefix = f"WIKI_{wiki_index}_" if wiki_index > 1 else "WIKI_"
        api_url = os.getenv(f"{prefix}API_URL")
        site_url = os.getenv(f"{prefix}SITE_URL")
        site_name = os.getenv(f"{prefix}SITE_NAME")

        if api_url and site_url and site_name:
            # Clean values (remove quotes if present)
            api_url = api_url.strip().strip('"').strip("'")
            site_url = site_url.strip().strip('"').strip("'")
            site_name = site_name.strip().strip('"').strip("'")

            try:
                wiki_client = WikiClient(api_url=api_url, site_url=site_url, site_name=site_name)
                app.state.wiki_clients.append(wiki_client)
                logger.info(f"✓ Wiki client #{wiki_index} initialized: {site_name}")
            except Exception as e:
                logger.error(f"✗ Failed to initialize wiki client #{wiki_index}: {e}", exc_info=True)
        elif wiki_index == 1:
            # No wiki configured at all
            logger.info("No wiki clients configured")
            break
        else:
            # No more wikis to configure
            logger.info(f"✓ Total wiki clients initialized: {len(app.state.wiki_clients)}")
            break

        wiki_index += 1

    app.state.safety_filter = SafetyFilter()
    app.state.merger = SearchMerger(float(os.getenv("MEILISEARCH_WEIGHT", "0.7")), float(os.getenv("CSE_WEIGHT", "0.3")))
    app.state.cse_client = CSEClient(api_key=os.getenv("GOOGLE_CSE_API_KEY"), search_engine_id=os.getenv("GOOGLE_CSE_ID")) if os.getenv("GOOGLE_CSE_API_KEY") and os.getenv("GOOGLE_CSE_API_KEY") != "your_google_api_key_here" else None

    if os.getenv("RERANKING_ENABLED", "false").lower() == "true":
        try:
            app.state.embedding_provider = create_embedding_provider()
            app.state.reranker = HuggingFaceAPIReranker()
            logger.info("✓ Reranker and embedding provider initialized.")
        except Exception as e:
            logger.error(f"✗ Reranker/embedding setup failed: {e}", exc_info=True)
    else:
        logger.info("Reranking is disabled.")

    try:
        app.state.stats_db = StatsDatabase()
        logger.info("✓ Stats database initialized")
        # --- Custom Prometheus Metrics ---
        Gauge("avg_search_time_ms", "Average search time in ms").set_function(lambda: app.state.stats_db.get_avg_search_time())
        Gauge("avg_meilisearch_time_ms", "Average Meilisearch query time in ms").set_function(lambda: app.state.stats_db.get_avg_meilisearch_time())
        Gauge("avg_cse_time_ms", "Average Google CSE query time in ms").set_function(lambda: app.state.stats_db.get_avg_cse_time())
        Gauge("avg_wiki_time_ms", "Average MediaWiki query time in ms").set_function(lambda: app.state.stats_db.get_avg_wiki_time())
        Gauge("avg_reranking_time_ms", "Average reranking time in ms").set_function(lambda: app.state.stats_db.get_avg_reranking_time())
        Gauge("crawler_running", "Indicates if the crawler is running").set_function(lambda: get_crawl_status().get("running", 0))
        Gauge("crawler_avg_embedding_time_per_page_ms", "Average crawler embedding time per page in ms").set_function(get_crawler_avg_embedding_time_per_page)
        Gauge("crawler_avg_indexing_time_per_page_ms", "Average crawler indexing time per page in ms").set_function(get_crawler_avg_indexing_time_per_page)
        logger.info("✓ Custom Prometheus metrics initialized")
    except Exception as e:
        logger.warning(f"✗ Failed to initialize stats database or metrics: {e}")

    logger.info("KidSearch API backend started successfully")
    yield
    logger.info("Shutting down KidSearch API backend...")

def create_app() -> FastAPI:
    app = FastAPI(
        title="KidSearch API",
        description="Backend API for KidSearch - Safe search engine for children",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], 
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api", tags=["Health"])
    app.include_router(search.router, prefix="/api", tags=["Search"])
    app.include_router(metrics.router, prefix="/api", tags=["Metrics"])
    app.include_router(auth.router, prefix="/api", tags=["Authentication"])

    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(status_code=500, content={"error": "Internal server error"})

    return app

app = create_app()
