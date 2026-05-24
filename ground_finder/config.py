from dataclasses import dataclass

@dataclass(frozen=True)
class SearchCriteria:
    anchor_lat: float = 56.8243
    anchor_lon: float = 60.6306
    anchor_label: str = "ул. Восточная 7г, Екатеринбург"
    max_drive_minutes: int = 20
    avg_drive_kmh: float = 50.0
    road_factor: float = 1.35
    area_min_m2: int = 800
    area_max_m2: int = 1200
    allowed_vri: tuple[str, ...] = ("ИЖС", "ЛПХ")
    price_max_rub: int | None = None

    @property
    def max_road_km(self) -> float:
        return self.avg_drive_kmh * (self.max_drive_minutes / 60)

    @property
    def max_straight_km(self) -> float:
        return self.max_road_km / self.road_factor


DEFAULT = SearchCriteria()
