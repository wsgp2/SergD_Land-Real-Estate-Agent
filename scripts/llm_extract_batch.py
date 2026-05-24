"""Stage 3+5 — прогон Claude Sonnet 4.6 (tool_use + prompt caching) по всем листингам.

Извлекает 22 структурированных поля из текста объявления:
  - кадастровый номер (даже из «грязной» формы записи),
  - нормализованный адрес для геокодинга,
  - площадь, ВРИ, цена,
  - коммуникации (газ, электр, вода, канализация),
  - постройки (дом, баня),
  - инфраструктура (лес, водоём, круглогодичный подъезд),
  - финансовые (ипотека, торг, рассрочка, тип продавца),
  - red_flags (доли, ЛЭП, обременения),
  - short_summary (1 строка для шорт-листа).

Использование:
    HTTPS_PROXY=socks5h://127.0.0.1:1080 \\
    ANTHROPIC_API_KEY=sk-ant-... \\
    python scripts/llm_extract_batch.py [path/to/listings.db]
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from ground_finder.llm.extract_listing import extract

DB = sys.argv[1] if len(sys.argv) > 1 else "data/listings.db"
WORKERS = 5


def main() -> None:
    conn = sqlite3.connect(DB)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "llm_extraction" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN llm_extraction TEXT")
        conn.commit()
        print("Added llm_extraction column")

    rows = conn.execute(
        "SELECT source, external_id, raw_json FROM listings "
        "WHERE llm_extraction IS NULL ORDER BY rowid"
    ).fetchall()
    print(f"To process: {len(rows)} listings")
    conn.close()

    stats = {"ok": 0, "fail": 0, "cache_read": 0, "cache_write": 0,
             "input": 0, "output": 0, "new_cadastrals": 0}
    t0 = time.time()
    writer = sqlite3.connect(DB)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_work, r): r for r in rows}
        done = 0
        for fut in as_completed(futures):
            source, external_id, result, err = fut.result()
            done += 1
            if err or result is None:
                stats["fail"] += 1
                continue
            stats["ok"] += 1
            stats["cache_read"] += result.cache_read_tokens
            stats["cache_write"] += result.cache_write_tokens
            stats["input"] += result.input_tokens
            stats["output"] += result.output_tokens
            cad = (result.data or {}).get("cadastral_number")
            prev_cad = writer.execute(
                "SELECT cadastral_number FROM listings WHERE source=? AND external_id=?",
                (source, external_id),
            ).fetchone()
            if cad and (not prev_cad or not prev_cad[0]):
                stats["new_cadastrals"] += 1
                writer.execute(
                    "UPDATE listings SET llm_extraction=?, cadastral_number=? "
                    "WHERE source=? AND external_id=?",
                    (json.dumps(result.data, ensure_ascii=False), cad, source, external_id),
                )
            else:
                writer.execute(
                    "UPDATE listings SET llm_extraction=? "
                    "WHERE source=? AND external_id=?",
                    (json.dumps(result.data, ensure_ascii=False), source, external_id),
                )
            if done % 25 == 0:
                writer.commit()
                rate = done / (time.time() - t0)
                print(f"  [{done}/{len(rows)}] ok={stats['ok']} fail={stats['fail']} "
                      f"new_cads={stats['new_cadastrals']} | {rate:.1f}/s | "
                      f"cache_r={stats['cache_read']:,} cache_w={stats['cache_write']:,} "
                      f"in={stats['input']:,} out={stats['output']:,}")
    writer.commit()
    writer.close()

    elapsed = time.time() - t0
    cost = (stats["cache_write"] * 3.0 * 1.25 / 1_000_000 +
            stats["cache_read"] * 3.0 * 0.1 / 1_000_000 +
            stats["input"] * 3.0 / 1_000_000 +
            stats["output"] * 15.0 / 1_000_000)
    print(f"\n=== DONE in {elapsed:.0f}s ===")
    print(f"  ok: {stats['ok']}, fail: {stats['fail']}")
    print(f"  new cadastrals extracted: {stats['new_cadastrals']}")
    print(f"  estimated cost: ${cost:.3f}")


def _work(row):
    source, external_id, raw_json = row
    raw = json.loads(raw_json or "{}")
    text = (raw.get("raw", {}).get("text")
            or raw.get("text") or raw.get("title") or "")
    if not text:
        return source, external_id, None, "no text"
    try:
        return source, external_id, extract(text), None
    except Exception as e:  # noqa: BLE001
        return source, external_id, None, f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    main()
