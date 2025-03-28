import asyncio
import random
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Set, Optional
import numpy as np
from faker import Faker
from uuid import uuid4

from backend.geo_utils import (
    lat_lon_to_h3,
    h3_to_lat_lon,
    get_random_point_in_zone,
    calculate_new_position,
    adjust_heading_towards_point
)
from backend.models import (
    Driver,
    DriverStatus,
    RideRequest,
    RideRequestStatus,
    GeoPoint
)
from backend.database import (
    insert_one,
    update_one,
    find_many,
    find_one
)
from config import (
    NUM_DRIVERS,
    REQUEST_RATE,
    SIMULATION_SPEED,
    COLLECTION_DRIVERS,
    COLLECTION_RIDE_REQUESTS,
    COLLECTION_ZONES,
    H3_RESOLUTION,
    DEFAULT_LAT,
    DEFAULT_LON
)

logger = logging.getLogger(__name__)
fake = Faker()

# Global state
active_zones = set()
active_drivers = {}
active_ride_requests = {}
websocket_connections = set()


class Simulation:
    """Manages the simulation of drivers and ride requests"""

    def __init__(self):
        self.running = False
        self.driver_task = None
        self.request_task = None
        self.surge_task = None
        self.time_multiplier = SIMULATION_SPEED
        self.driver_speeds = {}  # Random speed for each driver
        self.driver_destinations = {}  # Current destination for each driver

    async def start(self, zones: List[str]):
        """Start the simulation"""
        if self.running:
            return

        self.running = True
        global active_zones
        active_zones = set(zones)

        logger.info(f"Starting simulation with {NUM_DRIVERS} drivers and {len(active_zones)} zones")

        # Initialize drivers
        await self._initialize_drivers()

        # Start async tasks
        self.driver_task = asyncio.create_task(self._simulate_drivers())
        self.request_task = asyncio.create_task(self._simulate_ride_requests())
        self.surge_task = asyncio.create_task(self._update_surge_zones())

        logger.info("Simulation started")

    async def stop(self):
        """Stop the simulation"""
        if not self.running:
            return

        self.running = False

        # Cancel tasks
        if self.driver_task:
            self.driver_task.cancel()
        if self.request_task:
            self.request_task.cancel()
        if self.surge_task:
            self.surge_task.cancel()

        logger.info("Simulation stopped")

    async def _initialize_drivers(self):
        """Initialize the drivers at random positions within the zones"""
        global active_drivers
        active_drivers = {}

        # Select random zones for initial driver positions
        if not active_zones:
            logger.error("No active zones for driver initialization")
            return

        driver_zones = random.sample(list(active_zones), min(NUM_DRIVERS, len(active_zones)))
        if len(driver_zones) < NUM_DRIVERS:
            # If we have more drivers than zones, duplicate some zones
            driver_zones.extend(random.choices(list(active_zones), k=NUM_DRIVERS - len(driver_zones)))

        # Create drivers
        for i in range(NUM_DRIVERS):
            zone_id = driver_zones[i]
            lat, lon = h3_to_lat_lon(zone_id)

            # Add some randomness to position
            lat += random.uniform(-0.001, 0.001)
            lon += random.uniform(-0.001, 0.001)

            # Random heading
            heading = random.uniform(0, 360)

            # Random speed between 15-50 km/h
            speed = random.uniform(15, 50)
            self.driver_speeds[f"driver_{i + 1}"] = speed

            # Create driver object
            driver = Driver(
                id=f"driver_{i + 1}",
                name=fake.name(),
                vehicle_type=random.choice(["sedan", "suv", "compact"]),
                location=GeoPoint(coordinates=[lon, lat]),
                heading=heading,
                speed=speed,
                status=DriverStatus.AVAILABLE,
                current_zone=zone_id
            )

            # Insert into database
            driver_dict = driver.dict()
            await insert_one(COLLECTION_DRIVERS, driver_dict)

            # Add to active drivers
            active_drivers[driver.id] = driver

            # No initial destination
            self.driver_destinations[driver.id] = None

        logger.info(f"Initialized {NUM_DRIVERS} drivers")

    async def _simulate_drivers(self):
        """Simulate driver movement"""
        try:
            while self.running:
                start_time = time.time()

                # Update each driver's position
                for driver_id, driver in list(active_drivers.items()):
                    # Skip drivers that are offline
                    if driver.status == DriverStatus.OFFLINE:
                        continue

                    # If driver has no destination, set a new random one
                    if not self.driver_destinations.get(driver_id):
                        # Drivers without a ride request wander randomly
                        if driver.status == DriverStatus.AVAILABLE:
                            # Pick a random neighboring zone to head towards
                            destination_zone = random.choice(list(active_zones))
                            target_lat, target_lon = h3_to_lat_lon(destination_zone)

                            # Add some randomness
                            target_lat += random.uniform(-0.002, 0.002)
                            target_lon += random.uniform(-0.002, 0.002)

                            # Set as destination
                            self.driver_destinations[driver_id] = (target_lat, target_lon)

                    # Get current position
                    lon, lat = driver.location.coordinates

                    # If driver has a destination, adjust heading towards it
                    destination = self.driver_destinations.get(driver_id)
                    if destination:
                        target_lat, target_lon = destination

                        # Calculate distance to destination
                        dx = target_lon - lon
                        dy = target_lat - lat
                        distance = (dx ** 2 + dy ** 2) ** 0.5

                        # If close to destination, clear it
                        if distance < 0.0005:  # Approximately 50 meters
                            self.driver_destinations[driver_id] = None
                        else:
                            # Adjust heading towards destination
                            new_heading = adjust_heading_towards_point(
                                lat, lon, target_lat, target_lon, driver.heading
                            )
                            driver.heading = new_heading

                    # Calculate new position based on speed and heading
                    # Time passed in seconds with simulation speed factor
                    time_factor = 1.0 * self.time_multiplier
                    new_lat, new_lon = calculate_new_position(
                        lat, lon, driver.heading, driver.speed, time_factor
                    )

                    # Update driver position
                    driver.location.coordinates = [new_lon, new_lat]

                    # Update driver's current zone
                    new_zone = lat_lon_to_h3(new_lat, new_lon, H3_RESOLUTION)
                    if new_zone != driver.current_zone:
                        old_zone = driver.current_zone
                        driver.current_zone = new_zone

                        # Emit geofence event
                        await self._handle_geofence_event(driver_id, old_zone, new_zone)

                    # Update database
                    await update_one(
                        COLLECTION_DRIVERS,
                        {"id": driver_id},
                        {"$set": {
                            "location": driver.location.dict(),
                            "heading": driver.heading,
                            "current_zone": driver.current_zone,
                            "last_updated": datetime.utcnow()
                        }}
                    )

                # Update zone driver counts
                await self._update_zone_driver_counts()

                # Broadcast driver updates to connected clients
                await self._broadcast_driver_updates()

                # Sleep for a short time (adjusted by time_multiplier)
                elapsed = time.time() - start_time
                sleep_time = max(0.1, 1.0 / self.time_multiplier - elapsed)
                await asyncio.sleep(sleep_time)

        except asyncio.CancelledError:
            logger.info("Driver simulation task cancelled")
        except Exception as e:
            logger.error(f"Error in driver simulation: {str(e)}")

    async def _simulate_ride_requests(self):
        """Simulate ride requests"""
        try:
            # Calculate average time between requests
            avg_seconds_between_requests = 60.0 / REQUEST_RATE

            while self.running:
                # Wait for random time based on request rate
                wait_time = random.expovariate(1.0 / avg_seconds_between_requests)
                wait_time /= self.time_multiplier  # Adjust for simulation speed
                await asyncio.sleep(wait_time)

                # Skip if no zones available
                if not active_zones:
                    continue

                # Generate a ride request
                # Pick random pickup and dropoff zones with higher probability in certain zones
                zone_weights = await self._get_zone_weights()
                pickup_zone = random.choices(list(active_zones), weights=zone_weights, k=1)[0]

                # Pick a different zone for dropoff
                dropoff_zone = pickup_zone
                while dropoff_zone == pickup_zone:
                    dropoff_zone = random.choice(list(active_zones))

                # Generate random points within the zones
                pickup_lat, pickup_lon = get_random_point_in_zone(pickup_zone)
                dropoff_lat, dropoff_lon = get_random_point_in_zone(dropoff_zone)

                # Create the ride request
                estimated_fare = random.uniform(5, 30)  # Random fare between $5-$30

                ride_request = RideRequest(
                    user_id=f"user_{uuid4().hex[:8]}",
                    pickup_location=GeoPoint(coordinates=[pickup_lon, pickup_lat]),
                    dropoff_location=GeoPoint(coordinates=[dropoff_lon, dropoff_lat]),
                    pickup_zone=pickup_zone,
                    dropoff_zone=dropoff_zone,
                    status=RideRequestStatus.PENDING,
                    estimated_fare=estimated_fare
                )

                # Insert into database
                request_dict = ride_request.dict()
                request_id = await insert_one(COLLECTION_RIDE_REQUESTS, request_dict)

                # Add to active requests
                request_dict["_id"] = request_id
                active_ride_requests[ride_request.id] = ride_request

                # Update zone request count
                await self._increment_zone_request_count(pickup_zone)

                # Find nearby driver to assign to this request
                await self._assign_driver_to_request(ride_request)

                # Log the new request
                logger.info(f"New ride request {ride_request.id} created in zone {pickup_zone}")

                # Broadcast request update
                await self._broadcast_request_updates()

        except asyncio.CancelledError:
            logger.info("Ride request simulation task cancelled")
        except Exception as e:
            logger.error(f"Error in ride request simulation: {str(e)}")

    async def _update_surge_zones(self):
        """Update surge status for zones based on demand"""
        try:
            while self.running:
                # Sleep for a short time
                await asyncio.sleep(5.0 / self.time_multiplier)

                # Update demand level and surge status for each zone
                await self._calculate_surge_zones()

                # Broadcast zone updates
                await self._broadcast_zone_updates()

        except asyncio.CancelledError:
            logger.info("Surge zone update task cancelled")
        except Exception as e:
            logger.error(f"Error in surge zone update: {str(e)}")

    async def _get_zone_weights(self) -> List[float]:
        """Get weights for zones based on time of day and historical patterns"""
        # In a real system, this would use ML models and historical data
        # For simulation, we'll use a simple approach

        # Get current hour (0-23)
        current_hour = datetime.now().hour

        # Base weights - all zones start with 1.0
        weights = [1.0] * len(active_zones)

        # Convert to list for indexing
        zones_list = list(active_zones)

        # Modify weights based on time of day (simplified)
        for i, zone in enumerate(zones_list):
            # Random but consistent weight multiplier for each zone
            # We use hash of zone_id to get consistent randomness
            zone_hash = hash(zone) % 1000 / 1000.0  # 0.0 to 1.0

            # Morning rush hour (7-9 AM)
            if 7 <= current_hour < 9:
                # Residential areas have higher demand in morning
                weights[i] *= 1.0 + zone_hash * 2.0

            # Evening rush hour (5-7 PM)
            elif 17 <= current_hour < 19:
                # Business districts have higher demand in evening
                weights[i] *= 1.0 + (1.0 - zone_hash) * 2.0

            # Late night (10 PM - 2 AM)
            elif current_hour >= 22 or current_hour < 2:
                # Entertainment areas have higher demand at night
                if zone_hash > 0.7:
                    weights[i] *= 3.0

            # Add some randomness
            weights[i] *= random.uniform(0.8, 1.2)

        return weights

    async def _assign_driver_to_request(self, ride_request: RideRequest):
        """Find and assign the nearest available driver to a ride request"""
        # Get pickup coordinates
        pickup_lon, pickup_lat = ride_request.pickup_location.coordinates

        # Find available drivers
        available_drivers = [driver for driver in active_drivers.values()
                             if driver.status == DriverStatus.AVAILABLE]

        if not available_drivers:
            logger.info(f"No available drivers for request {ride_request.id}")
            return

        # Calculate distance to each driver
        driver_distances = []
        for driver in available_drivers:
            driver_lon, driver_lat = driver.location.coordinates
            # Simple Euclidean distance for simulation purposes
            distance = ((driver_lon - pickup_lon) ** 2 + (driver_lat - pickup_lat) ** 2) ** 0.5
            driver_distances.append((driver, distance))

        # Sort by distance
        driver_distances.sort(key=lambda x: x[1])

        # Assign to nearest driver
        nearest_driver, _ = driver_distances[0]

        # Update request
        ride_request.status = RideRequestStatus.ACCEPTED
        ride_request.driver_id = nearest_driver.id

        # Update database
        await update_one(
            COLLECTION_RIDE_REQUESTS,
            {"id": ride_request.id},
            {"$set": {
                "status": RideRequestStatus.ACCEPTED.value,
                "driver_id": nearest_driver.id
            }}
        )

        # Update driver status
        nearest_driver.status = DriverStatus.BUSY
        await update_one(
            COLLECTION_DRIVERS,
            {"id": nearest_driver.id},
            {"$set": {"status": DriverStatus.BUSY.value}}
        )

        # Set driver destination to pickup location
        self.driver_destinations[nearest_driver.id] = (pickup_lat, pickup_lon)

        logger.info(f"Assigned driver {nearest_driver.id} to request {ride_request.id}")

        # Simulate the ride lifecycle in a separate task
        asyncio.create_task(self._simulate_ride_lifecycle(ride_request, nearest_driver))

    async def _simulate_ride_lifecycle(self, ride_request: RideRequest, driver: Driver):
        """Simulate the full lifecycle of a ride"""
        try:
            # Wait for driver to reach pickup point
            while self.running:
                # Get current driver location
                driver_lon, driver_lat = driver.location.coordinates
                pickup_lon, pickup_lat = ride_request.pickup_location.coordinates

                # Calculate distance to pickup
                distance = ((driver_lon - pickup_lon) ** 2 + (driver_lat - pickup_lat) ** 2) ** 0.5

                # If close enough to pickup, break
                if distance < 0.0005:  # Approximately 50 meters
                    break

                await asyncio.sleep(0.5 / self.time_multiplier)

                # Reload driver data in case it's changed
                driver_data = await find_one(COLLECTION_DRIVERS, {"id": driver.id})
                if driver_data:
                    driver.location.coordinates = driver_data["location"]["coordinates"]

            # Driver has arrived at pickup location
            logger.info(f"Driver {driver.id} arrived at pickup for request {ride_request.id}")

            # Update request status to in progress
            ride_request.status = RideRequestStatus.IN_PROGRESS
            await update_one(
                COLLECTION_RIDE_REQUESTS,
                {"id": ride_request.id},
                {"$set": {"status": RideRequestStatus.IN_PROGRESS.value}}
            )

            # Set destination to dropoff
            dropoff_lon, dropoff_lat = ride_request.dropoff_location.coordinates
            self.driver_destinations[driver.id] = (dropoff_lat, dropoff_lon)

            # Wait for driver to reach dropoff point
            while self.running:
                # Get current driver location
                driver_lon, driver_lat = driver.location.coordinates

                # Calculate distance to dropoff
                distance = ((driver_lon - dropoff_lon) ** 2 + (driver_lat - dropoff_lat) ** 2) ** 0.5

                # If close enough to dropoff, break
                if distance < 0.0005:  # Approximately 50 meters
                    break

                await asyncio.sleep(0.5 / self.time_multiplier)

                # Reload driver data
                driver_data = await find_one(COLLECTION_DRIVERS, {"id": driver.id})
                if driver_data:
                    driver.location.coordinates = driver_data["location"]["coordinates"]

            # Driver has arrived at dropoff location
            logger.info(f"Driver {driver.id} completed request {ride_request.id}")

            # Update request status to completed
            ride_request.status = RideRequestStatus.COMPLETED
            await update_one(
                COLLECTION_RIDE_REQUESTS,
                {"id": ride_request.id},
                {"$set": {"status": RideRequestStatus.COMPLETED.value}}
            )

            # Remove from active requests
            if ride_request.id in active_ride_requests:
                del active_ride_requests[ride_request.id]

            # Update driver status back to available
            driver.status = DriverStatus.AVAILABLE
            await update_one(
                COLLECTION_DRIVERS,
                {"id": driver.id},
                {"$set": {"status": DriverStatus.AVAILABLE.value}}
            )

            # Clear driver destination
            self.driver_destinations[driver.id] = None

            # Broadcast updates
            await self._broadcast_driver_updates()
            await self._broadcast_request_updates()

        except Exception as e:
            logger.error(f"Error in ride lifecycle: {str(e)}")

    async def _update_zone_driver_counts(self):
        """Update the count of drivers in each zone"""
        # Initialize counts
        zone_counts = {zone: 0 for zone in active_zones}

        # Count drivers per zone
        for driver in active_drivers.values():
            if driver.current_zone in zone_counts:
                zone_counts[driver.current_zone] += 1

        # Update database
        for zone, count in zone_counts.items():
            await update_one(
                COLLECTION_ZONES,
                {"zone_id": zone},
                {"$set": {"drivers_count": count}}
            )

    async def _increment_zone_request_count(self, zone_id: str):
        """Increment the request count for a zone"""
        await update_one(
            COLLECTION_ZONES,
            {"zone_id": zone_id},
            {"$inc": {"current_requests": 1}}
        )

    async def _calculate_surge_zones(self):
        """Calculate which zones should have surge pricing based on demand"""
        from config import SURGE_THRESHOLD

        # Get all zones with their current request counts
        zones = await find_many(COLLECTION_ZONES, {})

        for zone in zones:
            # Calculate demand level (0-10 scale)
            current_requests = zone.get("current_requests", 0)
            drivers_count = zone.get("drivers_count", 0)

            # Avoid division by zero
            if drivers_count == 0:
                drivers_count = 1

            # Demand level increases with more requests and fewer drivers
            demand_ratio = current_requests / drivers_count
            demand_level = min(10, int(demand_ratio * 2))

            # Determine if this is a surge zone
            is_surge = current_requests >= SURGE_THRESHOLD

            # Update zone
            await update_one(
                COLLECTION_ZONES,
                {"zone_id": zone["zone_id"]},
                {"$set": {
                    "demand_level": demand_level,
                    "is_surge": is_surge
                }}
            )

            # If surge status changed, log it
            if is_surge != zone.get("is_surge", False):
                status = "activated" if is_surge else "deactivated"
                logger.info(f"Surge pricing {status} for zone {zone['zone_id']}")

    async def _handle_geofence_event(self, driver_id: str, old_zone: str, new_zone: str):
        """Handle a driver crossing a zone boundary"""
        # Check if entering or leaving a surge zone
        old_zone_data = await find_one(COLLECTION_ZONES, {"zone_id": old_zone})
        new_zone_data = await find_one(COLLECTION_ZONES, {"zone_id": new_zone})

        if not old_zone_data or not new_zone_data:
            return

        # Get driver
        driver = active_drivers.get(driver_id)
        if not driver:
            return

        # Entering a surge zone
        if not old_zone_data.get("is_surge", False) and new_zone_data.get("is_surge", False):
            logger.info(f"Driver {driver_id} entered surge zone {new_zone}")

            # In a real system, we would send a notification to the driver
            # For simulation, we'll just log it

        # Leaving a surge zone
        elif old_zone_data.get("is_surge", False) and not new_zone_data.get("is_surge", False):
            logger.info(f"Driver {driver_id} left surge zone {old_zone}")

    async def _broadcast_driver_updates(self):
        """Broadcast driver updates to all connected clients"""
        # In the WebSocket handler, we'll implement this
        pass

    async def _broadcast_request_updates(self):
        """Broadcast ride request updates to all connected clients"""
        # In the WebSocket handler, we'll implement this
        pass

    async def _broadcast_zone_updates(self):
        """Broadcast zone updates to all connected clients"""
        # In the WebSocket handler, we'll implement this
        pass


# Singleton instance
simulation = Simulation()