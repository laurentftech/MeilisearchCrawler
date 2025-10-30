"""
Metrics management endpoints.
"""

import logging
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/metrics/reset",
    status_code=status.HTTP_200_OK,
    summary="Reset API metrics",
    description="Reset all API statistics and metrics",
)
async def reset_metrics(request: Request) -> JSONResponse:
    """
    Reset all API statistics.

    This will delete all search query logs and feedback from the stats database.
    Prometheus metrics will be reset to 0.
    """
    try:
        # Reset stats database
        if hasattr(request.app.state, 'stats_db'):
            success = request.app.state.stats_db.reset_stats()
            if success:
                logger.info("API metrics have been reset")
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={
                        "status": "success",
                        "message": "Metrics have been reset successfully"
                    }
                )
            else:
                logger.error("Failed to reset metrics")
                return JSONResponse(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    content={
                        "status": "error",
                        "message": "Failed to reset metrics"
                    }
                )
        else:
            logger.warning("Stats database not available")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "error",
                    "message": "Stats database not available"
                }
            )
    except Exception as e:
        logger.error(f"Error resetting metrics: {e}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": f"Error resetting metrics: {str(e)}"
            }
        )
