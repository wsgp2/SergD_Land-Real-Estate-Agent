from __future__ import annotations

import re
import time
from typing import Iterator

REGION_EKB = 4743
PAGE_URL = (
    "https://www.cian.ru/cat.php?engine_version=2&p={page}&with_neighbors=0"
    "&region={region}&deal_type=sale&offer_type=suburban&object_type%5B0%5D=3"
)

CADASTRAL_RE = re.compile(r"\b\d{2}:\d{2}:\d{6,7}:\d{1,6}\b")
SOTKA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*сот", re.IGNORECASE)


def fetch_land_plots(
    max_pages: int = 5,
    region: int = REGION_EKB,
    headless: bool = True,
    delay_s: float = 2.5,
) -> Iterator[dict]:
    from cloakbrowser import launch

    browser = launch(headless=headless)
    try:
        page = browser.new_page()
        for n in range(1, max_pages + 1):
            url = PAGE_URL.format(page=n, region=region)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as exc:
                print(f"  [cian] page {n}: navigation error {exc}")
                continue
            time.sleep(delay_s)

            cards = page.evaluate(_EXTRACT_JS)
            print(f"  [cian] page {n}: {len(cards)} cards")
            for raw in cards:
                yield _normalize(raw)
    finally:
        browser.close()


_EXTRACT_JS = r"""() => {
    const cards = document.querySelectorAll("article[data-name=CardComponent]");
    return Array.from(cards).map(c => {
        const title = c.querySelector("[data-mark=OfferTitle]")?.innerText || null;
        const price = c.querySelector("[data-mark=MainPrice]")?.innerText || null;
        const link = Array.from(c.querySelectorAll("a"))
            .map(a => a.href).find(h => h.includes("/sale/suburban/")) || null;
        return {
            title,
            price,
            link,
            text: c.innerText,
        };
    });
}"""


def _normalize(raw: dict) -> dict:
    text = raw.get("text") or ""
    cad_match = CADASTRAL_RE.search(text)
    sotka_match = SOTKA_RE.search(raw.get("title") or "") or SOTKA_RE.search(text)
    address = _extract_address(text)
    external_id = _extract_id(raw.get("link"))

    return {
        "source": "cian",
        "external_id": external_id or raw.get("link") or "",
        "url": raw.get("link"),
        "title": raw.get("title"),
        "price_rub": _parse_price(raw.get("price")),
        "area_sotka": float(sotka_match.group(1).replace(",", ".")) if sotka_match else None,
        "vri": _detect_vri(text),
        "address": address,
        "cadastral_number": cad_match.group(0) if cad_match else None,
        "raw": raw,
    }


def _extract_id(url: str | None) -> str | None:
    if not url:
        return None
    m = re.search(r"/sale/suburban/(\d+)/", url)
    return m.group(1) if m else None


def _parse_price(text: str | None) -> int | None:
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return int(digits) if digits else None


def _extract_address(text: str | None) -> str | None:
    if not text:
        return None
    for line in text.split("\n"):
        line = line.strip()
        if "область" in line or "Екатеринбург" in line:
            return line
    return None


def _detect_vri(text: str | None) -> str | None:
    if not text:
        return None
    upper = text.upper()
    if "ИЖС" in upper:
        return "ИЖС"
    if "ЛПХ" in upper:
        return "ЛПХ"
    if "СНТ" in upper or "ДНП" in upper or "СНП" in upper:
        return "СНТ/ДНП"
    if "С/Х" in upper or "СЕЛЬХОЗ" in upper:
        return "СХ"
    return None
