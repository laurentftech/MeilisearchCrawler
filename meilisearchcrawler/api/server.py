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
from meilisearch.errors import MeilisearchCommunicationError
from fastapi.responses import JSONResponse

from .routes import health, search
from .services.meilisearch_client import MeilisearchClient
from .services.cse_client import CSEClient
from .services.safety import SafetyFilter
from .services.merger import SearchMerger
from .services.reranker import SentenceTransformerReranker
from .services.stats_db import StatsDatabase

logger = logging.getLogger(__name__)


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
    # --- End of .env loading ---

    # Force PyTorch to use CPU if CUDA is not available
    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    logger.info("Set CUDA_VISIBLE_DEVICES=-1 to force CPU usage for PyTorch.")

    # Load environment variables
    meili_url = os.getenv("MEILI_URL", "http://localhost:7700")
    meili_key = os.getenv("MEILI_KEY", "")
    index_name = os.getenv("INDEX_NAME", "kidsearch")

    # Initialize Meilisearch client
    logger.info(f"Initializing Meilisearch client for {meili_url}...")
    meilisearch_client = MeilisearchClient(meili_url, meili_key, index_name)
    try:
        meilisearch_client.connect()
        app.state.meilisearch_client = meilisearch_client
        logger.info("✓ Meilisearch client initialized")

        # --- Verify index configuration ---
        logger.info("Verifying Meilisearch index configuration...")
        required_filterable = ["lang", "site"]
        try:
            index = meilisearch_client.client.index(index_name)
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
        # --- End verification ---

    except MeilisearchCommunicationError:
        logger.critical("✗✗✗ CRITICAL: Could not connect to Meilisearch.")
        logger.critical(f"    URL: {meili_url}")
        logger.critical("    Please ensure Meilisearch is running and accessible.")
        app.state.meilisearch_client = None

    except Exception as e:
        logger.critical(f"✗✗✗ CRITICAL: An unexpected error occurred during Meilisearch initialization: {e}")
        logger.critical("    The API will start in a DEGRADED state.")
        app.state.meilisearch_client = None

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

    # Initialize Reranker (optional, requires PyTorch)
    reranking_enabled = os.getenv("RERANKING_ENABLED", "false").lower() == "true"

    if reranking_enabled:
        logger.info("Initializing semantic reranker...")
        try:
            reranker_model = os.getenv("RERANKER_MODEL", "intfloat/multilingual-e5-base")
            reranker = SentenceTransformerReranker(reranker_model)
            reranker.initialize()
            app.state.reranker = reranker
            logger.info("✓ Reranker initialized")
        except Exception as e:
            logger.warning(f"✗ Failed to initialize reranker: {e}")
            logger.warning("Continuing without reranking")
    else:
        logger.info("Reranking disabled")

    # Initialize Stats Database
    logger.info("Initializing stats database...")
    try:
        stats_db = StatsDatabase()
        app.state.stats_db = stats_db
        logger.info("✓ Stats database initialized")
    except Exception as e:
        logger.warning(f"✗ Failed to initialize stats database: {e}")
        logger.warning("Continuing without stats tracking")

    logger.info("KidSearch API backend started successfully")

    yield

    # Cleanup resources
    logger.info("Shutting down KidSearch API backend...")
    if hasattr(app.state, "meilisearch_client") and app.state.meilisearch_client:
        # No explicit close needed for http-based client, but good practice
        logger.info("✓ Meilisearch client does not require explicit shutdown.")
    if hasattr(app.state, "stats_db"):
        logger.info("✓ Stats database connection will be closed.")
    logger.info("KidSearch API backend shut down successfully.")


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
