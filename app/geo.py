from __future__ import annotations

import math
from typing import Sequence

# Metres per degree at NCR latitudes. Longitude is the short axis (cos 28.6 deg),
# so use it whenever a bound has to be conservative.
M_PER_DEG_LAT = 110900.0
M_PER_DEG_LON = 97600.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def point_on_segment(
    lat1: float, lon1: float, lat2: float, lon2: float, t: float
) -> tuple[float, float]:
    return lat1 + (lat2 - lat1) * t, lon1 + (lon2 - lon1) * t


def _origin_to_segment(ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    d2 = dx * dx + dy * dy
    if d2 == 0.0:
        return math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / d2))
    return math.hypot(ax + t * dx, ay + t * dy)


def min_dist_to_path_m(lat: float, lon: float, path: Sequence[Sequence[float]]) -> float:
    """Exact distance from a point to a polyline, flat-earth around the point."""
    kx = 111320.0 * math.cos(math.radians(lat))
    ky = 110540.0
    best = float("inf")
    prev: tuple[float, float] | None = None
    for plat, plon in path:
        x = (plon - lon) * kx
        y = (plat - lat) * ky
        best = min(best, math.hypot(x, y) if prev is None else _origin_to_segment(prev[0], prev[1], x, y))
        prev = (x, y)
    return best


def densify(path: Sequence[Sequence[float]], step_m: float) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = [(path[0][0], path[0][1])]
    for (alat, alon), (blat, blon) in zip(path, path[1:]):
        gap = haversine_m(alat, alon, blat, blon)
        for i in range(1, int(gap // step_m) + 1):
            out.append(point_on_segment(alat, alon, blat, blon, i * step_m / gap))
        out.append((blat, blon))
    return out


class GridIndex:
    """Uniform lat/lon buckets. NCR spans under a degree, so no projection needed."""

    def __init__(self, cell_deg: float = 0.005) -> None:
        self.cell = cell_deg
        self.buckets: dict[tuple[int, int], list] = {}

    def add(self, lat: float, lon: float, payload) -> None:
        self.buckets.setdefault((int(lat / self.cell), int(lon / self.cell)), []).append(payload)

    def near(self, lat: float, lon: float, radius_m: float) -> set:
        span = int(radius_m / (self.cell * M_PER_DEG_LON)) + 1
        ci, cj = int(lat / self.cell), int(lon / self.cell)
        out: set = set()
        for i in range(ci - span, ci + span + 1):
            for j in range(cj - span, cj + span + 1):
                bucket = self.buckets.get((i, j))
                if bucket:
                    out.update(bucket)
        return out

    def nearest(self, lat: float, lon: float, start_m: float = 700.0, limit_m: float = 80000.0):
        radius = start_m
        while radius <= limit_m:
            best = min(
                (
                    (haversine_m(lat, lon, plat, plon), pid)
                    for pid, plat, plon in self.near(lat, lon, radius)
                ),
                default=None,
            )
            if best is not None and best[0] <= radius:
                return best[1], best[0]
            radius *= 2
        return None, float("inf")
