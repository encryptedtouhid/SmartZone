import logging
from datetime import datetime
from typing import Dict, List, Set, Tuple

from backend.database import insert_one, find_one, update_one
from backend.models import GeoFenceAlert
from config import COLLECTION_ZONES, COLLECTION_DRIVERS

logger = logging.getLogger(__name__)


class GeofencingService:
    """Manages geofencing alerts and zone transitions"""

    def __init__(self):
        # Track which drivers are in which zones
        self.driver_zones: Dict[str, str] = {}
        # Track geofence events to avoid duplicates
        self.recent_events: Set[Tuple[str, str, str]] = set()

    async def check_zone_transition(self, driver_id: str, old_zone: str, new_zone: str) -> bool:
        """
        Check if a driver has transitioned between zones and handle geofence events

        Args:
            driver_id: The ID of the driver
            old_zone: The previous zone ID
            new_zone: The new zone ID

        Returns:
            True if the driver has entered a surge zone, False otherwise
        """
        # Skip if old and new zones are the same
        if old_zone == new_zone:
            return False

        # Get zone data
        old_zone_data = await find_one(COLLECTION_ZONES, {"zone_id": old_zone}) or {}
        new_zone_data = await find_one(COLLECTION_ZONES, {"zone_id": new_zone}) or {}

        # Skip if either zone doesn't exist
        if not old_zone_data or not new_zone_data:
            return False

        # Check if driver is entering a surge zone
        entering_surge = not old_zone_data.get("is_surge", False) and new_zone_data.get("is_surge", False)

        # Check if driver is leaving a surge zone
        leaving_surge = old_zone_data.get("is_surge", False) and not new_zone_data.get("is_surge", False)

        # If either event occurred, create a geofence alert
        if entering_surge or leaving_surge:
            event_type = "enter" if entering_surge else "exit"
            zone_id = new_zone if entering_surge else old_zone

            # Create a unique event key to avoid duplicates
            event_key = (driver_id, zone_id, event_type)

            # Skip if this is a duplicate event (within recent events)
            if event_key in self.recent_events:
                return entering_surge

            # Add to recent events
            self.recent_events.add(event_key)

            # If we have too many recent events, remove oldest
            if len(self.recent_events) > 1000:
                self.recent_events.pop()

            # Create alert
            alert = GeoFenceAlert(
                driver_id=driver_id,
                zone_id=zone_id,
                event_type=event_type,
                timestamp=datetime.utcnow()
            )

            # Store in database - in a real system, this would be sent as a notification
            # But for this project, we'll just log it
            logger.info(f"Geofence alert: Driver {driver_id} {event_type}ed surge zone {zone_id}")

            # In a real app, we would also trigger a notification to the driver's device

            # Update driver's current zone in the database
            await update_one(
                COLLECTION_DRIVERS,
                {"id": driver_id},
                {"$set": {"current_zone": new_zone}}
            )

            # Return True if entered surge zone
            return entering_surge

        # Just update the driver's current zone
        await update_one(
            COLLECTION_DRIVERS,
            {"id": driver_id},
            {"$set": {"current_zone": new_zone}}
        )

        return False

    def get_currently_in_surge(self, driver_id: str) -> bool:
        """Check if a driver is currently in a surge zone"""
        # This would typically check the current state
        # For now, we'll use a simplistic approach
        return False  # Placeholder

    async def get_all_drivers_in_surge_zones(self) -> List[str]:
        """Get all drivers currently in surge zones"""
        # Query for drivers in surge zones
        surge_zones = await find_one(COLLECTION_ZONES, {"is_surge": True})
        surge_zone_ids = [zone["zone_id"] for zone in surge_zones]

        # Find drivers in these zones
        drivers = []
        for zone_id in surge_zone_ids:
            zone_drivers = await find_one(
                COLLECTION_DRIVERS,
                {"current_zone": zone_id}
            )
            drivers.extend([driver["id"] for driver in zone_drivers])

        return drivers


# Create a singleton instance
geofencing_service = GeofencingService()