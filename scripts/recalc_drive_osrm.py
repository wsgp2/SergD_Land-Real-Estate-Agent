"""Пересчёт est_drive_min для всех листингов с координатами через OSRM.

Считает реальный автомобильный маршрут от якоря до точки участка
по графу OpenStreetMap. Заменяет грубую оценку haversine × road_factor
на точное время по дорогам (без учёта пробок).

Использование:
    python scripts/recalc_drive_osrm.py [path/to/listings.db]
"""
from __future__ import annotations

import sqlite3
import sys
import time

from ground_finder.config import DEFAULT
from ground_finder.enrichment.osrm import route

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"
ANCHOR_LAT = DEFAULT.anchor_lat
ANCHOR_LON = DEFAULT.anchor_lon


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "drive_km_osrm" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN drive_km_osrm REAL")
    if "drive_min_osrm" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN drive_min_osrm REAL")
    conn.commit()

    rows = list(conn.execute(
        "SELECT source, external_id, lat, lon FROM listings "
        "WHERE lat IS NOT NULL AND lon IS NOT NULL"
    ).fetchall())
    print(f"Listings with coords: {len(rows)}")
    print(f"Anchor: {ANCHOR_LAT}, {ANCHOR_LON}  ({DEFAULT.anchor_label})")

    success = 0
    in_25 = 0
    in_15 = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        km, mins = route(ANCHOR_LAT, ANCHOR_LON, r["lat"], r["lon"])
        if mins is not None:
            conn.execute(
                "UPDATE listings SET drive_km_osrm=?, drive_min_osrm=?, est_drive_min=? "
                "WHERE source=? AND external_id=?",
                (km, mins, mins, r["source"], r["external_id"]),
            )
            success += 1
            if mins <= 25:
                in_25 += 1
            if mins <= 15:
                in_15 += 1
        if i % 25 == 0:
            conn.commit()
            rate = i / (time.time() - t0)
            print(f"  [{i}/{len(rows)}] success={success} in_25={in_25} in_15={in_15} | {rate:.1f}/s")
    conn.commit()
    conn.close()
    print(f"\nDone. Routed: {success}/{len(rows)} | Within 25min: {in_25} | Within 15min: {in_15}")


if __name__ == "__main__":
    main()
