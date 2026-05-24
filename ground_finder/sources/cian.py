from __future__ import annotations

from typing import Iterator
import cianparser


LOCATION = "Екатеринбург"


def fetch_land_plots(
    max_pages: int = 5,
    deal_type: str = "sale",
) -> Iterator[dict]:
    parser = cianparser.CianParser(location=LOCATION)
    rows = parser.get_suburban(
        deal_type=deal_type,
        suburban_type="land-plot",
        with_extra_data=False,
        additional_settings={
            "start_page": 1,
            "end_page": max_pages,
        },
    )
    for row in rows:
        yield _normalize(row)


def _normalize(row: dict) -> dict:
    return {
        "source": "cian",
        "external_id": str(row.get("id") or row.get("link") or ""),
        "url": row.get("link") or row.get("url"),
        "title": row.get("title"),
        "price_rub": _parse_int(row.get("price") or row.get("total_price")),
        "area_sotka": _parse_float(row.get("land_area") or row.get("land_plot")),
        "vri": row.get("land_plot_status") or row.get("land_status"),
        "address": row.get("address") or row.get("location"),
        "raw": row,
    }


def _parse_int(value) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _parse_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    cleaned = str(value).replace(",", ".")
    digits = "".join(ch for ch in cleaned if ch.isdigit() or ch == ".")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None
