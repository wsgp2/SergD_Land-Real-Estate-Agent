"""Финальный отчёт + интерактивная HTML-карта + JSON шорт-лист.

Три группы кандидатов:
  A. С точными координатами (Rosreestr или Nominatim) и в drive_window
  B. Без координат, но LLM city='Екатеринбург' (внутри ГО ≈ ≤25 мин)
  C. Пригороды (Берёзовский, Арамиль, Сысерть, Верхняя Пышма и др.)

Использование:
    python scripts/report.py [path/to/listings.db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from ground_finder.config import DEFAULT

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"
ANCHOR_CITY = "Екатеринбург"


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    _print_summary(conn)
    group_a = _query_group_a(conn)
    group_b = _query_group_b(conn)
    group_c = _query_group_c(conn)

    print(f"=== A — с точным drive_time, ≤25 мин, 6-14 сот, без red_flags: {len(group_a)} ===\n")
    for r in group_a:
        print(_fmt_row(r, show_drive=True))

    print(f"\n=== B — внутри Екб без координат, 6-14 сот, без red_flags: {len(group_b)} ===")
    print("(почти гарантированно внутри 25 мин, точное время неизвестно)\n")
    for r in group_b[:30]:
        print(_fmt_row(r, show_drive=False))
    if len(group_b) > 30:
        print(f"  ... и ещё {len(group_b) - 30} (все в data/shortlist.json)\n")

    print(f"\n=== C — пригороды, 6-14 сот, без red_flags: {len(group_c)} ===\n")
    for r in group_c[:15]:
        print(_fmt_row(r, show_drive=False, show_city=True))

    # Сохраняем всё
    payload = {
        "a_with_coords": [_to_dict(r) for r in group_a],
        "b_inside_city_no_coords": [_to_dict(r) for r in group_b],
        "c_suburbs": [_to_dict(r) for r in group_c],
    }
    out_json = Path("data/shortlist.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    print(f"\n💾 Full shortlist (A:{len(group_a)} + B:{len(group_b)} + C:{len(group_c)}) → {out_json}")

    out_html = Path("data/map.html")
    out_html.write_text(_render_map(group_a))
    print(f"🗺  Interactive map (group A only, координаты есть) → {out_html}")


def _print_summary(conn: sqlite3.Connection) -> None:
    total = conn.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"]
    with_llm = conn.execute("SELECT COUNT(*) c FROM listings WHERE llm_extraction IS NOT NULL").fetchone()["c"]
    with_coords = conn.execute("SELECT COUNT(*) c FROM listings WHERE lat IS NOT NULL").fetchone()["c"]
    flagged = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE "
        "json_array_length(json_extract(llm_extraction, '$.red_flags')) > 0"
    ).fetchone()["c"]
    izhs = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE json_extract(llm_extraction, '$.vri')='ИЖС'"
    ).fetchone()["c"]
    print("=== SUMMARY ===")
    print(f"Всего в БД:             {total}")
    print(f"С LLM-извлечением:      {with_llm}")
    print(f"С координатами:         {with_coords}")
    print(f"С red_flags:            {flagged}")
    print(f"ИЖС (по LLM):           {izhs}")
    print()


def _query_group_a(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT * FROM listings
           WHERE est_drive_min IS NOT NULL AND est_drive_min<=25
             AND area_sotka BETWEEN 6 AND 14
             AND (json_array_length(json_extract(llm_extraction, '$.red_flags'))=0
                  OR json_extract(llm_extraction, '$.red_flags') IS NULL)
           ORDER BY est_drive_min ASC"""
    ))


