from __future__ import annotations

from typing import Iterable

from ground_finder.config import SearchCriteria
from ground_finder.enrichment.geo import within_drive_window
from ground_finder.enrichment.rosreestr import extract_cadastral_number, lookup


def enrich(row: dict, criteria: SearchCriteria) -> dict:
    text_fields = " ".join(
        str(row.get(k) or "")
        for k in ("title", "address", "url")
    ) + " " + str(row.get("raw") or "")
    cad = extract_cadastral_number(text_fields)

    lat = lon = drive_min = None
    real_area_m2 = None
    if cad:
        info = lookup(cad)
        if info:
            lat, lon = info.lat, info.lon
            real_area_m2 = info.area_m2
            row["cadastral_number"] = info.cadastral_number
            if info.address:
                row["address"] = info.address
            if info.permitted_use:
                row["permitted_use"] = info.permitted_use
                if not row.get("vri") and ("ИЖС" in info.permitted_use.upper() or "индивидуальн" in info.permitted_use.lower()):
                    row["vri"] = "ИЖС"
                elif not row.get("vri") and "ЛПХ" in info.permitted_use.upper():
                    row["vri"] = "ЛПХ"
                elif not row.get("vri") and "садовод" in info.permitted_use.lower():
                    row["vri"] = "СНТ/ДНП"
            if info.category:
                row["land_category"] = info.category
            if info.cadastral_cost_rub:
                row["cadastral_cost_rub"] = info.cadastral_cost_rub

    in_window, drive_min = within_drive_window(lat, lon, criteria)
    row["lat"] = lat
    row["lon"] = lon
    row["est_drive_min"] = drive_min
    row["_in_drive_window"] = in_window
    if real_area_m2 is not None:
        row["_area_m2_from_rosreestr"] = real_area_m2
    return row


def apply_filters(rows: Iterable[dict], criteria: SearchCriteria) -> list[dict]:
    keep = []
    for row in rows:
        area = _area_to_m2(row.get("area_sotka")) or row.get("_area_m2_from_rosreestr")
        if area is not None:
            if not (criteria.area_min_m2 <= area <= criteria.area_max_m2):
                continue
        if criteria.price_max_rub and row.get("price_rub"):
            if row["price_rub"] > criteria.price_max_rub:
                continue
        if row.get("lat") is not None and not row.get("_in_drive_window"):
            continue
        keep.append(row)
    return keep


def _area_to_m2(sotka: float | None) -> float | None:
    if sotka is None:
        return None
    return sotka * 100.0
