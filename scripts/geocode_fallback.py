"""Stage 8b — геокодинг через Nominatim для листингов без кадастра.

Берёт `full_address` из llm_extraction для тех, у кого нет lat/lon, проходит через
Nominatim (с rate limit 1 req/s и кешем), считает est_drive_min от якоря.

Использование:
    python scripts/geocode_fallback.py [path/to/listings.db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time

from ground_finder.config import DEFAULT
from ground_finder.enrichment.geo import within_drive_window
from ground_finder.enrichment.nominatim import geocode

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT source, external_id, llm_extraction FROM listings "
        "WHERE lat IS NULL AND llm_extraction IS NOT NULL"
    ).fetchall())
    print(f"Geocoding candidates (no coords, with LLM data): {len(rows)}")

    success = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        try:
            llm = json.loads(r["llm_extraction"])
        except Exception:
            continue
        address = llm.get("full_address") or ""
        if not address:
            continue
        lat, lon = geocode(address)
        if lat is not None:
            in_window, drive_min = within_drive_window(lat, lon, DEFAULT)
            conn.execute(
                "UPDATE listings SET lat=?, lon=?, est_drive_min=? "
                "WHERE source=? AND external_id=?",
                (lat, lon, drive_min, r["source"], r["external_id"]),
            )
            success += 1
        if i % 25 == 0:
            conn.commit()
            rate = i / (time.time() - t0)
            print(f"  [{i}/{len(rows)}] success={success} | {rate:.1f}/s")
    conn.commit()
    conn.close()
    print(f"Done. Geocoded: {success}/{len(rows)}")


if __name__ == "__main__":
    main()