def _query_group_b(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT * FROM listings
           WHERE lat IS NULL
             AND json_extract(llm_extraction, '$.city')=?
             AND area_sotka BETWEEN 6 AND 14
             AND (json_array_length(json_extract(llm_extraction, '$.red_flags'))=0
                  OR json_extract(llm_extraction, '$.red_flags') IS NULL)
           ORDER BY price_rub ASC""",
        (ANCHOR_CITY,),
    ))


def _query_group_c(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(conn.execute(
        """SELECT * FROM listings
           WHERE lat IS NULL
             AND json_extract(llm_extraction, '$.city') != ?
             AND json_extract(llm_extraction, '$.city') IS NOT NULL
             AND area_sotka BETWEEN 6 AND 14
             AND (json_array_length(json_extract(llm_extraction, '$.red_flags'))=0
                  OR json_extract(llm_extraction, '$.red_flags') IS NULL)
           ORDER BY price_rub ASC""",
        (ANCHOR_CITY,),
    ))


def _to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    if d.get("llm_extraction"):
        try:
            d["llm_extraction"] = json.loads(d["llm_extraction"])
        except Exception:
            pass
    if d.get("raw_json"):
        d.pop("raw_json", None)
    return d


def _fmt_row(r: sqlite3.Row, *, show_drive: bool = True, show_city: bool = False) -> str:
    llm = json.loads(r["llm_extraction"] or "{}")
    flags = llm.get("red_flags") or []
    flag_str = f" ⚠ {'; '.join(flags)}" if flags else ""
    utils = []
    if llm.get("has_gas"): utils.append("газ")
    if llm.get("has_electricity"): utils.append("свет")
    if llm.get("has_water"): utils.append("вода")
    if llm.get("has_house"): utils.append("дом")
    if llm.get("has_banya"): utils.append("баня")
    utils_str = ", ".join(utils) if utils else "—"
    drive = f"{r['est_drive_min']:5.1f}min" if show_drive and r["est_drive_min"] else "  ?  "
    addr = llm.get("full_address") or r["address"] or ""
    city_prefix = f"  📍 {llm.get('city')}\n" if show_city else ""
    return (
        city_prefix +
        f"  {drive} | {(r['area_sotka'] or 0):5.1f} сот | "
        f"💰 {(r['price_rub'] or 0):>10,}₽ | 🏷 {(llm.get('vri') or '?'):>5} | 🔌 {utils_str}\n"
        f"          {llm.get('short_summary', '')}{flag_str}\n"
        f"          📍 {addr}\n"
        f"          🔗 {r['url']}\n"
    )


def _render_map(rows) -> str:
    points = []
    for r in rows:
        if r["lat"] is None:
            continue
        llm = json.loads(r["llm_extraction"] or "{}")
        points.append({
            "lat": r["lat"], "lon": r["lon"],
            "price": r["price_rub"], "area": r["area_sotka"],
            "drive": r["est_drive_min"], "vri": llm.get("vri"),
            "url": r["url"],
            "summary": (llm.get("short_summary") or "").replace("'", "\\'"),
            "addr": (llm.get("full_address") or "").replace("'", "\\'"),
        })

    return f"""<!DOCTYPE html>
<html><head>
<meta charset="utf-8"/><title>Ground-finder shortlist</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>html,body,#map{{height:100%;margin:0}}</style>
</head><body><div id="map"></div>
<script>
const points = {json.dumps(points, ensure_ascii=False)};
const anchor = [{DEFAULT.anchor_lat}, {DEFAULT.anchor_lon}];
const map = L.map('map').setView(anchor, 11);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
    maxZoom: 19, attribution: '© OpenStreetMap'
}}).addTo(map);
L.marker(anchor).addTo(map).bindPopup('<b>Анкор:</b> {DEFAULT.anchor_label}');
L.circle(anchor, {{radius: {int(DEFAULT.max_road_km * 1000)}, color:'#888', fillOpacity:0.05}})
  .addTo(map).bindPopup('Радиус {DEFAULT.max_drive_minutes} мин ({DEFAULT.max_road_km:.1f} км)');
points.forEach(p => {{
    const color = p.vri === 'ИЖС' ? 'green' : (p.vri === 'ЛПХ' ? 'orange' : 'blue');
    const m = L.circleMarker([p.lat, p.lon], {{radius: 8, color, fillOpacity: 0.7}}).addTo(map);
    m.bindPopup(`<b>${{p.area}} сот ${{p.vri || ''}}</b><br>
        💰 ${{p.price ? p.price.toLocaleString('ru') + '₽' : '—'}}<br>
        ⏱ ${{p.drive.toFixed(0)}} мин<br>
        ${{p.summary || ''}}<br>
        📍 ${{p.addr || ''}}<br>
        <a href="${{p.url}}" target="_blank">Открыть на ЦИАН →</a>`);
}});
</script></body></html>"""


if __name__ == "__main__":
    main()
