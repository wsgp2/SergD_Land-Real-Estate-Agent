"""Stage 6 — обогащение Rosreestr по уже собранным кадастрам.

Берёт все листинги с заполненным cadastral_number и подтягивает координаты + площадь + ВРИ +
кадастровую стоимость через rosreestr2coord. Прогресс параллельный (8 потоков), результаты
кешируются в data/rosreestr_cache.db, чтобы повторные запуски не дёргали API заново.

Использование:
    python scripts/reenrich_rosreestr.py [path/to/listings.db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

from ground_finder.config import DEFAULT
from ground_finder.enrichment.geo import within_drive_window
from ground_finder.enrichment.rosreestr import lookup

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT source, external_id, cadastral_number FROM listings "
        "WHERE cadastral_number IS NOT NULL"
    ).fetchall())
    print(f"Listings with cadastral_number: {len(rows)}")

    success = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futures = {ex.submit(_work, r): r for r in rows}
        done = 0
        for fut in as_completed(futures):
            info = fut.result()
            done += 1
            if info and info["lat"] is not None:
                in_window, drive_min = within_drive_window(info["lat"], info["lon"], DEFAULT)
                conn.execute(
                    "UPDATE listings SET lat=?, lon=?, est_drive_min=?, "
                    "address=COALESCE(?, address) "
                    "WHERE source=? AND external_id=?",
                    (info["lat"], info["lon"], drive_min, info["address"],
                     info["source"], info["external_id"]),
                )
                success += 1
            if done % 25 == 0:
                conn.commit()
                print(f"  progress: {done}/{len(rows)} (with coords: {success})")
    conn.commit()
    conn.close()
    print(f"Done. Coords resolved: {success}/{len(rows)}")


def _work(r):
    info = lookup(r["cadastral_number"])
    if not info:
        return None
    return {
        "source": r["source"], "external_id": r["external_id"],
        "lat": info.lat, "lon": info.lon, "address": info.address,
    }


if __name__ == "__main__":
    main()
