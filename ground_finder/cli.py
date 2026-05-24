from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from ground_finder.config import DEFAULT, SearchCriteria
from ground_finder.pipeline import apply_filters, enrich
from ground_finder.sources import cian, cian_cloak
from ground_finder.storage import connect, upsert

app = typer.Typer(help="Ground-finder: aggregator of land plots near Yekaterinburg")
console = Console()


@app.command()
def fetch(
    pages: int = typer.Option(3, help="Pages to pull from CIAN"),
    drive: int = typer.Option(DEFAULT.max_drive_minutes, help="Max drive minutes from anchor"),
    area_min: int = typer.Option(DEFAULT.area_min_m2, help="Min area in m²"),
    area_max: int = typer.Option(DEFAULT.area_max_m2, help="Max area in m²"),
    price_max: int = typer.Option(0, help="Max price in RUB (0 = no limit)"),
    db: Path = typer.Option(Path("data/listings.db"), help="SQLite DB path"),
    skip_rosreestr: bool = typer.Option(
        False, help="Skip Rosreestr enrichment (faster, but no coords)"
    ),
    use_legacy_cian: bool = typer.Option(
        False, "--legacy-cian", help="Use old cianparser (broken; default uses CloakBrowser)"
    ),
):
    criteria = SearchCriteria(
        max_drive_minutes=drive,
        area_min_m2=area_min,
        area_max_m2=area_max,
        price_max_rub=price_max or None,
    )
    console.print(f"[bold cyan]Fetching CIAN[/] pages=1..{pages}, anchor={criteria.anchor_label}")
    source = cian if use_legacy_cian else cian_cloak
    raw = list(source.fetch_land_plots(max_pages=pages))
    console.print(f"  → got [bold]{len(raw)}[/] raw listings")

    if skip_rosreestr:
        enriched = raw
    else:
        console.print("[bold cyan]Enriching with Rosreestr[/] (parallel, 8 workers)…")
        enriched = _enrich_parallel(raw, criteria, workers=8)

    matched = apply_filters(enriched, criteria)
    console.print(f"[bold green]Matched filters:[/] {len(matched)} / {len(enriched)}")

    with connect(db) as conn:
        upsert(conn, enriched)
    console.print(f"[dim]Saved all {len(enriched)} listings to {db}[/]")

    _show(matched[:20])


@app.command()
def show(
    db: Path = typer.Option(Path("data/listings.db")),
    drive: int = typer.Option(DEFAULT.max_drive_minutes),
    area_min: int = typer.Option(DEFAULT.area_min_m2),
    area_max: int = typer.Option(DEFAULT.area_max_m2),
):
    with connect(db) as conn:
        cur = conn.execute(
            """
            SELECT title, address, price_rub, area_sotka, est_drive_min, url
            FROM listings
            WHERE (area_sotka * 100) BETWEEN ? AND ?
              AND (est_drive_min IS NULL OR est_drive_min <= ?)
            ORDER BY est_drive_min IS NULL, est_drive_min ASC, price_rub ASC
            LIMIT 30
            """,
            (area_min, area_max, drive),
        )
        rows = [dict(zip([c[0] for c in cur.description], r)) for r in cur.fetchall()]
    _show(rows)


def _enrich_parallel(rows: list[dict], criteria: SearchCriteria, workers: int = 8) -> list[dict]:
    out: list[dict] = []
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Rosreestr", total=len(rows))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = {ex.submit(enrich, r, criteria): r for r in rows}
            for fut in as_completed(futures):
                try:
                    out.append(fut.result())
                except Exception as exc:
                    base = futures[fut]
                    base["_enrich_error"] = str(exc)
                    out.append(base)
                progress.advance(task)
    return out


def _show(rows: list[dict]) -> None:
    if not rows:
        console.print("[yellow]Nothing to show[/]")
        return
    table = Table(show_lines=False, header_style="bold magenta")
    for col in ("title", "address", "price_rub", "area_sotka", "est_drive_min"):
        table.add_column(col)
    for row in rows:
        table.add_row(
            (row.get("title") or "")[:40],
            (row.get("address") or "")[:50],
            _fmt_price(row.get("price_rub")),
            _fmt(row.get("area_sotka"), "{:.1f}"),
            _fmt(row.get("est_drive_min"), "{:.0f} мин"),
        )
    console.print(table)


def _fmt_price(v) -> str:
    if v is None:
        return "—"
    return f"{int(v):,}".replace(",", " ") + " ₽"


def _fmt(v, fmt: str) -> str:
    return fmt.format(v) if v is not None else "—"


if __name__ == "__main__":
    app()
