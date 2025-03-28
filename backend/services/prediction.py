import logging
import asyncio
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
import joblib
import os.path
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split

from backend.database import find_many, insert_one
from config import COLLECTION_RIDE_REQUESTS, COLLECTION_ZONES

logger = logging.getLogger(__name__)


class DemandPredictionService:
    """Service for predicting ride demand in zones"""

    def __init__(self):
        self.models: Dict[str, Pipeline] = {}  # zone_id -> trained model
        self.prediction_task = None
        self.training_interval = 3600  # Train models every hour
        self.prediction_interval = 300  # Make predictions every 5 minutes
        self.model_dir = "data/models"
        self.feature_cols = [
            "hour_of_day", "day_of_week", "is_weekend",
            "is_morning_rush", "is_evening_rush"
        ]

    async def start(self):
        """Start the prediction service"""
        if self.prediction_task is None or self.prediction_task.done():
            # Make sure model directory exists
            os.makedirs(self.model_dir, exist_ok=True)

            # Start background task
            self.prediction_task = asyncio.create_task(self._run_prediction_service())
            logger.info("Demand prediction service started")

    async def stop(self):
        """Stop the prediction service"""
        if self.prediction_task:
            self.prediction_task.cancel()
            self.prediction_task = None
            logger.info("Demand prediction service stopped")

    async def _run_prediction_service(self):
        """Run the prediction service"""
        try:
            # Initial training
            await self._train_models()

            last_training = datetime.utcnow()

            while True:
                # Make predictions
                await self._make_predictions()

                # Retrain models periodically
                now = datetime.utcnow()
                if (now - last_training).total_seconds() >= self.training_interval:
                    await self._train_models()
                    last_training = now

                # Sleep until next prediction cycle
                await asyncio.sleep(self.prediction_interval)

        except asyncio.CancelledError:
            logger.info("Prediction service task cancelled")
        except Exception as e:
            logger.error(f"Error in prediction service: {str(e)}")

    async def _train_models(self):
        """Train prediction models for each zone"""
        logger.info("Training demand prediction models")

        # Get all zone IDs
        zones = await find_many(COLLECTION_ZONES, {})
        zone_ids = [zone["zone_id"] for zone in zones]

        # Get historical data (last 7 days)
        start_time = datetime.utcnow() - timedelta(days=7)
        requests = await find_many(
            COLLECTION_RIDE_REQUESTS,
            {"created_at": {"$gte": start_time}}
        )

        if not requests:
            logger.warning("No historical data available for training")
            return

        # Convert to pandas DataFrame
        df = pd.DataFrame(requests)

        # Train a model for each zone
        for zone_id in zone_ids:
            try:
                # Filter data for this zone
                zone_df = df[df["pickup_zone"] == zone_id].copy()

                # Skip if not enough data
                if len(zone_df) < 30:
                    logger.info(f"Not enough data to train model for zone {zone_id}")
                    continue

                # Extract features
                zone_df = self._extract_features(zone_df)

                # Aggregate by hour
                zone_df = zone_df.groupby([
                    "hour_of_day", "day_of_week", "is_weekend",
                    "is_morning_rush", "is_evening_rush"
                ]).size().reset_index(name="request_count")

                # Split into features and target
                X = zone_df[self.feature_cols]
                y = zone_df["request_count"]

                # Create and train model
                model = Pipeline([
                    ("scaler", StandardScaler()),
                    ("regressor", RandomForestRegressor(n_estimators=100, random_state=42))
                ])

                model.fit(X, y)

                # Save model
                self.models[zone_id] = model

                # Save to disk
                model_path = os.path.join(self.model_dir, f"model_{zone_id}.joblib")
                joblib.dump(model, model_path)

                logger.info(f"Trained model for zone {zone_id}")

            except Exception as e:
                logger.error(f"Error training model for zone {zone_id}: {str(e)}")

    async def _make_predictions(self):
        """Make demand predictions for each zone"""
        logger.info("Making demand predictions")

        # Get all zone IDs
        zones = await find_many(COLLECTION_ZONES, {})

        # Current time
        now = datetime.utcnow()

        # Make predictions for each hour in the next 6 hours
        for i in range(1, 7):
            # Future time
            future_time = now + timedelta(hours=i)

            # Create features for this time
            features = self._create_time_features(future_time)

            # Make predictions for each zone
            for zone in zones:
                zone_id = zone["zone_id"]

                if zone_id not in self.models:
                    # Try to load model from disk
                    model_path = os.path.join(self.model_dir, f"model_{zone_id}.joblib")
                    if os.path.exists(model_path):
                        self.models[zone_id] = joblib.load(model_path)
                    else:
                        continue

                # Make prediction
                model = self.models[zone_id]
                features_df = pd.DataFrame([features])

                try:
                    # Predict demand
                    prediction = model.predict(features_df)[0]
                    confidence = 0.8  # Placeholder - would be calculated from model metrics

                    # Store prediction in database
                    await insert_one(
                        "demand_predictions",
                        {
                            "zone_id": zone_id,
                            "timestamp": future_time,
                            "predicted_demand": float(prediction),
                            "confidence": confidence,
                            "prediction_made_at": now
                        }
                    )

                except Exception as e:
                    logger.error(f"Error making prediction for zone {zone_id}: {str(e)}")

    def _extract_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Extract time-based features from DataFrame"""
        # Convert created_at to datetime if needed
        if not pd.api.types.is_datetime64_dtype(df["created_at"]):
            df["created_at"] = pd.to_datetime(df["created_at"])

        # Extract features
        df["hour_of_day"] = df["created_at"].dt.hour
        df["day_of_week"] = df["created_at"].dt.dayofweek
        df["is_weekend"] = df["day_of_week"].isin([5, 6]).astype(int)
        df["is_morning_rush"] = df["hour_of_day"].between(7, 9).astype(int)
        df["is_evening_rush"] = df["hour_of_day"].between(17, 19).astype(int)

        return df

    def _create_time_features(self, dt: datetime) -> Dict:
        """Create time-based features for a datetime"""
        return {
            "hour_of_day": dt.hour,
            "day_of_week": dt.weekday(),
            "is_weekend": 1 if dt.weekday() >= 5 else 0,
            "is_morning_rush": 1 if 7 <= dt.hour <= 9 else 0,
            "is_evening_rush": 1 if 17 <= dt.hour <= 19 else 0
        }

    async def get_predictions(self, zone_id: Optional[str] = None, hours: int = 6) -> List[Dict]:
        """Get demand predictions for a zone or all zones"""
        # Calculate start time
        start_time = datetime.utcnow()

        # Query for predictions
        query = {"timestamp": {"$gte": start_time}}
        if zone_id:
            query["zone_id"] = zone_id

        predictions = await find_many(
            "demand_predictions",
            query,
            sort=[("timestamp", 1)]
        )

        return predictions


# Create a singleton instance
prediction_service = DemandPredictionService()