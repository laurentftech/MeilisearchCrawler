#!/usr/bin/env python3
"""
KidSearch API Backend Launcher
Starts the FastAPI server for unified search (Meilisearch + Google CSE + Reranking)
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s:%(lineno)d] %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    """Launch the API server."""

    # Check if API is enabled
    api_enabled = os.getenv("API_ENABLED", "false").lower() == "true"
    if not api_enabled:
        logger.warning(
            "API backend is disabled. Set API_ENABLED=true in .env to enable."
        )
        sys.exit(1)

    # Get configuration
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8080"))
    workers = int(os.getenv("API_WORKERS", "4"))

    # Check required dependencies
    try:
        import fastapi
        import uvicorn
    except ImportError:
        logger.error(
            "FastAPI dependencies not installed. "
            "Run: pip install -r requirements.txt"
        )
        sys.exit(1)

    # Check Meilisearch connection
    meili_url = os.getenv("MEILI_URL", "http://localhost:7700")
    logger.info(f"Meilisearch URL: {meili_url}")

    # Check Google CSE configuration
    cse_api_key = os.getenv("GOOGLE_CSE_API_KEY")
    cse_id = os.getenv("GOOGLE_CSE_ID")

    if not cse_api_key or not cse_id or \
       cse_api_key == "your_google_api_key_here" or \
       cse_id == "your_search_engine_id_here":
        logger.warning(
            "Google CSE not configured. "
            "API will work with Meilisearch only. "
            "Set GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID in .env for unified search."
        )

    # Log configuration
    logger.info("=" * 60)
    logger.info("KidSearch API Backend")
    logger.info("=" * 60)
    logger.info(f"Host: {host}")
    logger.info(f"Port: {port}")
    logger.info(f"Workers: {workers}")
    logger.info(f"Reranking: {os.getenv('RERANKING_ENABLED', 'true')}")
    logger.info(f"Reranker Model: {os.getenv('RERANKER_MODEL', 'intfloat/multilingual-e5-base')}")
    logger.info("=" * 60)
    logger.info("")
    logger.info("API Documentation:")
    logger.info(f"  Swagger UI: http://{host}:{port}/api/docs")
    logger.info(f"  ReDoc:      http://{host}:{port}/api/redoc")
    logger.info("")
    logger.info("Endpoints:")
    logger.info(f"  GET  http://{host}:{port}/api/health")
    logger.info(f"  GET  http://{host}:{port}/api/search?q=dinosaures")
    logger.info(f"  GET  http://{host}:{port}/api/stats")
    logger.info(f"  POST http://{host}:{port}/api/feedback")
    logger.info("=" * 60)

    # Start server
    try:
        import uvicorn
        uvicorn.run(
            "meilisearchcrawler.api.server:app",
            host=host,
            port=port,
            workers=workers,
            log_level="info",
            reload=False,  # Set to True for development
        )
    except KeyboardInterrupt:
        logger.info("API server stopped by user")
    except Exception as e:
        logger.error(f"Failed to start API server: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
