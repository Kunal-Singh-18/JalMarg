"""Moving test vehicles for Feature 1. Never writes to the live GPS store.

Each tick updates position, speed, heading, and road association, then
publishes through traffic.ingest_sim_fix (ids always start with sim-).
"""

from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass, field

from app.geo import haversine_m
from app.traffic import SIM, ingest_sim_fix, reset as traffic_reset, set_mode

DT_S = 1.0

# ~3 km around Rajiv Chowk: Inner/Outer Circle, radials, Mandi House, ITO fringe.
CP = (28.6315, 77.2167)
CP_RADIUS_M = 3200.0

SCENARIOS: dict[str, dict] = {
    "clear": {
        "n": 28,
        "speed": (24.0, 30.0),
        "stop_p": 0.0,
        "drop_p": 0.03,
        "noise_m": 6.0,
        "outliers": 0,
        "stopped": 0,
    },
    "moderate": {
        "n": 60,
        "speed": (12.0, 20.0),
        "stop_p": 0.06,
        "drop_p": 0.08,
        "noise_m": 12.0,
        "outliers": 0,
        "stopped": 3,
    },
    "heavy": {
        "n": 110,
        "speed": (3.0, 10.0),
        "stop_p": 0.22,
        "drop_p": 0.12,
        "noise_m": 16.0,
        "outliers": 0,
        "stopped": 14,
    },
    "mixed": {
        "n": 70,
        "speed": (10.0, 26.0),
        "stop_p": 0.12,
        "drop_p": 0.1,
        "noise_m": 20.0,
        "outliers": 6,
        "stopped": 8,
    },
}


def _graph():
    from app.routing import GRAPH

    return GRAPH


def _geom_len(geom: list) -> float:
    return sum(haversine_m(*a, *b) for a, b in zip(geom, geom[1:])) or 1.0


def _point_along(geom: list, dist_m: float) -> tuple[float, float, float]:
    """Return (lat, lon, heading_deg) at dist_m along geom."""
    if dist_m <= 0:
        lat1, lon1 = geom[0]
        lat2, lon2 = geom[1] if len(geom) > 1 else geom[0]
        return lat1, lon1, _heading(lat1, lon1, lat2, lon2)
    remaining = dist_m
    for (alat, alon), (blat, blon) in zip(geom, geom[1:]):
        seg = haversine_m(alat, alon, blat, blon)
        if remaining <= seg or seg == 0:
            t = 0 if seg == 0 else remaining / seg
            return alat + (blat - alat) * t, alon + (blon - alon) * t, _heading(alat, alon, blat, blon)
        remaining -= seg
    lat1, lon1 = geom[-2] if len(geom) > 1 else geom[-1]
    lat2, lon2 = geom[-1]
    return lat2, lon2, _heading(lat1, lon1, lat2, lon2)


