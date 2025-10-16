"""
Health check endpoints.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, status

from ..models import HealthResponse
from ... import __version__

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Check API and dependent services health status",
)
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    Returns status of API and all dependent services.
    """

    # TODO: Check actual service status
    services = {
        "meilisearch": True,  # TODO: Ping Meilisearch
        "reranker": True,     # TODO: Check if model loaded
        "cache": True,        # TODO: Check SQLite connection
    }

    all_healthy = all(services.values())

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=__version__,
        timestamp=datetime.utcnow(),
        services=services,
    )
