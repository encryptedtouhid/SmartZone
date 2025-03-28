import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Set
import random

from backend.database import find_many, find_one, update_one, insert_one
from config import (
    COLLECTION_ZONES,
    COLLECTION_RIDE_REQUESTS,
    COLLECTION_DRIVERS,
    COLLECTION_SURGE_HISTORY,
    SURGE_THRESHOLD
)

logger = logging.getLogger(__name__)


class SurgeDetectionService:
    """Detects surge pricing conditions based on demand and supply"""

    def __init__(self):
        self.active_surges: Dict[str, float] = {}  # zone_id -> surge multiplier
        self.surge_task = None

    async def start(self):
        """Start the surge detection service"""
        if self.surge_task is None or self.surge_task.done():
            self.surge_task = asyncio.create_task(self._periodic_surge_detection())
            logger.info("Surge detection service started")

    async def stop(self):
        """Stop the surge detection service"""
        if self.surge_task:
            self.surge_task.cancel()
            self.surge_task = None
            logger.info("Surge detection service stopped")

    async def _periodic_surge_detection(self):
        """Periodically detect surge conditions"""
        try:
            while True:
                # Run surge detection every 30 seconds
                await asyncio.sleep(30)
                await self.detect_surge_zones()
        except asyncio.CancelledError:
            logger.info("Surge detection task cancelled")
        except Exception as e:
            logger.error(f"Error in surge detection: {str(e)}")

    async def detect_surge_zones(self):
        """Detect surge zones based on current conditions"""
        # Get all zones
        zones = await find_many(COLLECTION_ZONES, {})

        # Time window for recent requests (last 10 minutes)
        time_window = datetime.utcnow() - timedelta(minutes=10)

        # Check each zone
        for zone in zones:
            zone_id = zone["zone_id"]

            # Get request count in this zone in the time window
            request_count = await self._count_requests_in_zone(zone_id, time_window)

            # Get available driver count in this zone
            driver_count = await self._count_drivers_in_zone(zone_id)

            # Calculate demand/supply ratio
            ratio = request_count / max(1, driver_count)  # Avoid division by zero

            # Update zone's demand level (0-10 scale)
            demand_level = min(10, int(ratio * 2))
            await update_one(
                COLLECTION_ZONES,
                {"zone_id": zone_id},
                {"$set": {"demand_level": demand_level}}
            )

            # Check if this zone should have surge pricing
            is_surge = request_count >= SURGE_THRESHOLD and ratio > 1.5

            # If surge state changed, handle it
            if is_surge != zone.get("is_surge", False):
                await self._handle_surge_state_change(zone_id, is_surge, demand_level, ratio)

    async def _count_requests_in_zone(self, zone_id: str, since: datetime) -> int:
        """Count ride requests in a zone since a specific time"""
        count = 0
        requests = await find_many(
            COLLECTION_RIDE_REQUESTS,
            {
                "pickup_zone": zone_id,
                "created_at": {"$gte": since}
            }
        )
        return len(requests)

    async def _count_drivers_in_zone(self, zone_id: str) -> int:
        """Count available drivers in a zone"""
        drivers = await find_many(
            COLLECTION_DRIVERS,
            {
                "current_zone": zone_id,
                "status": "available"
            }
        )
        return len(drivers)

    async def _handle_surge_state_change(self, zone_id: str, is_surge: bool, demand_level: int, ratio: float):
        """Handle a change in surge state for a zone"""
        # Calculate surge multiplier
        multiplier = 1.0
        if is_surge:
            # Higher demand levels get higher multipliers
            # Between 1.2x and 3.0x
            multiplier = min(3.0, 1.0 + (demand_level / 10) * 2.0)

            # Round to nearest 0.1
            multiplier = round(multiplier * 10) / 10

            # Add to active surges
            self.active_surges[zone_id] = multiplier

            logger.info(f"Surge pricing activated in zone {zone_id} with {multiplier}x multiplier")
        else:
            # Remove from active surges
            if zone_id in self.active_surges:
                del self.active_surges[zone_id]

            logger.info(f"Surge pricing deactivated in zone {zone_id}")

        # Update zone
        await update_one(
            COLLECTION_ZONES,
            {"zone_id": zone_id},
            {"$set": {"is_surge": is_surge}}
        )

        # Record the surge event for history
        await insert_one(
            COLLECTION_SURGE_HISTORY,
            {
                "zone_id": zone_id,
                "timestamp": datetime.utcnow(),
                "demand_level": demand_level,
                "multiplier": multiplier,
                "active": is_surge,
                "demand_supply_ratio": ratio
            }
        )

    def get_surge_multiplier(self, zone_id: str) -> float:
        """Get the current surge multiplier for a zone"""
        return self.active_surges.get(zone_id, 1.0)

    async def get_all_surge_zones(self) -> List[Dict]:
        """Get all zones currently experiencing surge pricing"""
        surge_zones = await find_many(
            COLLECTION_ZONES,
            {"is_surge": True}
        )

        result = []
        for zone in surge_zones:
            result.append({
                "zone_id": zone["zone_id"],
                "demand_level": zone.get("demand_level", 0),
                "multiplier": self.active_surges.get(zone["zone_id"], 1.0)
            })

        return result


# Create a singleton instance
surge_service = SurgeDetectionService()