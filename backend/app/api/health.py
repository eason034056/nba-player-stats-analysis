"""
health.py - Health Check API Endpoints

Provides health status checking for the service.
Use Cases:
1. Confirm service is running after deployment
2. Periodic checks by the load balancer
3. Service status checks for monitoring systems
4. Manual triggering of scheduled tasks (e.g. CSV download)
"""

from fastapi import APIRouter
from datetime import datetime, timezone
from app.models.schemas import HealthResponse
from app.services.scheduler import scheduler_service
from app.services.csv_downloader import csv_downloader_service

# Create router
# APIRouter: FastAPI's routing group tool
# prefix: common prefix for all endpoints under this router
# tags: Used for API documentation category (OpenAPI/Swagger)
router = APIRouter(
    prefix="/api",
    tags=["health"]
)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health Check",
    description="Check if the API service is up and running"
)
async def health_check() -> HealthResponse:
    """
    Health Check Endpoint

    GET /api/health

    Used to confirm the API service is running.
    Returns the service name and current server time (UTC).

    Returns:
        HealthResponse: Contains the service status.
        - ok: True means the service is healthy
        - service: Identifier of the service
        - time: Current server UTC time

    Example Response:
        {
            "ok": true,
            "service": "no-vig-nba",
            "time": "2026-01-14T18:00:00Z"
        }
    """
    return HealthResponse(
        ok=True,
        service="no-vig-nba",
        time=datetime.now(timezone.utc)
    )


@router.post(
    "/trigger-csv-download",
    summary="Manually Trigger CSV Download",
    description="Download the latest NBA player data CSV file from GitHub"
)
async def trigger_csv_download():
    """
    Manually Trigger CSV Download

    POST /api/trigger-csv-download

    Used to manually download the latest NBA player data CSV file without waiting for the scheduled time.
    This endpoint will immediately download the CSV from GitHub and save it to the data/ directory.

    Returns:
        dict: Download result
        - success: bool, whether the download was successful
        - message: str, result message
        - last_modified: str | None, last modification time of the CSV file

    Example Response (Success):
        {
            "success": true,
            "message": "CSV download succeeded",
            "last_modified": "2026-01-28T15:00:00+00:00"
        }

    Example Response (Failure):
        {
            "success": false,
            "message": "CSV download failed",
            "last_modified": null
        }
    """
    # Call the scheduler's manual trigger method
    success = await scheduler_service.trigger_csv_download_now()
    
    return {
        "success": success,
        "message": "CSV download succeeded" if success else "CSV download failed",
        "last_modified": csv_downloader_service.get_last_modified()
    }


@router.get(
    "/scheduler-status",
    summary="View Scheduler Status",
    description="Get the scheduler status and the next run time"
)
async def get_scheduler_status():
    """
    View Scheduler Status

    GET /api/scheduler-status

    Shows the status and next run time for all scheduled tasks.

    Returns:
        dict: Scheduler status
        - is_running: bool, whether the scheduler is running
        - next_daily_analysis: str | None, next run time for daily analysis
        - next_csv_download: str | None, next run time for CSV download
        - csv_last_modified: str | None, last modification time of the CSV file

    Example Response:
        {
            "is_running": true,
            "next_daily_analysis": "2026-01-28T12:00:00+00:00",
            "next_csv_download": "2026-01-28T15:00:00+00:00",
            "csv_last_modified": "2026-01-27T15:00:00+00:00"
        }
    """
    return {
        "is_running": scheduler_service.is_running,
        "next_daily_analysis": scheduler_service.get_next_run_time(),
        "next_csv_download": scheduler_service.get_csv_download_next_run_time(),
        "csv_last_modified": csv_downloader_service.get_last_modified()
    }

