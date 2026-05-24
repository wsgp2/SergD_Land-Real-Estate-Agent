from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from rosreestr2coord.parser import Area


CADASTRAL_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d{1,6}\b")
CACHE_DB = Path("data/rosreestr_cache.db")
_CACHE_LOCK = threading.Lock()
_CACHE_INIT = False


def _init_cache() -> None:
    global _CACHE_INIT
    if _CACHE_INIT:
        return
    CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS cad_cache (
                cadastral_number TEXT PRIMARY KEY,
                payload TEXT,
                fetched_ts TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )
    _CACHE_INIT = True


@dataclass
class CadastralInfo:
    cadastral_number: str
    lat: float | None
    lon: float | None
    area_m2: float | None
    address: str | None
    permitted_use: str | None
    category: str | None
    cadastral_cost_rub: float | None


def extract_cadastral_number(text: str | None) -> str | None:
    if not text:
        return None
    match = CADASTRAL_RE.search(text)
    return match.group(0) if match else None


def lookup(
    cadastral_number: str,
    *,
    max_attempts: int = 3,
    use_cache: bool = True,
) -> CadastralInfo | None:
    _init_cache()
    if use_cache:
        cached = _cache_get(cadastral_number)
        if cached is not None:
            return cached  # may be CadastralInfo or None (negative cache)

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            area = Area(cadastral_number)
            feature = getattr(area, "feature", None) or {}
            geometry = feature.get("geometry") if isinstance(feature, dict) else None
            options = (feature.get("properties") or {}).get("options") or {}
            lat, lon = _polygon_centroid(geometry)

            if lat is None and lon is None and not options:
                # nothing found
                _cache_put(cadastral_number, None)
                return None

            info = CadastralInfo(
                cadastral_number=cadastral_number,
                lat=lat,
                lon=lon,
                area_m2=_to_float(options.get("land_record_area")),
                address=options.get("readable_address") or options.get("address"),
                permitted_use=options.get("permitted_use_established_by_document"),
                category=options.get("land_record_category_type"),
                cadastral_cost_rub=_to_float(options.get("cost_value")),
            )
            _cache_put(cadastral_number, info)
            return info
        except Exception as exc:
            last_exc = exc
            if attempt < max_attempts:
                time.sleep(1.0 * (2 ** (attempt - 1)))  # 1s, 2s, 4s
    # only cache negative result if it's clearly "not found", not transient
    return None


def _cache_get(cad: str) -> CadastralInfo | None:
    with _CACHE_LOCK, sqlite3.connect(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT payload FROM cad_cache WHERE cadastral_number = ?", (cad,)
        ).fetchone()
    if not row:
        return None
    if row[0] is None or row[0] == "null":
        return None
    data = json.loads(row[0])
    return CadastralInfo(**data)


def _cache_put(cad: str, info: CadastralInfo | None) -> None:
    payload = json.dumps(asdict(info), ensure_ascii=False) if info else None
    with _CACHE_LOCK, sqlite3.connect(CACHE_DB) as conn:
        conn.execute(
            "INSERT INTO cad_cache (cadastral_number, payload) VALUES (?, ?) "
            "ON CONFLICT(cadastral_number) DO UPDATE SET payload=excluded.payload, fetched_ts=CURRENT_TIMESTAMP",
            (cad, payload),
        )
        conn.commit()


def _polygon_centroid(geometry: dict | None) -> tuple[float | None, float | None]:
    if not geometry or "coordinates" not in geometry:
        return None, None
    coords = geometry["coordinates"]
    points: list[tuple[float, float]] = []

    def _walk(node):
        if not isinstance(node, list):
            return
        if node and isinstance(node[0], (int, float)) and len(node) >= 2:
            points.append((float(node[0]), float(node[1])))
        else:
            for child in node:
                _walk(child)

    _walk(coords)
    if not points:
        return None, None
    lon = sum(p[0] for p in points) / len(points)
    lat = sum(p[1] for p in points) / len(points)
    return lat, lon


def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
