"""
FastAPI server for KidSearch backend.
Provides unified search API combining Meilisearch and Google CSE with reranking.
"""

import logging
import os
from contextlib import asynccontextmanager
from typing import Dict
from pathlib import Path
from dotenv import load_dotenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from meilisearch_python_sdk.errors import MeilisearchCommunicationError
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Gauge

from .routes import health, search
from .services.meilisearch_client import MeilisearchClient
from .services.cse_client import CSEClient
from .services.wiki_client import WikiClient
from .services.safety import SafetyFilter
from .services.merger import SearchMerger
from .services.reranker import HuggingFaceAPIReranker
from .services.stats_db import StatsDatabase
from .services.crawler_status import get_crawl_status

logger = logging.getLogger(__name__)

from fastapi.middleware.cors import CORSMiddleware



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager for FastAPI app."""
    logger.info("Starting KidSearch API backend...")

    # --- Load .env file from project root ---
    env_path = Path(__file__).parent.parent.parent / '.env'
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        logger.info(f"✓ Loaded environment variables from {env_path}")
    else:
        logger.warning(f"⚠️ .env file not found at {env_path}. Using system environment variables.")

    # Load environment variables
    meili_url = os.getenv("MEILI_URL", "http://localhost:7700")
    meili_key = os.getenv("MEILI_KEY", "")
    index_name = os.getenv("INDEX_NAME", "kidsearch")

    # Initialize Meilisearch client
    logger.info(f"Initializing Meilisearch client for {meili_url}...")
    meilisearch_client = MeilisearchClient(meili_url, meili_key, index_name)
    try:
        await meilisearch_client.connect()  # Await the async connection
        app.state.meilisearch_client = meilisearch_client
        logger.info("✓ Meilisearch client initialized")

        # --- Verify index configuration ---
        logger.info("Verifying Meilisearch index configuration...")
        required_filterable = ["lang", "site"]
        try:
            index = meilisearch_client.index
            settings = await index.get_settings()
            current_filterable = settings.filterable_attributes or []
            is_configured = all(attr in current_filterable for attr in required_filterable)

            if is_configured:
                logger.info("✓ Index filterable attributes are correctly configured.")
            else:
                logger.warning("⚠️ Index filterable attributes are not configured.")
                logger.warning(f"   Current: {current_filterable}")
                logger.warning(f"   Required: {required_filterable}")
                logger.warning("   You can run `python crawler.py` or `python configure_meilisearch.py` to apply settings.")
        except Exception as e:
            logger.error(f"✗ Could not verify index settings: {e}")
            logger.error("  The API might not work as expected.")

    except MeilisearchCommunicationError:
        logger.critical(f"✗✗✗ CRITICAL: Could not connect to Meilisearch at {meili_url}.")
        app.state.meilisearch_client = None
    except Exception as e:
        logger.critical(f"✗✗✗ CRITICAL: An unexpected error occurred during Meilisearch initialization: {e}")
        app.state.meilisearch_client = None

    # Initialize Wiki Client (optional)
    wiki_api_url = os.getenv("WIKI_API_URL")
    wiki_site_url = os.getenv("WIKI_SITE_URL")
    wiki_site_name = os.getenv("WIKI_SITE_NAME", "Wiki")

    if wiki_api_url and wiki_site_url:
        logger.info(f"Initializing Wiki client for {wiki_site_name}...")
        try:
            wiki_client = WikiClient(
                api_url=wiki_api_url,
                site_url=wiki_site_url,
                site_name=wiki_site_name
            )
            app.state.wiki_client = wiki_client
            logger.info("✓ Wiki client initialized")
        except Exception as e:
            logger.warning(f"✗ Failed to initialize Wiki client: {e}")
            app.state.wiki_client = None
    else:
        if wiki_api_url and not wiki_site_url:
            logger.warning("⚠️ WIKI_API_URL is set but WIKI_SITE_URL is missing. Wiki client not initialized.")
        else:
            logger.info("Wiki client not configured.")
        app.state.wiki_client = None


    # Initialize Safety Filter
    logger.info("Initializing safety filter...")
    safety_filter = SafetyFilter()
    app.state.safety_filter = safety_filter
    logger.info("✓ Safety filter initialized")

    # Initialize Search Merger
    logger.info("Initializing search merger...")
    meilisearch_weight = float(os.getenv("MEILISEARCH_WEIGHT", "0.7"))
    cse_weight = float(os.getenv("CSE_WEIGHT", "0.3"))
    merger = SearchMerger(meilisearch_weight, cse_weight)
    app.state.merger = merger
    logger.info(f"✓ Search merger initialized (weights: {meilisearch_weight}/{cse_weight})")

    # Initialize Google CSE client (optional)
    cse_api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if cse_api_key and cse_api_key != "your_google_api_key_here":
        logger.info("Initializing Google CSE client...")
        try:
            cse_cache_days = int(os.getenv("CSE_CACHE_DAYS", "7"))
            cse_quota = int(os.getenv("CSE_DAILY_QUOTA", "100"))

            cse_client = CSEClient(
                api_key=cse_api_key,
                search_engine_id=cse_id,
                cache_days=cse_cache_days,
                daily_quota=cse_quota,
            )
            app.state.cse_client = cse_client
            logger.info("✓ Google CSE client initialized")
        except Exception as e:
            logger.warning(f"✗ Failed to initialize CSE client: {e}")
    else:
        logger.info("Google CSE not configured, using Meilisearch only")

    # Initialize Reranker (optional)
    reranking_enabled = os.getenv("RERANKING_ENABLED", "false").lower() == "true"
    app.state.reranker = None

    if reranking_enabled:
        logger.info("Initializing semantic reranker...")
        try:
            reranker_api_url = os.getenv("RERANKER_API_URL")
            reranker_model = os.getenv("RERANKER_MODEL")
            
            reranker = HuggingFaceAPIReranker(api_url=reranker_api_url, model_name=reranker_model)
            app.state.reranker = reranker
            
            if not reranker._initialized:
                 logger.warning("Reranker initialization failed. Reranking will be skipped.")

        except Exception as e:
            logger.error(f"✗ An unexpected error occurred during reranker setup: {e}", exc_info=True)
            logger.warning("Continuing without reranking.")
    else:
        logger.info("Reranking is disabled by configuration.")

    # Initialize Stats Database
    logger.info("Initializing stats database...")
    try:
        stats_db = StatsDatabase()
        app.state.stats_db = stats_db
        logger.info("✓ Stats database initialized")

        # --- Custom Prometheus Metrics ---
        logger.info("Initializing custom Prometheus metrics...")
        Gauge(
            "avg_meilisearch_time_ms",
            "Average Meilisearch query time in ms (all time)"
        ).set_function(lambda: app.state.stats_db.get_avg_meilisearch_time())

        Gauge(
            "avg_cse_time_ms",
            "Average Google CSE query time in ms (all time)"
        ).set_function(lambda: app.state.stats_db.get_avg_cse_time())

        Gauge(
            "avg_reranking_time_ms",
            "Average reranking time in ms (all time)"
        ).set_function(lambda: app.state.stats_db.get_avg_reranking_time())

        # --- Crawler Metrics ---
        Gauge(
            "crawler_running",
            "Indicates if the crawler is currently running (1 for running, 0 for stopped)"
        ).set_function(lambda: get_crawl_status().get("running", 0))

        Gauge(
            "crawler_pages_indexed",
            "Total number of pages indexed in the last crawl"
        ).set_function(lambda: get_crawl_status().get("pages_indexed", 0))

        Gauge(
            "crawler_sites_crawled",
            "Number of sites crawled in the last run"
        ).set_function(lambda: get_crawl_status().get("sites_crawled", 0))

        Gauge(
            "crawler_errors",
            "Total number of errors during the last crawl"
        ).set_function(lambda: get_crawl_status().get("errors", 0))

        Gauge(
            "crawler_last_duration_sec",
            "Duration of the last crawl in seconds"
        ).set_function(lambda: get_crawl_status().get("last_crawl_duration_sec", 0))

        Gauge(
            "crawler_avg_embedding_batch_time_ms",
            "Average time to generate embeddings for a batch of documents in ms"
        ).set_function(lambda: get_crawl_status().get("avg_embedding_batch_time_ms", 0))

        Gauge(
            "crawler_avg_indexing_batch_time_ms",
            "Average time to index a batch of documents in ms"
        ).set_function(lambda: get_crawl_status().get("avg_indexing_batch_time_ms", 0))

        logger.info("✓ Custom Prometheus metrics initialized")

    except Exception as e:
        logger.warning(f"✗ Failed to initialize stats database: {e}")
        logger.warning("Continuing without stats tracking")

    logger.info("KidSearch API backend started successfully")

    yield

    logger.info("Shutting down KidSearch API backend...")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""

    app = FastAPI(
        title="KidSearch API",
        description="Backend API for KidSearch - Safe search engine for children",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # Add metrics middleware
    Instrumentator().instrument(app).expose(app, endpoint="/api/metrics")

    # CORS middleware for frontend integration
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # TODO: Configure specific origins in production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routes
    app.include_router(health.router, prefix="/api", tags=["Health"])
    app.include_router(search.router, prefix="/api", tags=["Search"])

    # Global exception handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request, exc):
        logger.error(f"Unhandled exception: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "detail": str(exc)},
        )

    return app


app = create_app()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ou "*" pour tout autoriser temporairement
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
