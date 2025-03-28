import logging
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import GEOSPHERE
from config import MONGO_URI, MONGO_DB, COLLECTION_DRIVERS, COLLECTION_RIDE_REQUESTS, COLLECTION_ZONES, \
    COLLECTION_SURGE_HISTORY

logger = logging.getLogger(__name__)


class Database:
    client = None
    db = None

    @classmethod
    async def connect(cls):
        """Connect to MongoDB and set up collections with proper indexes"""
        logger.info(f"Connecting to MongoDB at {MONGO_URI}")
        cls.client = AsyncIOMotorClient(MONGO_URI)
        cls.db = cls.client[MONGO_DB]

        # Set up geospatial indexes
        await cls._setup_indexes()
        logger.info(f"Connected to MongoDB database: {MONGO_DB}")

        return cls.db

    @classmethod
    async def close(cls):
        """Close the MongoDB connection"""
        if cls.client:
            cls.client.close()
            logger.info("Closed MongoDB connection")

    @classmethod
    async def _setup_indexes(cls):
        """Set up required indexes for collections"""
        # Drivers collection - 2dsphere index on location field
        await cls.db[COLLECTION_DRIVERS].create_index([("location", GEOSPHERE)])
        logger.info(f"Created geospatial index on {COLLECTION_DRIVERS}.location")

        # Ride requests collection - 2dsphere index on pickup_location field
        await cls.db[COLLECTION_RIDE_REQUESTS].create_index([("pickup_location", GEOSPHERE)])
        logger.info(f"Created geospatial index on {COLLECTION_RIDE_REQUESTS}.pickup_location")

        # Zones collection - index on zone_id
        await cls.db[COLLECTION_ZONES].create_index("zone_id", unique=True)
        logger.info(f"Created index on {COLLECTION_ZONES}.zone_id")

        # Time-based indexes for ride requests and surge history
        await cls.db[COLLECTION_RIDE_REQUESTS].create_index("created_at")
        await cls.db[COLLECTION_SURGE_HISTORY].create_index("timestamp")
        logger.info("Created time-based indexes")


# Helper functions for database operations
async def get_collection(collection_name):
    """Get a collection by name"""
    return Database.db[collection_name]


async def insert_one(collection_name, document):
    """Insert a single document into a collection"""
    collection = await get_collection(collection_name)
    result = await collection.insert_one(document)
    return result.inserted_id


async def find_one(collection_name, query):
    """Find a single document in a collection"""
    collection = await get_collection(collection_name)
    return await collection.find_one(query)


async def find_many(collection_name, query, limit=0, sort=None):
    """Find multiple documents in a collection"""
    collection = await get_collection(collection_name)
    cursor = collection.find(query)

    if sort:
        cursor = cursor.sort(sort)

    if limit > 0:
        cursor = cursor.limit(limit)

    return await cursor.to_list(length=limit if limit > 0 else None)


async def update_one(collection_name, query, update):
    """Update a single document in a collection"""
    collection = await get_collection(collection_name)
    result = await collection.update_one(query, update)
    return result.modified_count


async def delete_one(collection_name, query):
    """Delete a single document from a collection"""
    collection = await get_collection(collection_name)
    result = await collection.delete_one(query)
    return result.deleted_count