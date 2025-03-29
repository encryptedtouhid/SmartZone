import math
import h3
import numpy as np
from typing import Dict, List, Tuple, Union
from shapely.geometry import Point, Polygon
import geojson
import random
from config import H3_RESOLUTION, DEFAULT_LAT, DEFAULT_LON

# Constants
EARTH_RADIUS_KM = 6371.0  # Earth's radius in kilometers

def lat_lon_to_h3(lat: float, lon: float, resolution: int = H3_RESOLUTION) -> str:
    """Convert latitude and longitude to H3 cell index"""
    return h3.geo_to_h3(lat, lon, resolution)

def h3_to_lat_lon(h3_index: str) -> Tuple[float, float]:
    """Convert H3 cell index to latitude and longitude (center point)"""
    lat, lon = h3.h3_to_geo(h3_index)
    return lat, lon

def h3_to_boundary(h3_index: str) -> List[List[float]]:
    """Get boundary coordinates for an H3 cell index"""
    boundary = h3.h3_to_geo_boundary(h3_index)
    return [[lon, lat] for lat, lon in boundary]

def h3_to_geojson(h3_index: str) -> Dict:
    """Convert H3 cell to GeoJSON polygon"""
    boundary_coords = h3_to_boundary(h3_index)
    boundary_coords.append(boundary_coords[0])
    return {
        "type": "Feature",
        "properties": {"h3_index": h3_index},
        "geometry": {
            "type": "Polygon",
            "coordinates": [boundary_coords]
        }
    }

def get_neighboring_zones(h3_index: str, k_ring: int = 1) -> List[str]:
    """Get the neighboring zones within k rings"""
    return h3.k_ring(h3_index, k_ring)

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    distance = EARTH_RADIUS_KM * c
    return distance

def get_random_point_in_zone(h3_index: str) -> Tuple[float, float]:
    """Generate a random point within an H3 zone"""
    boundary = h3.h3_to_geo_boundary(h3_index)
    polygon = Polygon([(lon, lat) for lat, lon in boundary])  # ensure correct (x, y)
    minx, miny, maxx, maxy = polygon.bounds

    while True:
        p_lat = random.uniform(miny, maxy)
        p_lon = random.uniform(minx, maxx)
        point = Point(p_lon, p_lat)  # Correct order for shapely
        if polygon.contains(point):
            return p_lat, p_lon

def generate_zones_for_city(center_lat: float = DEFAULT_LAT,
                            center_lon: float = DEFAULT_LON,
                            radius_km: float = 5.0,
                            resolution: int = H3_RESOLUTION) -> List[str]:
    center_h3 = h3.geo_to_h3(center_lat, center_lon, resolution)
    hex_radius_km = h3.edge_length(resolution) * math.sqrt(3) / 2.0
    num_rings = math.ceil(radius_km / hex_radius_km)
    zones = h3.k_ring(center_h3, num_rings)

    result_zones = []
    for zone in zones:
        zone_center_lat, zone_center_lon = h3.h3_to_geo(zone)
        distance = haversine_distance(center_lat, center_lon, zone_center_lat, zone_center_lon)
        if distance <= radius_km:
            result_zones.append(zone)

    return result_zones

def generate_zone_data(h3_index: str) -> Dict:
    lat, lon = h3_to_lat_lon(h3_index)
    boundary = h3_to_boundary(h3_index)
    return {
        "zone_id": h3_index,
        "center": {
            "type": "Point",
            "coordinates": [lon, lat]
        },
        "boundary": boundary,
        "demand_level": 0,
        "is_surge": False,
        "current_requests": 0,
        "average_wait_time": 0.0,
        "drivers_count": 0
    }

def calculate_new_position(lat: float, lon: float, heading: float,
                           speed_kmh: float, time_seconds: float) -> Tuple[float, float]:
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    heading_rad = math.radians(heading)
    distance_km = speed_kmh * (time_seconds / 3600.0)
    angular_distance = distance_km / EARTH_RADIUS_KM

    new_lat_rad = math.asin(
        math.sin(lat_rad) * math.cos(angular_distance) +
        math.cos(lat_rad) * math.sin(angular_distance) * math.cos(heading_rad)
    )

    new_lon_rad = lon_rad + math.atan2(
        math.sin(heading_rad) * math.sin(angular_distance) * math.cos(lat_rad),
        math.cos(angular_distance) - math.sin(lat_rad) * math.sin(new_lat_rad)
    )

    new_lat = math.degrees(new_lat_rad)
    new_lon = math.degrees(new_lon_rad)

    return new_lat, new_lon

def point_in_polygon(point: Tuple[float, float], polygon: List[List[float]]) -> bool:
    shapely_polygon = Polygon([(lon, lat) for lon, lat in polygon])
    shapely_point = Point(point[1], point[0])
    return shapely_polygon.contains(shapely_point)

def adjust_heading_towards_point(current_lat: float, current_lon: float,
                                 target_lat: float, target_lon: float,
                                 current_heading: float, max_adjustment: float = 30.0) -> float:
    current_lat_rad = math.radians(current_lat)
    current_lon_rad = math.radians(current_lon)
    target_lat_rad = math.radians(target_lat)
    target_lon_rad = math.radians(target_lon)

    y = math.sin(target_lon_rad - current_lon_rad) * math.cos(target_lat_rad)
    x = math.cos(current_lat_rad) * math.sin(target_lat_rad) - \
        math.sin(current_lat_rad) * math.cos(target_lat_rad) * math.cos(target_lon_rad - current_lon_rad)

    target_bearing = math.degrees(math.atan2(y, x)) % 360
    heading_diff = (target_bearing - current_heading + 180) % 360 - 180

    if abs(heading_diff) > max_adjustment:
        heading_diff = max_adjustment if heading_diff > 0 else -max_adjustment

    new_heading = (current_heading + heading_diff) % 360
    return new_heading
