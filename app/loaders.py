from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
STATIC = ROOT / "static"


def load_hotspots() -> list[dict]:
    rows = []
    with (DATA / "hotspots.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "area": row["area"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "severity": int(row["severity"]),
                    "is_underpass": row["is_underpass"] == "1",
                    "relative_elevation_m": float(row["relative_elevation_m"]),
                    "source": row["source"],
                    "notes": row["notes"],
                }
            )
    return rows


def load_facilities() -> list[dict]:
    rows = []
    with (DATA / "facilities.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                    "notes": row["notes"],
                }
            )
    return rows


def load_news() -> list[dict]:
    return json.loads((DATA / "news_samples.json").read_text(encoding="utf-8"))
