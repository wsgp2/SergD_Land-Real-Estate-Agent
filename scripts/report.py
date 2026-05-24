"""Финальный отчёт по собранным листингам — шорт-лист по drive_time + площади + цене/сотка.

Использование:
    python scripts/report.py [path/to/listings.db]
"""
from __future__ import annotations

import json
import sqlite3
import sys

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) AS c FROM listings").fetchone()["c"]
    with_coords = conn.execute("SELECT COUNT(*) AS c FROM listings WHERE lat IS NOT NULL").fetchone()["c"]
    in_25 = conn.execute("SELECT COUNT(*) AS c FROM listings WHERE est_drive_min<=25").fetchone()["c"]
    in_20 = conn.execute("SELECT COUNT(*) AS c FROM listings WHERE est_drive_min<=20").fetchone()["c"]

    print(f"=== SUMMARY ===")
    print(f"Total in DB: {total}")
    print(f"With coords: {with_coords}")
    print(f"Within 25 min: {in_25}")
    print(f"Within 20 min: {in_20}\n")

    print(f"=== TOP-15 by drive time (area 6-14 сот) ===\n")
    for r in conn.execute(
        """SELECT * FROM listings
           WHERE est_drive_min IS NOT NULL AND est_drive_min<=25
             AND area_sotka BETWEEN 6 AND 14
           ORDER BY est_drive_min ASC LIMIT 15"""
    ):
        llm = json.loads(r["llm_extraction"] or "{}")
        summary = llm.get("short_summary", "")
        flags = llm.get("red_flags", []) or []
        flag_str = f" ⚠ {','.join(flags)}" if flags else ""
        print(f"  {r['est_drive_min']:5.1f}min | {r['area_sotka']:4.1f} сот | "
              f"{(r['price_rub'] or 0):>10,}₽ | {r['address'] or '-'}")
        if summary:
            print(f"          {summary}{flag_str}")
        print(f"          {r['url']}\n")


if __name__ == "__main__":
    main()
