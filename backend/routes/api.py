from fastapi import APIRouter, HTTPException, Query, Depends
from typing import List, Dict, Optional
from datetime import datetime, timedelta

from backend.database import find_many, find_one, insert_one, update_one
from backend.models import Zone, Driver, RideRequest, GeoPoint, MapBounds
from backend.geo_utils import generate_zones_for_city, generate_zone_data, lat_lon_to_h3
from backend.simulation import simulation, active_zones, active_drivers, active_ride_requests
from config import (
    COLLECTION_ZONES,
    COLLECTION_DRIVERS,
    COLLECTION_RIDE_REQUESTS,
    COLLECTION_SURGE_HISTORY,
    DEFAULT_LAT,
    DEFAULT_LON,
    H3_RESOLUTION
)

router = APIRouter()

@router.get("/zones", response_model=List[Zone])
async def get_zones():
    """Get all zones with their current status"""
    zones = await find_many(COLLECTION_ZONES, {})
    return zones

@router.get("/zones/{zone_id}", response_model=Zone)
async def get_zone(zone_id: str):
    """Get a specific zone by ID"""
    zone = await find_one(COLLECTION_ZONES, {"zone_id": zone_id})
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    return zone

@router.get("/drivers", response_model=List[Driver])
async def get_drivers(status: Optional[str] = None):
    """Get all drivers, optionally filtered by status"""
    query = {}
    if status:
        query["status"] = status
    drivers = await find_many(COLLECTION_DRIVERS, query)
    return drivers

@router.get("/drivers/{driver_id}", response_model=Driver)
async def get_driver(driver_id: str):
    """Get a specific driver by ID"""
    driver = await find_one(COLLECTION_DRIVERS, {"id": driver_id})
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found")
    return driver

@router.get("/ride-requests", response_model=List[RideRequest])
async def get_ride_requests(status: Optional[str] = None):
    """Get all ride requests, optionally filtered by status"""
    query = {}
    if status:
        query["status"] = status

    # Sort by created_at in descending order
    requests = await find_many(
        COLLECTION_RIDE_REQUESTS,
        query,
        sort=[("created_at", -1)]
    )
    return requests

@router.get("/ride-requests/{request_id}", response_model=RideRequest)
async def get_ride_request(request_id: str):
    """Get a specific ride request by ID"""
    request = await find_one(COLLECTION_RIDE_REQUESTS, {"id": request_id})
    if not request:
        raise HTTPException(status_code=404, detail="Ride request not found")
    return request

@router.post("/initialize-zones")
async def initialize_zones(
    center_lat: float = Query(DEFAULT_LAT),
    center_lon: float = Query(DEFAULT_LON),
    radius_km: float = Query(5.0),
    resolution: int = Query(H3_RESOLUTION)
):
    """Initialize zones for a city center"""
    # Generate zones
    zone_ids = generate_zones_for_city(center_lat, center_lon, radius_km, resolution)

    # Create zone documents
    zone_docs = []
    for zone_id in zone_ids:
        zone_doc = generate_zone_data(zone_id)
        zone_docs.append(zone_doc)

    # Insert into database
    for zone_doc in zone_docs:
        existing = await find_one(COLLECTION_ZONES, {"zone_id": zone_doc["zone_id"]})
        if not existing:
            await insert_one(COLLECTION_ZONES, zone_doc)

    # Update global active zones
    global active_zones
    active_zones = set(zone_ids)

    return {"message": f"Initialized {len(zone_ids)} zones", "zone_count": len(zone_ids)}

@router.post("/simulation/start")
async def start_simulation():
    """Start the simulation"""
    global active_zones  # <-- moved before usage

    # Make sure zones are initialized
    if not active_zones:
        zones = await find_many(COLLECTION_ZONES, {})
        if not zones:
            raise HTTPException(
                status_code=400,
                detail="No zones found. Initialize zones first."
            )
        active_zones = {zone["zone_id"] for zone in zones}

    # Start simulation
    await simulation.start(list(active_zones))
    return {"message": "Simulation started"}

@router.post("/simulation/stop")
async def stop_simulation():
    """Stop the simulation"""
    await simulation.stop()
    return {"message": "Simulation stopped"}

@router.get("/stats/surge-history")
async def get_surge_history(hours: int = Query(24)):
    """Get surge history for the past X hours"""
    start_time = datetime.utcnow() - timedelta(hours=hours)
    surge_events = await find_many(
        COLLECTION_SURGE_HISTORY,
        {"timestamp": {"$gte": start_time}},
        sort=[("timestamp", 1)]
    )
    return surge_events

@router.get("/stats/demand-by-zone")
async def get_demand_by_zone():
    """Get current demand levels for all zones"""
    zones = await find_many(COLLECTION_ZONES, {})
    result = []
    for zone in zones:
        result.append({
            "zone_id": zone["zone_id"],
            "demand_level": zone.get("demand_level", 0),
            "is_surge": zone.get("is_surge", False),
            "current_requests": zone.get("current_requests", 0),
            "drivers_count": zone.get("drivers_count", 0)
        })
    return result

@router.get("/geospatial/drivers-in-bounds")
async def get_drivers_in_bounds(bounds: MapBounds):
    """Get drivers within map bounds"""
    query = {
        "location": {
            "$geoWithin": {
                "$box": [
                    [bounds.west, bounds.south],
                    [bounds.east, bounds.north]
                ]
            }
        }
    }
    drivers = await find_many(COLLECTION_DRIVERS, query)
    return drivers

@router.get("/geospatial/requests-in-bounds")
async def get_requests_in_bounds(bounds: MapBounds):
    """Get ride requests within map bounds"""
    query = {
        "pickup_location": {
            "$geoWithin": {
                "$box": [
                    [bounds.west, bounds.south],
                    [bounds.east, bounds.north]
                ]
            }
        }
    }
    start_time = datetime.utcnow() - timedelta(hours=1)
    query["created_at"] = {"$gte": start_time}

    requests = await find_many(COLLECTION_RIDE_REQUESTS, query)
    return requests
