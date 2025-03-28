import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
dotenv_path = Path(".") / ".env"
load_dotenv(dotenv_path=dotenv_path)

# Application settings
APP_NAME = os.getenv("APP_NAME", "SmartZone")
DEBUG = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Server settings
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", 8000))

# MongoDB settings
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "smartzone_db")

# Geospatial settings
DEFAULT_CITY = os.getenv("DEFAULT_CITY", "Singapore")
DEFAULT_LAT = float(os.getenv("DEFAULT_LAT", 1.3521))
DEFAULT_LON = float(os.getenv("DEFAULT_LON", 103.8198))
DEFAULT_ZOOM = int(os.getenv("DEFAULT_ZOOM", 12))
H3_RESOLUTION = int(os.getenv("H3_RESOLUTION", 8))

# Simulation settings
SIMULATION_SPEED = float(os.getenv("SIMULATION_SPEED", 1.0))
NUM_DRIVERS = int(os.getenv("NUM_DRIVERS", 10))
REQUEST_RATE = int(os.getenv("REQUEST_RATE", 5))  # Requests per minute
SURGE_THRESHOLD = int(os.getenv("SURGE_THRESHOLD", 5))

# Collections
COLLECTION_DRIVERS = "drivers"
COLLECTION_RIDE_REQUESTS = "ride_requests"
COLLECTION_ZONES = "zones"
COLLECTION_SURGE_HISTORY = "surge_history"