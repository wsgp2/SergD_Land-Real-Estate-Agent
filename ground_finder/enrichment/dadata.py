"""DaData геокодер — лучший на российских СНТ/ДНП/КП.

API:
  - URL: https://cleaner.dadata.ru/api/v1/clean/address (POST массив строк)
  - Auth: Authorization: Token <API_KEY>  + X-Secret: <SECRET_KEY>
  - Бесплатный лимит: 10 000 запросов/день
  - Документация: https://dadata.ru/api/clean/address/

Возвращает структурированный адрес + координаты (geo_lat, geo_lon) + flag качества
(qc_geo: 0=точные, 1=улица, 2=населённый пункт, 3=город, 4=регион, 5=не определены).
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

import httpx

CLEAN_URL = "https://cleaner.dadata.ru/api/v1/clean/address"
CACHE_DB = Path("data/dadata_cache.db")
_LOCK = threading.Lock()
_INIT = False


def _init_cache() -> None:
    global _INIT
    if _INIT:
        return
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS geocache (
                address TEXT PRIMARY KEY,
                lat REAL, lon REAL,
                qc_geo INTEGER,
                result TEXT,
                payload TEXT,
                fetched_ts TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
    _INIT = True


def _cache_get(address: str) -> dict | None:
    with _LOCK, sqlite3.connect(CACHE_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT lat, lon, qc_geo, result FROM geocache WHERE address=?", (address,)
        ).fetchone()
    return dict(row) if row else None


def _cache_put(address: str, lat, lon, qc_geo, result, payload) -> None:
    with _LOCK, sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            "INSERT INTO geocache (address, lat, lon, qc_geo, result, payload) "
            "VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(address) DO UPDATE SET lat=excluded.lat, lon=excluded.lon, "
            "qc_geo=excluded.qc_geo, result=excluded.result, payload=excluded.payload, "
            "fetched_ts=CURRENT_TIMESTAMP",
            (address, lat, lon, qc_geo, result, payload),
        )
        conn.commit()


def geocode(address: str) -> dict | None:
    """Возвращает dict {lat, lon, qc_geo, result} или None если адрес не нашёлся.

    qc_geo: 0 — точные координаты (дом/участок), 1 — улица, 2 — НП, 3 — город, 4 — регион,
    5 — не определены. Для drive_time нам годится 0-2.
    """
    if not address or not address.strip():
        return None
    _init_cache()
    cached = _cache_get(address)
    if cached is not None:
        return cached if cached.get("lat") is not None else None

    api_key = os.environ.get("DADATA_API_KEY")
    secret = os.environ.get("DADATA_SECRET_KEY")
    if not (api_key and secret):
        raise RuntimeError("DADATA_API_KEY / DADATA_SECRET_KEY not set in environment")

    try:
        r = httpx.post(
            CLEAN_URL,
            headers={
                "Authorization": f"Token {api_key}",
                "X-Secret": secret,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            content=json.dumps([address], ensure_ascii=False).encode("utf-8"),
            timeout=20.0,
        )
        if r.status_code != 200:
            _cache_put(address, None, None, None, f"HTTP {r.status_code}", r.text[:200])
            return None
        arr = r.json()
        if not arr:
            _cache_put(address, None, None, None, "empty", None)
            return None
        item = arr[0]
        lat = item.get("geo_lat")
        lon = item.get("geo_lon")
        qc_geo = item.get("qc_geo")
        result = item.get("result")
        if lat is None or lon is None:
            _cache_put(address, None, None, qc_geo, result, json.dumps(item, ensure_ascii=False))
            return None
        lat = float(lat)
        lon = float(lon)
        qc_geo = int(qc_geo) if qc_geo is not None else None
        payload = json.dumps(item, ensure_ascii=False)
        _cache_put(address, lat, lon, qc_geo, result, payload)
        return {"lat": lat, "lon": lon, "qc_geo": qc_geo, "result": result}
    except Exception:
        return None
