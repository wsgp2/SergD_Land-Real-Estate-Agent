"""DaData геокодинг для листингов без координат.

Использование:
    DADATA_API_KEY=... DADATA_SECRET_KEY=... \\
    python scripts/geocode_dadata.py [path/to/listings.db]

Записывает в lat/lon/est_drive_min только если qc_geo ≤ 2
(0=точно, 1=улица, 2=НП — этого достаточно для drive_time оценки).
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time

from ground_finder.config import DEFAULT
from ground_finder.enrichment.dadata import geocode
from ground_finder.enrichment.geo import within_drive_window

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"
QC_GEO_MAX = 2  # 0/1/2 годится; 3+ слишком грубо (только город/регион)


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = list(conn.execute(
        "SELECT source, external_id, llm_extraction, address FROM listings "
        "WHERE lat IS NULL AND llm_extraction IS NOT NULL"
    ).fetchall())
    print(f"Candidates (no coords yet): {len(rows)}")

    success = 0
    too_coarse = 0
    in_25 = 0
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        try:
            llm = json.loads(r["llm_extraction"])
        except Exception:
            continue
        address = llm.get("full_address") or r["address"] or ""
        if not address:
            continue
        info = geocode(address)
        if info is None:
            continue
        qc = info.get("qc_geo")
        if qc is not None and qc > QC_GEO_MAX:
            too_coarse += 1
            continue
        in_window, drive_min = within_drive_window(info["lat"], info["lon"], DEFAULT)
        conn.execute(
            "UPDATE listings SET lat=?, lon=?, est_drive_min=? "
            "WHERE source=? AND external_id=?",
            (info["lat"], info["lon"], drive_min, r["source"], r["external_id"]),
        )
        success += 1
        if drive_min and drive_min <= 25:
            in_25 += 1
        if i % 25 == 0:
            conn.commit()
            rate = i / (time.time() - t0)
            print(f"  [{i}/{len(rows)}] success={success} (in 25min: {in_25}, too_coarse: {too_coarse}) | {rate:.1f}/s")
    conn.commit()
    conn.close()
    print(f"\nDone. Geocoded: {success}/{len(rows)} (within 25 min: {in_25}, too coarse: {too_coarse})")


if __name__ == "__main__":
    main()
