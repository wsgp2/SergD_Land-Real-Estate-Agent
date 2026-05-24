"""OSRM — реальное время в пути по графу OpenStreetMap.

Бесплатный публичный сервер: https://routing.openstreetmap.de/routed-car/
Без ключа, разумный rate limit (~1 req/sec для вежливости).

Endpoint:
    GET https://routing.openstreetmap.de/routed-car/route/v1/driving/{lon1},{lat1};{lon2},{lat2}
    ?overview=false&alternatives=false

Возвращает routes[0].distance (метры) и routes[0].duration (секунды).
Кеш в data/osrm_cache.db по округлённым координатам (6 знаков ≈ 11 см) —
для одинаковых пар запросов не лезем повторно.

Замечание: OSRM не учитывает пробки. Для «час пик» уmножай на 1.3-1.5.
Для точного с пробками — Yandex Routing API.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import httpx

OSRM_URL = "https://routing.openstreetmap.de/routed-car/route/v1/driving/"
CACHE_DB = Path("data/osrm_cache.db")
RATE_LIMIT_S = 1.1  # вежливость к публичному серверу

_RATE_LOCK = threading.Lock()
_LAST_CALL = 0.0
_CACHE_LOCK = threading.Lock()
_INIT = False


def _init_cache() -> None:
    global _INIT
    if _INIT:
        return
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS routes (
                key TEXT PRIMARY KEY,
                distance_m REAL,
                duration_s REAL,
                fetched_ts TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
    _INIT = True


def _key(lat1, lon1, lat2, lon2) -> str:
    return f"{lat1:.6f},{lon1:.6f}|{lat2:.6f},{lon2:.6f}"


def _cache_get(key: str) -> tuple[float | None, float | None] | None:
    with _CACHE_LOCK, sqlite3.connect(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT distance_m, duration_s FROM routes WHERE key=?", (key,)
        ).fetchone()
    return (row[0], row[1]) if row else None


def _cache_put(key: str, distance_m, duration_s) -> None:
    with _CACHE_LOCK, sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            "INSERT INTO routes (key, distance_m, duration_s) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET distance_m=excluded.distance_m, "
            "duration_s=excluded.duration_s, fetched_ts=CURRENT_TIMESTAMP",
            (key, distance_m, duration_s),
        )
        conn.commit()


def route(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> tuple[float | None, float | None]:
    """Возвращает (distance_km, duration_min) или (None, None) при ошибке."""
    global _LAST_CALL
    if lat1 is None or lon1 is None or lat2 is None or lon2 is None:
        return None, None
    _init_cache()
    key = _key(lat1, lon1, lat2, lon2)
    cached = _cache_get(key)
    if cached is not None:
        d, t = cached
        if d is None:
            return None, None
        return d / 1000.0, t / 60.0

    with _RATE_LOCK:
        elapsed = time.time() - _LAST_CALL
        if elapsed < RATE_LIMIT_S:
            time.sleep(RATE_LIMIT_S - elapsed)
        _LAST_CALL = time.time()

    coords = f"{lon1:.6f},{lat1:.6f};{lon2:.6f},{lat2:.6f}"
    try:
        r = httpx.get(
            OSRM_URL + coords,
            params={"overview": "false", "alternatives": "false"},
            headers={"User-Agent": "Ground-finder (github.com/wsgp2/SergD_Land-Real-Estate-Agent)"},
            timeout=20.0,
        )
        if r.status_code != 200:
            _cache_put(key, None, None)
            return None, None
        data = r.json()
        if data.get("code") != "Ok" or not data.get("routes"):
            _cache_put(key, None, None)
            return None, None
        route0 = data["routes"][0]
        d_m = float(route0["distance"])
        t_s = float(route0["duration"])
        _cache_put(key, d_m, t_s)
        return d_m / 1000.0, t_s / 60.0
    except Exception:
        return None, None
