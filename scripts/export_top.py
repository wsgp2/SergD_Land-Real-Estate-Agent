"""Экспорт топ-кандидатов в Telegram-форматах (HTML + Unicode-bold plain text).

Использование:
    python scripts/export_top.py [--drive 10] [--area-min 6] [--area-max 14] [--db PATH]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from html import escape as html_escape
from pathlib import Path


COMMERCIAL_MARKERS = ("коммерч", "трц", "торгово", "офис", "склад", "многоэтаж",
                       "мкд", "под бизнес", "под застройку мн", "под жилой комплекс")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drive", type=int, default=15, help="Max drive_time minutes")
    ap.add_argument("--area-min", type=float, default=6)
    ap.add_argument("--area-max", type=float, default=14)
    ap.add_argument("--max-price", type=int, default=50_000_000,
                    help="Max price RUB (default: 50M — отсекаем явно коммерческие)")
    ap.add_argument("--db", default="data/listings.db")
    ap.add_argument("--out-dir", default="data")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    raw_rows = list(conn.execute(
        """SELECT *,
                  json_extract(llm_extraction, '$.vri') vri,
                  json_extract(llm_extraction, '$.short_summary') summary,
                  json_extract(llm_extraction, '$.full_address') addr,
                  json_extract(llm_extraction, '$.has_gas') has_gas,
                  json_extract(llm_extraction, '$.has_electricity') has_elec,
                  json_extract(llm_extraction, '$.has_water') has_water,
                  json_extract(llm_extraction, '$.has_house') has_house,
                  json_extract(llm_extraction, '$.has_banya') has_banya,
                  json_extract(llm_extraction, '$.seller_type') seller
           FROM listings
           WHERE est_drive_min IS NOT NULL AND est_drive_min <= ?
             AND area_sotka BETWEEN ? AND ?
             AND (price_rub IS NULL OR price_rub <= ?)
             AND (json_array_length(json_extract(llm_extraction, '$.red_flags')) = 0
                  OR json_extract(llm_extraction, '$.red_flags') IS NULL)
             AND llm_extraction IS NOT NULL
             AND COALESCE(json_extract(llm_extraction, '$.vri'), '') != 'коммерческое'
           ORDER BY est_drive_min ASC, price_rub ASC""",
        (args.drive, args.area_min, args.area_max, args.max_price),
    ))

    # Дополнительная фильтрация по тексту summary — Sonnet иногда ставит vri=ИЖС,
    # хотя описание явно коммерческое (под ТРЦ, многоэтажку и т.п.).
    rows = []
    skipped_commercial = 0
    for r in raw_rows:
        summary = (r["summary"] or "").lower()
        if any(m in summary for m in COMMERCIAL_MARKERS):
            skipped_commercial += 1
            continue
        rows.append(r)
    if skipped_commercial:
        print(f"Skipped {skipped_commercial} commercial-looking listings (по тексту summary)")

    print(f"Top within {args.drive} min, {args.area_min}-{args.area_max} sot: {len(rows)} listings")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"top_{args.drive}min.html"
    txt_path = out_dir / f"top_{args.drive}min.txt"
    html_path.write_text(_render_html(rows, args.drive))
    txt_path.write_text(_render_plain(rows, args.drive))
    print(f"Saved: {html_path}  ({html_path.stat().st_size} bytes)")
    print(f"Saved: {txt_path}   ({txt_path.stat().st_size} bytes)")


# ---------- HTML (для Telegram parse_mode=HTML или копипаста в desktop)

def _render_html(rows: list, drive_max: int) -> str:
    parts = [f"<b>🏡 Топ участков в {drive_max} минутах от ул. Восточная</b>\n"
             f"<i>Площадь 6–14 сот · без red flags · сорт. по времени езды</i>\n\n"]
    for i, r in enumerate(rows, 1):
        parts.append(_one_html(i, r))
    parts.append(f"\n<i>Всего {len(rows)} кандидатов. Полный список — на GitHub: "
                 f"<a href=\"https://github.com/wsgp2/SergD_Land-Real-Estate-Agent\">SergD/Land-Real-Estate-Agent</a></i>")
    return "".join(parts)


def _one_html(i: int, r) -> str:
    utils = _utils_list(r)
    price = _fmt_price(r["price_rub"])
    title = f"#{i} · {r['est_drive_min']:.0f} мин · {r['area_sotka']:.1f} сот · {price}"
    seller = r["seller"] or ""
    seller_str = {"owner": " · собственник", "agent": " · агент", "developer": " · застройщик"}.get(seller, "")
    summary = html_escape(r["summary"] or "")
    addr = html_escape(r["addr"] or "")
    vri = html_escape(r["vri"] or "—")
    url = r["url"] or ""
    url_safe = url.replace("&", "&amp;")
    return (
        f"<b>{html_escape(title)}</b>\n"
        f"🏷 {vri}{seller_str} · 🔌 {html_escape(utils)}\n"
        f"📍 {addr}\n"
        f"📝 {summary}\n"
        f"<a href=\"{url_safe}\">→ открыть на ЦИАН</a>\n\n"
    )


# ---------- Plain (Unicode-bold для прямого копипаста в любой Telegram)

# Unicode bold sans-serif маппинг для латиницы и цифр
def _bold(text: str) -> str:
    out = []
    for ch in text:
        cp = ord(ch)
        if 0x30 <= cp <= 0x39:  # 0-9 → 𝟬-𝟵
            out.append(chr(0x1D7EC + cp - 0x30))
        elif 0x41 <= cp <= 0x5A:  # A-Z → 𝗔-𝗭
            out.append(chr(0x1D5D4 + cp - 0x41))
        elif 0x61 <= cp <= 0x7A:  # a-z → 𝗮-𝘇
            out.append(chr(0x1D5EE + cp - 0x61))
        else:
            out.append(ch)
    return "".join(out)


def _render_plain(rows: list, drive_max: int) -> str:
    parts = [
        f"🏡 ТОП УЧАСТКОВ В {drive_max} МИН ОТ УЛ. ВОСТОЧНАЯ\n",
        f"Площадь 6-14 сот, без red flags, сорт. по времени езды\n",
        f"{'─' * 50}\n\n",
    ]
    for i, r in enumerate(rows, 1):
        parts.append(_one_plain(i, r))
    parts.append(f"\n{'─' * 50}\n")
    parts.append(f"Всего {len(rows)} кандидатов\n")
    parts.append(f"Полный список + код: github.com/wsgp2/SergD_Land-Real-Estate-Agent\n")
    return "".join(parts)


def _one_plain(i: int, r) -> str:
    utils = _utils_list(r)
    price = _fmt_price(r["price_rub"])
    drive = f"{r['est_drive_min']:.0f} мин"
    area = f"{r['area_sotka']:.1f} сот"
    # Unicode bold для номера/времени/цены/площади
    head = f"#{i} · {_bold(drive)} · {_bold(area)} · {_bold(price)}"
    seller = r["seller"] or ""
    seller_str = {"owner": " · собственник", "agent": " · агент", "developer": " · застройщик"}.get(seller, "")
    return (
        f"{head}\n"
        f"🏷 {r['vri'] or '—'}{seller_str} · 🔌 {utils}\n"
        f"📍 {r['addr'] or '—'}\n"
        f"📝 {r['summary'] or '—'}\n"
        f"{r['url']}\n\n"
    )


# ---------- helpers

def _utils_list(r) -> str:
    parts = []
    if r["has_gas"]: parts.append("газ")
    if r["has_elec"]: parts.append("свет")
    if r["has_water"]: parts.append("вода")
    if r["has_house"]: parts.append("дом")
    if r["has_banya"]: parts.append("баня")
    return ", ".join(parts) if parts else "—"


def _fmt_price(p) -> str:
    if not p:
        return "—"
    if p >= 1_000_000:
        v = p / 1_000_000
        s = f"{v:.2f}".rstrip("0").rstrip(".")
        return f"{s}М₽"
    return f"{int(p):,}₽".replace(",", " ")


if __name__ == "__main__":
    main()
