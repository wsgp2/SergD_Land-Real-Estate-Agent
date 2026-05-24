from __future__ import annotations

from math import asin, cos, radians, sin, sqrt

from ground_finder.config import SearchCriteria


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * asin(sqrt(a))


def within_drive_window(
    lat: float | None,
    lon: float | None,
    criteria: SearchCriteria,
) -> tuple[bool, float | None]:
    if lat is None or lon is None:
        return False, None
    distance = haversine_km(criteria.anchor_lat, criteria.anchor_lon, lat, lon)
    est_minutes = (distance * criteria.road_factor) / criteria.avg_drive_kmh * 60
    return est_minutes <= criteria.max_drive_minutes, est_minutes
