"""
Seed data generator for SmartZone
This script can be used to generate initial data for testing
"""

import asyncio
import logging
import random
import sys
import os
from datetime import datetime, timedelta
from typing import List, Dict
from faker import Faker
import json
import pymongo
from pymongo import MongoClient

# Add parent directory to path to import modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import (
    MONGO_URI,
    MONGO_DB,
    COLLECTION_ZONES,
    COLLECTION_DRIVERS,
    COLLECTION_RIDE_REQUESTS,
    COLLECTION_SURGE_HISTORY,
    DEFAULT_LAT,
    DEFAULT_LON,
    H3_RESOLUTION
)
from backend.geo_utils import (
    generate_zones_for_city,
    generate_zone_data,
    h3_to_lat_lon,
    get_random_point_in_zone
)
from backend.models import (
    Driver,
    DriverStatus,
    RideRequest,
    RideRequestStatus,
    GeoPoint,
    SurgeEvent
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize Faker
fake = Faker()


class DataSeeder:
    """Generate seed data for testing"""

    def __init__(self, uri: str = MONGO_URI, db_name: str = MONGO_DB):
        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        self.fake = Faker()

    def init_database(self):
        """Initialize database with collections and indexes"""
        self.db[COLLECTION_DRIVERS].create_index([("location", pymongo.GEOSPHERE)])
        self.db[COLLECTION_RIDE_REQUESTS].create_index([("pickup_location", pymongo.GEOSPHERE)])
        self.db[COLLECTION_ZONES].create_index("zone_id", unique=True)
        self.db[COLLECTION_RIDE_REQUESTS].create_index("created_at")
        self.db[COLLECTION_SURGE_HISTORY].create_index("timestamp")
        logger.info("Initialized database indexes")

    def clear_collections(self):
        """Clear all collections"""
        collections = [
            COLLECTION_ZONES,
            COLLECTION_DRIVERS,
            COLLECTION_RIDE_REQUESTS,
            COLLECTION_SURGE_HISTORY
        ]
        for collection in collections:
            self.db[collection].delete_many({})
        logger.info("Cleared all collections")

    def create_zones(self, city_lat: float = DEFAULT_LAT, city_lon: float = DEFAULT_LON,
                     radius_km: float = 5.0, resolution: int = H3_RESOLUTION) -> List[str]:
        logger.info(f"Generating zones for city at ({city_lat}, {city_lon})")
        zone_ids = generate_zones_for_city(city_lat, city_lon, radius_km, resolution)
        zones = [generate_zone_data(zone_id) for zone_id in zone_ids]
        if zones:
            self.db[COLLECTION_ZONES].insert_many(zones)
        logger.info(f"Created {len(zones)} zones")
        return zone_ids

    def create_drivers(self, num_drivers: int = 10, zone_ids: List[str] = None) -> List[Dict]:
        logger.info(f"Generating {num_drivers} drivers")
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]
        if not zone_ids:
            logger.error("No zones available for driver creation")
            return []
        drivers = []
        for i in range(num_drivers):
            zone_id = random.choice(zone_ids)
            lat, lon = h3_to_lat_lon(zone_id)
            lat += random.uniform(-0.001, 0.001)
            lon += random.uniform(-0.001, 0.001)
            driver = Driver(
                id=f"driver_{i + 1}",
                name=fake.name(),
                vehicle_type=random.choice(["sedan", "suv", "compact"]),
                location=GeoPoint(coordinates=[lon, lat]),
                heading=random.uniform(0, 360),
                speed=random.uniform(15, 50),
                status=random.choice(list(DriverStatus)),
                current_zone=zone_id
            )
            drivers.append(driver.model_dump())
        if drivers:
            self.db[COLLECTION_DRIVERS].insert_many(drivers)
        logger.info(f"Created {len(drivers)} drivers")
        return drivers

    def create_ride_requests(self, num_requests: int = 50, zone_ids: List[str] = None,
                             days_back: int = 7) -> List[Dict]:
        logger.info(f"Generating {num_requests} ride requests")
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]
        if not zone_ids:
            logger.error("No zones available for request creation")
            return []
        drivers = list(self.db[COLLECTION_DRIVERS].find({}, {"id": 1}))
        driver_ids = [driver["id"] for driver in drivers]
        if not driver_ids:
            driver_ids = [f"driver_{i + 1}" for i in range(10)]
        requests = []
        for i in range(num_requests):
            pickup_zone = random.choice(zone_ids)
            dropoff_zone = random.choice(zone_ids)
            pickup_lat, pickup_lon = get_random_point_in_zone(pickup_zone)
            dropoff_lat, dropoff_lon = get_random_point_in_zone(dropoff_zone)
            created_at = datetime.utcnow() - timedelta(
                days=random.uniform(0, days_back),
                hours=random.uniform(0, 24)
            )
            status_weights = [0.1, 0.1, 0.2, 0.5, 0.1]
            status = random.choices(
                list(RideRequestStatus),
                weights=status_weights
            )[0]
            driver_id = random.choice(driver_ids) if status != RideRequestStatus.PENDING else None
            estimated_fare = random.uniform(5, 30)
            user_id = f"user_{fake.uuid4()[:8]}"
            request = RideRequest(
                id=f"request_{i + 1}",
                user_id=user_id,
                pickup_location=GeoPoint(coordinates=[pickup_lon, pickup_lat]),
                dropoff_location=GeoPoint(coordinates=[dropoff_lon, dropoff_lat]),
                pickup_zone=pickup_zone,
                dropoff_zone=dropoff_zone,
                status=status,
                created_at=created_at,
                driver_id=driver_id,
                estimated_fare=estimated_fare
            )
            requests.append(request.model_dump())
        if requests:
            self.db[COLLECTION_RIDE_REQUESTS].insert_many(requests)
        logger.info(f"Created {len(requests)} ride requests")
        return requests

    def create_surge_history(self, num_events: int = 20, zone_ids: List[str] = None,
                             days_back: int = 7) -> List[Dict]:
        logger.info(f"Generating {num_events} surge events")
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]
        if not zone_ids:
            logger.error("No zones available for surge event creation")
            return []
        surge_events = []
        for i in range(num_events):
            zone_id = random.choice(zone_ids)
            timestamp = datetime.utcnow() - timedelta(
                days=random.uniform(0, days_back),
                hours=random.uniform(0, 24)
            )
            demand_level = int(min(10, max(1, random.normalvariate(5, 2))))
            multiplier = round((1.0 + (demand_level / 10) * 2.0) * 10) / 10
            time_factor = (datetime.utcnow() - timestamp).total_seconds() / (days_back * 86400)
            active_prob = max(0.1, 1.0 - time_factor)
            active = random.random() < active_prob
            event = SurgeEvent(
                zone_id=zone_id,
                timestamp=timestamp,
                demand_level=demand_level,
                multiplier=multiplier,
                active=active
            )
            surge_events.append(event.model_dump())
        if surge_events:
            self.db[COLLECTION_SURGE_HISTORY].insert_many(surge_events)
        logger.info(f"Created {len(surge_events)} surge events")
        return surge_events

    def seed_all(self, city_lat: float = DEFAULT_LAT, city_lon: float = DEFAULT_LON,
                 radius_km: float = 5.0, num_drivers: int = 10, num_requests: int = 50,
                 num_surge_events: int = 20, days_back: int = 7):
        self.clear_collections()
        self.init_database()
        zone_ids = self.create_zones(city_lat, city_lon, radius_km)
        self.create_drivers(num_drivers, zone_ids)
        self.create_ride_requests(num_requests, zone_ids, days_back)
        self.create_surge_history(num_surge_events, zone_ids, days_back)
        logger.info("Completed seeding all data")


if __name__ == "__main__":
    seeder = DataSeeder()
    import argparse
    parser = argparse.ArgumentParser(description="Seed data for SmartZone application")
    parser.add_argument("--city-lat", type=float, default=DEFAULT_LAT, help="City center latitude")
    parser.add_argument("--city-lon", type=float, default=DEFAULT_LON, help="City center longitude")
    parser.add_argument("--radius", type=float, default=5.0, help="Radius in kilometers")
    parser.add_argument("--drivers", type=int, default=10, help="Number of drivers to create")
    parser.add_argument("--requests", type=int, default=50, help="Number of ride requests to create")
    parser.add_argument("--surges", type=int, default=20, help="Number of surge events to create")
    parser.add_argument("--days", type=int, default=7, help="Days of historical data to generate")
    parser.add_argument("--clear", action="store_true", help="Clear collections without seeding")
    args = parser.parse_args()
    if args.clear:
        seeder.clear_collections()
    else:
        seeder.seed_all(
            city_lat=args.city_lat,
            city_lon=args.city_lon,
            radius_km=args.radius,
            num_drivers=args.drivers,
            num_requests=args.requests,
            num_surge_events=args.surges,
            days_back=args.days
        )
