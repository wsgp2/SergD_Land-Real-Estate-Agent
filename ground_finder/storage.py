from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

DEFAULT_DB = Path("data/listings.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT,
    title TEXT,
    price_rub INTEGER,
    area_sotka REAL,
    vri TEXT,
    address TEXT,
    cadastral_number TEXT,
    lat REAL,
    lon REAL,
    est_drive_min REAL,
    raw_json TEXT,
    first_seen_ts TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen_ts TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_cadastral ON listings(cadastral_number);
CREATE INDEX IF NOT EXISTS idx_area_drive ON listings(area_sotka, est_drive_min);
"""


def connect(db_path: Path = DEFAULT_DB) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def upsert(conn: sqlite3.Connection, rows: Iterable[dict]) -> int:
    count = 0
    for row in rows:
        conn.execute(
            """
            INSERT INTO listings (source, external_id, url, title, price_rub,
                                  area_sotka, vri, address, cadastral_number,
                                  lat, lon, est_drive_min, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source, external_id) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                price_rub = excluded.price_rub,
                area_sotka = excluded.area_sotka,
                vri = excluded.vri,
                address = excluded.address,
                cadastral_number = excluded.cadastral_number,
                lat = excluded.lat,
                lon = excluded.lon,
                est_drive_min = excluded.est_drive_min,
                raw_json = excluded.raw_json,
                last_seen_ts = CURRENT_TIMESTAMP
            """,
            (
                row["source"],
                row["external_id"],
                row.get("url"),
                row.get("title"),
                row.get("price_rub"),
                row.get("area_sotka"),
                row.get("vri"),
                row.get("address"),
                row.get("cadastral_number"),
                row.get("lat"),
                row.get("lon"),
                row.get("est_drive_min"),
                json.dumps(row.get("raw"), ensure_ascii=False, default=str),
            ),
        )
        count += 1
    conn.commit()
    return count
