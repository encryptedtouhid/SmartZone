import logging
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import asyncio

from backend.database import Database
from backend.routes import api, websocket
from backend.services.surge_detection import surge_service
from backend.services.geofencing import geofencing_service
from backend.services.prediction import prediction_service
from config import APP_NAME, DEBUG, HOST, PORT

# Configure logging
logging.basicConfig(
    level=logging.INFO if DEBUG else logging.WARNING,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title=APP_NAME,
    description="Geo-Fenced Demand Prediction & Surge Visualizer",
    version="1.0.0",
    debug=DEBUG
)

# Mount static files
app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

# Templates
templates = Jinja2Templates(directory="frontend/templates")

# Include routers
app.include_router(api.router, prefix="/api", tags=["api"])
app.include_router(websocket.router, prefix="/ws", tags=["websocket"])


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the main dashboard page"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.on_event("startup")
async def startup_event():
    """Initialize database and services on startup"""
    logger.info(f"Starting {APP_NAME}...")

    # Connect to database
    await Database.connect()

    # Start services
    await surge_service.start()

    # Start prediction service if enabled
    # Comment out to disable ML prediction (as it's optional)
    await prediction_service.start()

    logger.info(f"{APP_NAME} started successfully!")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown"""
    logger.info(f"Shutting down {APP_NAME}...")

    # Stop services
    await surge_service.stop()
    await prediction_service.stop()

    # Close database connection
    await Database.close()

    logger.info(f"{APP_NAME} shutdown complete")


if __name__ == "__main__":
    # Run the server
    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        reload=DEBUG
    )