def _heading(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return (math.degrees(math.atan2(dx, dy)) + 360.0) % 360.0


def _cp_geoms() -> list[list]:
    """Driveable edges within ~3 km of Connaught Place (circle + radials)."""
    GRAPH = _graph()
    geoms: list[list] = []
    for u, v, data in GRAPH.edges(data=True):
        nu, nv = GRAPH.nodes[u], GRAPH.nodes[v]
        mid_lat = (nu["lat"] + nv["lat"]) / 2
        mid_lon = (nu["lon"] + nv["lon"]) / 2
        if haversine_m(CP[0], CP[1], mid_lat, mid_lon) > CP_RADIUS_M:
            continue
        if data.get("metres", 0) < 80:
            continue
        geom = data.get("geom") or []
        if len(geom) >= 2:
            geoms.append(geom)
    return geoms


def _jitter(lat: float, lon: float, metres: float, rng: random.Random) -> tuple[float, float]:
    if metres <= 0:
        return lat, lon
    ang = rng.uniform(0, 2 * math.pi)
    r = rng.gauss(0, metres)
    return lat + (r * math.cos(ang)) / 111_000.0, lon + (r * math.sin(ang)) / (111_000.0 * math.cos(math.radians(lat)))


@dataclass
class Vehicle:
    vid: str
    geom: list
    dist_m: float
    speed_kmh: float
    cruise_kmh: float
    direction: int
    stop_until: float = 0.0
    drop_until: float = 0.0
    role: str = "normal"  # normal | outlier | stopped


@dataclass
class Simulator:
    scenario: str
    vehicles: list[Vehicle] = field(default_factory=list)
    path_nodes: list[int] = field(default_factory=list)
    running: bool = False
    tick: int = 0


_sim = Simulator(scenario="clear")
_thread: threading.Thread | None = None
_stop = threading.Event()
_rng = random.Random(11)


def _full_geom(nodes: list[int]) -> list[tuple[float, float]]:
    GRAPH = _graph()
    pts: list[tuple[float, float]] = []
    for u, v in zip(nodes, nodes[1:]):
        geom = list(GRAPH.edges[u, v]["geom"])
        if pts:
            d0 = haversine_m(*pts[-1], *geom[0])
            d1 = haversine_m(*pts[-1], *geom[-1])
            if d1 < d0:
                geom = geom[::-1]
            pts.extend(geom[1:])
        else:
            pts.extend(geom)
    return pts


def _spawn(scenario: str) -> Simulator:
    cfg = SCENARIOS[scenario]
    geoms = _cp_geoms()
    if not geoms:
        geoms = [data["geom"] for _, _, data in list(_graph().edges(data=True))[:40] if len(data.get("geom") or []) >= 2]
    lo, hi = cfg["speed"]
    vehicles: list[Vehicle] = []
    n = cfg["n"]
    for i in range(n):
        role = "normal"
        if i < cfg["stopped"]:
            role = "stopped"
        elif i < cfg["stopped"] + cfg["outliers"]:
            role = "outlier"
        if role == "outlier":
            cruise = _rng.uniform(55.0, 75.0)
        elif role == "stopped":
            cruise = lo
        else:
            cruise = _rng.uniform(lo, hi)
        geom = geoms[i % len(geoms)]
        total = _geom_len(geom)
        vehicles.append(
            Vehicle(
                vid=f"sim-{i:03d}",
                geom=geom,
                dist_m=_rng.uniform(0, total),
                speed_kmh=0.0 if role == "stopped" else cruise,
                cruise_kmh=cruise,
                direction=1 if i % 2 == 0 else -1,
                stop_until=time.time() + 1e9 if role == "stopped" else 0.0,
                role=role,
            )
        )
    return Simulator(scenario=scenario, vehicles=vehicles, path_nodes=[], running=True)


def _tick_vehicle(v: Vehicle, cfg: dict, now: float) -> None:
    total = _geom_len(v.geom)
    if v.role != "stopped" and v.stop_until < now and _rng.random() < cfg["stop_p"]:
        v.stop_until = now + _rng.uniform(4, 12)
    if now < v.stop_until:
        v.speed_kmh = 0.0
    else:
        jitter = _rng.uniform(-1.5, 1.5)
        v.speed_kmh = max(0.0, v.cruise_kmh + jitter)

    dropped = now < v.drop_until
    if not dropped and _rng.random() < cfg["drop_p"]:
        v.drop_until = now + _rng.uniform(3, 10)
        dropped = True

    if not dropped:
        step = (v.speed_kmh / 3.6) * DT_S
        v.dist_m += step * v.direction
        if v.dist_m >= total:
            v.dist_m = total
            v.direction = -1
        elif v.dist_m <= 0:
            v.dist_m = 0.0
            v.direction = 1

    lat, lon, heading = _point_along(v.geom, v.dist_m)
    if v.direction < 0:
        heading = (heading + 180.0) % 360.0
    noisy_lat, noisy_lon = _jitter(lat, lon, cfg["noise_m"], _rng)
    ingest_sim_fix(
        v.vid,
        noisy_lat,
        noisy_lon,
        v.speed_kmh,
        heading=heading,
        dropped_update=dropped,
    )


def _loop() -> None:
    while not _stop.is_set():
        cfg = SCENARIOS.get(_sim.scenario) or SCENARIOS["clear"]
        now = time.time()
        for v in list(_sim.vehicles):
            _tick_vehicle(v, cfg, now)
        _sim.tick += 1
        _stop.wait(DT_S)


def load(scenario: str = "moderate") -> dict:
    """Arm a scenario without starting the ticker (tests / first frame)."""
    global _sim
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    stop()
    traffic_reset(SIM)
    set_mode(SIM)
    _sim = _spawn(scenario)
    return status()


def start(scenario: str = "moderate") -> dict:
    global _thread
    load(scenario)
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="traffic-sim", daemon=True)
    _thread.start()
    info = status()
    info["ok"] = True
    return info


def step(ticks: int = 1) -> dict:
    """Advance the current scenario without the background thread (for tests)."""
    cfg = SCENARIOS.get(_sim.scenario) or SCENARIOS["clear"]
    for _ in range(max(1, ticks)):
        now = time.time()
        for v in list(_sim.vehicles):
            _tick_vehicle(v, cfg, now)
        _sim.tick += 1
    return status()


def stop() -> dict:
    global _thread
    _stop.set()
    if _thread is not None:
        _thread.join(timeout=2.0)
        _thread = None
    _sim.running = False
    return status()


def status() -> dict:
    from app.traffic import get_mode, snapshot

    return {
        "mode": get_mode(),
        "simulation_running": bool(_sim.running and _thread is not None and _thread.is_alive()),
        "scenario": _sim.scenario,
        "tick": _sim.tick,
        "vehicles": len(_sim.vehicles),
        "scenarios": list(SCENARIOS),
        "traffic": snapshot(),
    }
