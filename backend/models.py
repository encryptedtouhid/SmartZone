from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple, Union
from pydantic import BaseModel, Field, validator
from uuid import uuid4


class GeoPoint(BaseModel):
    """GeoJSON Point format with [longitude, latitude] coordinates"""
    type: str = "Point"
    coordinates: List[float] = Field(..., min_items=2, max_items=2)

    @validator('coordinates')
    def validate_coordinates(cls, v):
        # Ensure longitude and latitude are within valid ranges
        lon, lat = v
        if not (-180 <= lon <= 180):
            raise ValueError(f"Longitude must be between -180 and 180, got {lon}")
        if not (-90 <= lat <= 90):
            raise ValueError(f"Latitude must be between -90 and 90, got {lat}")
        return v


class DriverStatus(str, Enum):
    OFFLINE = "offline"
    AVAILABLE = "available"
    BUSY = "busy"  # Picking up or with passenger


class Driver(BaseModel):
    """Model for a driver with location and status"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    vehicle_type: str
    location: GeoPoint
    heading: float = Field(..., ge=0, lt=360)  # Direction in degrees
    speed: float = Field(..., ge=0)  # Speed in km/h
    status: DriverStatus = DriverStatus.AVAILABLE
    current_zone: Optional[str] = None
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class RideRequestStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class RideRequest(BaseModel):
    """Model for a ride request"""
    id: str = Field(default_factory=lambda: str(uuid4()))
    user_id: str
    pickup_location: GeoPoint
    dropoff_location: GeoPoint
    pickup_zone: str
    dropoff_zone: str
    status: RideRequestStatus = RideRequestStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    driver_id: Optional[str] = None
    estimated_fare: float

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class Zone(BaseModel):
    """Model for a geographical zone"""
    zone_id: str  # H3 cell index as string
    center: GeoPoint
    boundary: List[List[float]]  # List of [lon, lat] pairs forming the boundary
    demand_level: int = 0
    is_surge: bool = False
    current_requests: int = 0
    average_wait_time: float = 0
    drivers_count: int = 0

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class SurgeEvent(BaseModel):
    """Model for a surge pricing event"""
    zone_id: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    demand_level: int
    multiplier: float  # Price multiplier
    active: bool = True

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class GeoFenceAlert(BaseModel):
    """Model for a geofence alert"""
    driver_id: str
    zone_id: str
    event_type: str  # "enter" or "exit"
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


class DemandPrediction(BaseModel):
    """Model for demand prediction"""
    zone_id: str
    timestamp: datetime
    predicted_demand: float
    confidence: float

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }


# WebSocket message models
class WebSocketMessage(BaseModel):
    """Base model for WebSocket messages"""
    type: str
    data: Dict


class MapBounds(BaseModel):
    """Model for map bounds"""
    north: float
    south: float
    east: float
    west: float