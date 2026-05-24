from __future__ import annotations

from typing import Iterator


def fetch_land_plots(max_pages: int = 5) -> Iterator[dict]:
    raise NotImplementedError(
        "Avito source not wired yet. Will plug into user's existing parser "
        "on RU server (see project_infrastructure memory)."
    )
