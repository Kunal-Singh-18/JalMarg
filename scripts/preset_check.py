"""Dev helper: print what each preset actually does at a given rainfall.

    python scripts/preset_check.py [--rain 50] [--pairs a:b,c:d]

Not used by the app. It exists so the numbers quoted in the README and in the
preset stories can be re-derived instead of remembered.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.loaders import load_facilities, load_hotspots, load_news  # noqa: E402
from app.main import PRESETS  # noqa: E402
from app.news import match_news  # noqa: E402
from app.risk import hotspot_risk  # noqa: E402
from app.routing import (  # noqa: E402
    LANDMARK_NODES,
    facility_access,
    graph_info,
    route,
    scored_edges,
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rain", type=float, default=50.0)
    ap.add_argument("--pairs", default="", help="extra origin:dest landmark pairs")
    args = ap.parse_args()

    hotspots = load_hotspots()
    facilities = load_facilities()
    news_ids, _ = match_news(load_news(), hotspots)
    scored = [hotspot_risk(s, args.rain, news_ids) for s in hotspots]
    edges = scored_edges(scored)
    facs = facility_access(facilities, scored, edges)

    info = graph_info()
    print(f"graph      {info['nodes']} nodes / {info['edges']} edges / {info['km']} km")
    print(f"landmarks  {info['landmarks']}   hotspots {len(hotspots)}   facilities {len(facilities)}")
    print(f"news-named {sum(1 for s in scored if s['news_mentioned'])}/{len(scored)}")
    print(
        f"rain {args.rain:.0f} mm -> blocked {sum(1 for s in scored if s['level'] == 'blocked')}"
        f" / likely {sum(1 for s in scored if s['level'] == 'likely')}"
        f" / watch {sum(1 for s in scored if s['level'] == 'watch')}"
        f"   affected edges {len(edges)} ({sum(1 for e in edges if e['blocked'])} blocked)"
    )
    print(
        "facilities  cut_off "
        f"{sum(1 for f in facs if f['status'] == 'cut_off')}"
        f" / at_risk {sum(1 for f in facs if f['status'] == 'at_risk')}"
        f" / site_flooded {sum(1 for f in facs if f['site_flooded'])}"
    )
    print()

    pairs = [(p["id"], p["origin"]["node"], p["dest"]["node"]) for p in PRESETS]
    for extra in filter(None, args.pairs.split(",")):
        a, b = extra.split(":")
        pairs.append((f"{a}->{b}", a, b))

    for pid, a, b in pairs:
        r = route({"node": a}, {"node": b}, edges)
        if "error" in r:
            print(f"{pid:22s} ERROR {r['error']}")
            continue
        naive = r["naive"]
        if r["unreachable"]:
            print(
                f"{pid:22s} {naive['km']:6.1f} km -> NO DRY PATH   "
                f"crosses {len(naive['flooded_segments'])} flooded: "
                f"{'; '.join(naive['flooded_segments'][:3])}"
            )
        else:
            safe = r["safe"]
            ratio = safe["km"] / naive["km"] if naive["km"] else 0
            print(
                f"{pid:22s} {naive['km']:6.1f} km -> {safe['km']:6.1f} km "
                f"({ratio:4.2f}x, +{safe['minutes'] - naive['minutes']:.0f} min)  "
                f"via {' / '.join(safe['via'][:3])}"
            )
            if naive["flooded_segments"]:
                print(f"{'':22s}   flooded on naive: {'; '.join(naive['flooded_segments'][:3])}")

    print()
    trouble = [f for f in facs if f["status"] != "open"]
    for f in sorted(trouble, key=lambda x: x["status"])[:25]:
        print(f"  {f['status']:8s} {f['name'][:38]:40s} {f['status_label']}")


if __name__ == "__main__":
    main()
