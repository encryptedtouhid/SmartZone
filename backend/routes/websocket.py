import json
import logging
import asyncio
from typing import Dict, List, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime

from backend.database import find_many
from backend.models import WebSocketMessage
from backend.simulation import (
    active_drivers,
    active_ride_requests,
    active_zones,
    websocket_connections
)
from config import (
    COLLECTION_DRIVERS,
    COLLECTION_RIDE_REQUESTS,
    COLLECTION_ZONES
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Store active WebSocket connections
connections: Set[WebSocket] = set()


class WebSocketManager:
    def __init__(self):
        self.connections: Set[WebSocket] = set()
        self.broadcast_task = None

    async def connect(self, websocket: WebSocket):
        """Handle new WebSocket connection"""
        await websocket.accept()
        self.connections.add(websocket)
        logger.info(f"New WebSocket connection. Total connections: {len(self.connections)}")

        # Start broadcast task if not running
        if self.broadcast_task is None or self.broadcast_task.done():
            self.broadcast_task = asyncio.create_task(self._periodic_broadcast())

    async def disconnect(self, websocket: WebSocket):
        """Handle WebSocket disconnection"""
        self.connections.remove(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.connections)}")

        # Cancel broadcast task if no more connections
        if not self.connections and self.broadcast_task:
            self.broadcast_task.cancel()
            self.broadcast_task = None

    async def broadcast(self, message: Dict):
        """Broadcast a message to all connected clients"""
        disconnected = set()

        for connection in self.connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting to client: {str(e)}")
                disconnected.add(connection)

        # Remove disconnected clients
        for connection in disconnected:
            self.connections.remove(connection)

    async def _periodic_broadcast(self):
        """Periodically broadcast updates to all clients"""
        try:
            while True:
                # Broadcast updates every 1 second
                await asyncio.sleep(1.0)

                # Skip if no connections
                if not self.connections:
                    continue

                # Broadcast driver locations
                await self._broadcast_drivers()

                # Broadcast zone updates
                await self._broadcast_zones()

                # Broadcast ride requests
                await self._broadcast_requests()

        except asyncio.CancelledError:
            logger.info("Periodic broadcast task cancelled")
        except Exception as e:
            logger.error(f"Error in periodic broadcast: {str(e)}")

    async def _broadcast_drivers(self):
        """Broadcast driver updates"""
        # Get current drivers from database (more up-to-date than in-memory)
        drivers = await find_many(COLLECTION_DRIVERS, {})

        # Format for frontend
        driver_data = []
        for driver in drivers:
            # Extract only needed fields
            driver_data.append({
                "id": driver["id"],
                "location": driver["location"],
                "status": driver["status"],
                "heading": driver["heading"],
                "current_zone": driver["current_zone"]
            })

        # Send driver updates
        message = {
            "type": "driver_updates",
            "data": {
                "drivers": driver_data,
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        await self.broadcast(message)


# Create WebSocket manager instance
manager = WebSocketManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates"""
    await manager.connect(websocket)

    try:
        while True:
            # Wait for messages from the client
            data = await websocket.receive_text()

            try:
                # Parse the message
                message = json.loads(data)

                # Handle client messages
                if message.get("type") == "ping":
                    # Send pong response
                    await websocket.send_json({"type": "pong", "timestamp": datetime.utcnow().isoformat()})

                elif message.get("type") == "subscribe":
                    # Client can subscribe to specific updates
                    # This is a placeholder for future functionality
                    pass

            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received: {data}")

    except WebSocketDisconnect:
        # Handle disconnection
        await manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await manager.disconnect(websocket)


# Expose the manager instance for simulation to use
def get_websocket_manager():
    """Get the WebSocket manager instance"""
    return manager

    async def _broadcast_zones(self):
        """Broadcast zone updates"""
        # Get current zones from database
        zones = await find_many(COLLECTION_ZONES, {})

        # Format for frontend
        zone_data = []
        for zone in zones:
            # Only send necessary data
            zone_data.append({
                "zone_id": zone["zone_id"],
                "center": zone["center"],
                "demand_level": zone.get("demand_level", 0),
                "is_surge": zone.get("is_surge", False),
                "current_requests": zone.get("current_requests", 0),
                "drivers_count": zone.get("drivers_count", 0)
            })

        # Send zone updates
        message = {
            "type": "zone_updates",
            "data": {
                "zones": zone_data,
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        await self.broadcast(message)

    async def _broadcast_requests(self):
        """Broadcast ride request updates"""
        # Get recent ride requests
        # Only get active requests (not completed or cancelled)
        requests = await find_many(
            COLLECTION_RIDE_REQUESTS,
            {"status": {"$in": ["pending", "accepted", "in_progress"]}},
            sort=[("created_at", -1)],
            limit=50
        )

        # Format for frontend
        request_data = []
        for req in requests:
            request_data.append({
                "id": req["id"],
                "pickup_location": req["pickup_location"],
                "dropoff_location": req["dropoff_location"],
                "status": req["status"],
                "created_at": req["created_at"].isoformat(),
                "driver_id": req.get("driver_id")
            })

        # Send request updates
        message = {
            "type": "request_updates",
            "data": {
                "requests": request_data,
                "timestamp": datetime.utcnow().isoformat()
            }
        }

        await self.broadcast(message)