"""Геокодинг адреса через бесплатный Nominatim (OpenStreetMap).

Nominatim требует:
  - валидный User-Agent с контактом;
  - не более 1 запроса в секунду;
  - bias-параметр (countrycodes) сильно ускоряет точность.

Возвращает (lat, lon) или (None, None).
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "Ground-finder (https://github.com/wsgp2/SergD_Land-Real-Estate-Agent)"
RATE_LIMIT_S = 1.05
CACHE_DB = Path("data/nominatim_cache.db")

_RATE_LOCK = threading.Lock()
_LAST_CALL = 0.0


def _init_cache() -> None:
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS geocache (
                address TEXT PRIMARY KEY,
                lat REAL, lon REAL,
                display_name TEXT,
                fetched_ts TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )


def _cache_get(address: str) -> tuple[float | None, float | None] | None:
    with sqlite3.connect(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT lat, lon FROM geocache WHERE address = ?", (address,)
        ).fetchone()
    if row is None:
        return None
    return (row[0], row[1])


def _cache_put(address: str, lat: float | None, lon: float | None, display: str | None) -> None:
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            "INSERT INTO geocache (address, lat, lon, display_name) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
            "display_name=excluded.display_name, fetched_ts=CURRENT_TIMESTAMP",
            (address, lat, lon, display),
        )
        conn.commit()


def geocode(address: str, *, country: str = "ru") -> tuple[float | None, float | None]:
    global _LAST_CALL
    if not address or not address.strip():
        return None, None
    _init_cache()
    cached = _cache_get(address)
    if cached is not None:
        return cached

    with _RATE_LOCK:
        elapsed = time.time() - _LAST_CALL
        if elapsed < RATE_LIMIT_S:
            time.sleep(RATE_LIMIT_S - elapsed)
        _LAST_CALL = time.time()

    try:
        r = httpx.get(
            NOMINATIM_URL,
            params={
                "q": address,
                "format": "json",
                "limit": 1,
                "countrycodes": country,
                "addressdetails": 0,
            },
            headers={"User-Agent": USER_AGENT, "Accept-Language": "ru"},
            timeout=15.0,
        )
        if r.status_code != 200:
            _cache_put(address, None, None, None)
            return None, None
        data = r.json()
        if not data:
            _cache_put(address, None, None, None)
            return None, None
        item = data[0]
        lat = float(item["lat"])
        lon = float(item["lon"])
        _cache_put(address, lat, lon, item.get("display_name"))
        return lat, lon
    except Exception:
        return None, None
