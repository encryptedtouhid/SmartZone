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
        # Create geospatial index on drivers location
        self.db[COLLECTION_DRIVERS].create_index([("location", pymongo.GEOSPHERE)])

        # Create geospatial index on ride requests pickup location
        self.db[COLLECTION_RIDE_REQUESTS].create_index([("pickup_location", pymongo.GEOSPHERE)])

        # Create unique index on zone_id
        self.db[COLLECTION_ZONES].create_index("zone_id", unique=True)

        # Create time-based indexes
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
        """Create zones for a city"""
        logger.info(f"Generating zones for city at ({city_lat}, {city_lon})")

        # Generate H3 zones
        zone_ids = generate_zones_for_city(city_lat, city_lon, radius_km, resolution)

        # Create zone documents
        zones = []
        for zone_id in zone_ids:
            zone_doc = generate_zone_data(zone_id)
            zones.append(zone_doc)

        # Insert into database
        if zones:
            self.db[COLLECTION_ZONES].insert_many(zones)

        logger.info(f"Created {len(zones)} zones")
        return zone_ids

    def create_drivers(self, num_drivers: int = 10, zone_ids: List[str] = None) -> List[Dict]:
        """Create driver documents"""
        logger.info(f"Generating {num_drivers} drivers")

        # If no zones provided, fetch from database
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]

        if not zone_ids:
            logger.error("No zones available for driver creation")
            return []

        drivers = []
        for i in range(num_drivers):
            # Select random zone
            zone_id = random.choice(zone_ids)
            lat, lon = h3_to_lat_lon(zone_id)

            # Add some randomness to position
            lat += random.uniform(-0.001, 0.001)
            lon += random.uniform(-0.001, 0.001)

            # Create driver
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

            # Convert to dict and add
            drivers.append(driver.dict())

        # Insert into database
        if drivers:
            self.db[COLLECTION_DRIVERS].insert_many(drivers)

        logger.info(f"Created {len(drivers)} drivers")
        return drivers

    def create_ride_requests(self, num_requests: int = 50, zone_ids: List[str] = None,
                             days_back: int = 7) -> List[Dict]:
        """Create historical ride requests"""
        logger.info(f"Generating {num_requests} ride requests")

        # If no zones provided, fetch from database
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]

        if not zone_ids:
            logger.error("No zones available for request creation")
            return []

        # Get drivers
        drivers = list(self.db[COLLECTION_DRIVERS].find({}, {"id": 1}))
        driver_ids = [driver["id"] for driver in drivers]

        if not driver_ids:
            # Create some dummy driver IDs
            driver_ids = [f"driver_{i + 1}" for i in range(10)]

        requests = []
        for i in range(num_requests):
            # Select random zones for pickup and dropoff
            pickup_zone = random.choice(zone_ids)
            dropoff_zone = random.choice(zone_ids)

            # Generate points within the zones
            pickup_lat, pickup_lon = get_random_point_in_zone(pickup_zone)
            dropoff_lat, dropoff_lon = get_random_point_in_zone(dropoff_zone)

            # Random time in the past few days
            created_at = datetime.utcnow() - timedelta(
                days=random.uniform(0, days_back),
                hours=random.uniform(0, 24)
            )

            # Select random status, weighted towards completed
            status_weights = [0.1, 0.1, 0.2, 0.5, 0.1]  # Pending, Accepted, In Progress, Completed, Cancelled
            status = random.choices(
                list(RideRequestStatus),
                weights=status_weights
            )[0]

            # Assign driver for non-pending requests
            driver_id = None
            if status != RideRequestStatus.PENDING:
                driver_id = random.choice(driver_ids)

            # Random fare
            estimated_fare = random.uniform(5, 30)

            # Create request
            request = RideRequest(
                id=f"request_{i + 1}",
                user_id=f"user_{fake.uuid4().hex[:8]}",
                pickup_location=GeoPoint(coordinates=[pickup_lon, pickup_lat]),
                dropoff_location=GeoPoint(coordinates=[dropoff_lon, dropoff_lat]),
                pickup_zone=pickup_zone,
                dropoff_zone=dropoff_zone,
                status=status,
                created_at=created_at,
                driver_id=driver_id,
                estimated_fare=estimated_fare
            )

            # Convert to dict and add
            request_dict = request.dict()
            requests.append(request_dict)

        # Insert into database
        if requests:
            self.db[COLLECTION_RIDE_REQUESTS].insert_many(requests)

        logger.info(f"Created {len(requests)} ride requests")
        return requests

    def create_surge_history(self, num_events: int = 20, zone_ids: List[str] = None,
                             days_back: int = 7) -> List[Dict]:
        """Create historical surge events"""
        logger.info(f"Generating {num_events} surge events")

        # If no zones provided, fetch from database
        if not zone_ids:
            zones = list(self.db[COLLECTION_ZONES].find({}, {"zone_id": 1}))
            zone_ids = [zone["zone_id"] for zone in zones]

        if not zone_ids:
            logger.error("No zones available for surge event creation")
            return []

        surge_events = []
        for i in range(num_events):
            # Select random zone
            zone_id = random.choice(zone_ids)

            # Random time in the past few days
            timestamp = datetime.utcnow() - timedelta(
                days=random.uniform(0, days_back),
                hours=random.uniform(0, 24)
            )

            # Random demand level (higher probability for moderate levels)
            demand_level = int(min(10, max(1, random.normalvariate(5, 2))))

            # Surge multiplier based on demand level
            multiplier = 1.0 + (demand_level / 10) * 2.0
            multiplier = round(multiplier * 10) / 10  # Round to nearest 0.1

            # Random active state, weighted towards inactive for older events
            time_factor = (datetime.utcnow() - timestamp).total_seconds() / (days_back * 86400)
            active_prob = max(0.1, 1.0 - time_factor)
            active = random.random() < active_prob

            # Create surge event
            event = SurgeEvent(
                zone_id=zone_id,
                timestamp=timestamp,
                demand_level=demand_level,
                multiplier=multiplier,
                active=active
            )

            # Convert to dict and add
            surge_events.append(event.dict())

        # Insert into database
        if surge_events:
            self.db[COLLECTION_SURGE_HISTORY].insert_many(surge_events)

        logger.info(f"Created {len(surge_events)} surge events")
        return surge_events

    def seed_all(self, city_lat: float = DEFAULT_LAT, city_lon: float = DEFAULT_LON,
                 radius_km: float = 5.0, num_drivers: int = 10, num_requests: int = 50,
                 num_surge_events: int = 20, days_back: int = 7):
        """Seed all data"""
        # Clear existing data
        self.clear_collections()

        # Initialize database
        self.init_database()

        # Create zones
        zone_ids = self.create_zones(city_lat, city_lon, radius_km)

        # Create drivers
        self.create_drivers(num_drivers, zone_ids)

        # Create ride requests
        self.create_ride_requests(num_requests, zone_ids, days_back)

        # Create surge history
        self.create_surge_history(num_surge_events, zone_ids, days_back)

        logger.info("Completed seeding all data")


if __name__ == "__main__":
    seeder = DataSeeder()

    # Parse command line arguments
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