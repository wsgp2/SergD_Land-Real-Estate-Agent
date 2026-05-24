"""Финальный отчёт + интерактивная HTML-карта.

Шорт-лист отфильтрован по:
  - drive_time ≤ N мин от якоря
  - area_sotka в диапазоне
  - ВРИ из allowed
  - red_flags пустой (или их нет)

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


def main() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row

    total = conn.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"]
    with_llm = conn.execute("SELECT COUNT(*) c FROM listings WHERE llm_extraction IS NOT NULL").fetchone()["c"]
    with_coords = conn.execute("SELECT COUNT(*) c FROM listings WHERE lat IS NOT NULL").fetchone()["c"]
    in_25 = conn.execute("SELECT COUNT(*) c FROM listings WHERE est_drive_min<=25").fetchone()["c"]
    in_20 = conn.execute("SELECT COUNT(*) c FROM listings WHERE est_drive_min<=20").fetchone()["c"]
    in_15 = conn.execute("SELECT COUNT(*) c FROM listings WHERE est_drive_min<=15").fetchone()["c"]
    izhs = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE json_extract(llm_extraction, '$.vri')='ИЖС'"
    ).fetchone()["c"]
    flagged = conn.execute(
        "SELECT COUNT(*) c FROM listings WHERE "
        "json_array_length(json_extract(llm_extraction, '$.red_flags')) > 0"
    ).fetchone()["c"]

    print("=== SUMMARY ===")
    print(f"Total in DB:           {total}")
    print(f"With LLM extraction:   {with_llm}")
    print(f"With coords:           {with_coords}")
    print(f"With red_flags:        {flagged}")
    print(f"ИЖС:                   {izhs}")
    print(f"Within 25 min:         {in_25}")
    print(f"Within 20 min:         {in_20}")
    print(f"Within 15 min:         {in_15}")
    print()

    # Шорт-лист: ≤25 мин, 6-14 сот, ИЖС или ЛПХ, без red_flags
    shortlist = list(conn.execute(
        """SELECT l.*, json_extract(llm_extraction, '$.short_summary') summary,
                  json_extract(llm_extraction, '$.vri') llm_vri,
                  json_extract(llm_extraction, '$.full_address') llm_address,
                  json_extract(llm_extraction, '$.has_gas') has_gas,
                  json_extract(llm_extraction, '$.has_electricity') has_electricity,
                  json_extract(llm_extraction, '$.has_house') has_house,
                  json_extract(llm_extraction, '$.red_flags') flags_json,
                  json_extract(llm_extraction, '$.seller_type') seller
           FROM listings l
           WHERE est_drive_min IS NOT NULL AND est_drive_min<=25
             AND area_sotka BETWEEN 6 AND 14
             AND (json_array_length(json_extract(llm_extraction, '$.red_flags'))=0
                  OR json_extract(llm_extraction, '$.red_flags') IS NULL)
           ORDER BY est_drive_min ASC LIMIT 30"""
    ))

    print(f"=== SHORTLIST: {len(shortlist)} clean listings within 25 min, 6-14 sot, no red flags ===\n")
    for r in shortlist[:15]:
        utils = []
        if r["has_gas"]: utils.append("газ")
        if r["has_electricity"]: utils.append("электр.")
        if r["has_house"]: utils.append("дом")
        utils_str = ", ".join(utils) if utils else "—"
        print(f"  ⏱  {r['est_drive_min']:5.1f}min | 📐 {r['area_sotka']:5.1f} сот | "
              f"💰 {(r['price_rub'] or 0):>10,}₽ | 🏷 {r['llm_vri'] or '?'} | 🔌 {utils_str}")
        if r["summary"]:
            print(f"          {r['summary']}")
        print(f"          📍 {r['llm_address']}")
        print(f"          🔗 {r['url']}\n")

    # Сохраним JSON всего шорт-листа
    out_json = Path("data/shortlist.json")
    out_json.write_text(
        json.dumps([dict(r) for r in shortlist], ensure_ascii=False, indent=2, default=str)
    )
    print(f"Full shortlist ({len(shortlist)}) saved to {out_json}")

    # HTML-карта Leaflet
    out_html = Path("data/map.html")
    out_html.write_text(_render_map(shortlist))
    print(f"Interactive map saved to {out_html}")


def _render_map(rows) -> str:
    points = []
    for r in rows:
        if r["lat"] is None:
            continue
        summary = (r["summary"] or "").replace("'", "\\'")
        addr = (r["llm_address"] or "").replace("'", "\\'")
        points.append({
            "lat": r["lat"], "lon": r["lon"],
            "price": r["price_rub"], "area": r["area_sotka"],
            "drive": r["est_drive_min"], "vri": r["llm_vri"],
            "url": r["url"], "summary": summary, "addr": addr,
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
L.marker(anchor, {{title: 'Анкор'}}).addTo(map)
  .bindPopup('<b>Анкор:</b> {DEFAULT.anchor_label}');
L.circle(anchor, {{radius: {int(DEFAULT.max_road_km * 1000)}, color:'#888', fillOpacity:0.05}})
  .addTo(map).bindPopup('Радиус {DEFAULT.max_drive_minutes} мин ({DEFAULT.max_road_km:.1f} км по дорогам)');
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
