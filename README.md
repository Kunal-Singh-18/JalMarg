# JalMarg — urban waterlogging & emergency access

Delhi NCR monsoon operations desk. Known waterlogging pins, a rainfall slider, live weather squares, facilities that lose access, and ambulance routes that **cannot use flooded roads**.

This is a **scoring model**, not a hydrology engine. Spots are compiled from public MCD/NDMC and NCR civic lists plus news archives, so the map names real streets.

Roads are the real thing: an OpenStreetMap driveable-road extract for the region (major and minor, named and unnamed), cached on disk. Restricted-access, foot-only, and incomplete stretches are excluded with a recorded reason.

## Run

From this folder, with the project venv:

```powershell
..\..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8765
```

Open http://127.0.0.1:8765

Or: `.\run.ps1`

Boot is offline. The road network is read from `data/ncr_roads.json`. Search, live weather, and live traffic talk to the network only when you use those modes.

## Rainfall modes

The desk has **two rainfall sources**. They are never mixed.

### Manual / Simulation

- Slider **0–120 mm** over three hours
- Presets **10 / 25 / 50 / 80 mm**
- One test value for the whole NCR — for pitching and what-if runs

Moving the slider or a preset always returns you to this mode.

### Real-Time Weather Monitoring

An extra option on the same map and the same router. It does not replace the slider.

- NCR is tiled into **4 km squares** (15×15)
- Live rain and precipitation come from **Open-Meteo**, one reading per square
- Each road uses the square it sits in, not a single Delhi-wide millimetre value
- The map draws **only the squares the selected path crosses**
- Hover a square for **area name and millimetres**
- If live rain in a crossed cell jumps by **8 mm or more**, the path is rechecked and the desk explains if it changed
- Missing or failed weather is **not stored as 0 mm**. The cell is marked unavailable/stale and treated as uncertain, not dry

Example: a Nizamuddin → Holy Family run may read Central 6 mm → South 10 mm → Noida 8 mm on the same route.

## Routing (unchanged engine)

One Dijkstra on the OSM graph. Live squares only change the rain each edge sees.

| Option | What it is |
|---|---|
| Fastest | Shortest travel time |
| Dry | Avoids flooded roads |
| Safest | Highest safety score |
| Balanced | Time / safety (default) |
| Alternate | A different dry path when one exists |

If no dry path remains, the desk says so instead of inventing a line.

## Location

- **From / To** search (Nominatim, NCR-biased, via the server — the browser does not hit OSM)
- Landmark suggestions from the desk's place list
- **GPS** sets From
- Map click: origin, then destination, snapped to the road network

## Traffic overlay

A separate layer (Feature 1). Live GPS pings or a Connaught Place simulation. Median speed → clear / moderate / heavy. Live and simulation never mix.

## Light / dark

Header toggle. Preference is kept in the browser. Map tiles follow the theme.

## Pitch walkthrough (5 minutes)

1. Open the map. Red pins are chronic spots (Minto Bridge, Rajpur Road underpass, AIIMS Ring Road, Zakhira, Pul Prahladpur, Ashram Chowk, Hero Honda Chowk, …).
2. Stay on **Manual / Simulation**. Set rain to **50 mm**. Underpasses go red first. The sidebar splits two questions that are easy to confuse: **9 facility sites are inside a flood radius**, but **0 are unreachable by road**. AIIMS reads "site flooded, road access clear" — the water is at the gate, the ambulance can still get there.
3. Keep the preset **Nizamuddin → Holy Family**. Find route options. Ashram Chowk and Sarai Kale Khan close the Ring Road together, so 4.4 km becomes **12.5 km** back up Bhairon Marg and down through Lajpat Nagar. Click a card to draw that option.
4. Switch to **Raja Garden → RML** for the honest failure case: every road out of that junction is inside a flood zone, and the desk says so instead of guessing.
5. Switch to **Noida Sector 18 → Apollo**. At 50 mm nothing changes — Noida's grid has parallel roads. Push the slider to **80 mm** and Sector 18 becomes an island. The model is allowed to say "fine".
6. Turn on **Real-Time Weather Monitoring**. Squares appear only on the chosen path. Hover for the area name. Flood pins and the recommended option now follow **per-square** rain, not the slider.
7. Click a pin: severity, underpass flag, news mention, civic/news source. Click a road: the real OSM street name and which hotspot is closing it.

## Demo presets

At 50 mm rain (simulation):

| Preset | Naive | Safer | Why |
|---|---|---|---|
| Nizamuddin → Holy Family (Okhla) | 4.4 km | **12.5 km** | Ashram Chowk + Sarai Kale Khan close the Ring Road |
| MG Road → Fortis Gurugram | 3.4 km | **7.0 km** | Mehrauli-Gurgaon Road service lanes go under |
| Lajpat Nagar → AIIMS | 4.3 km | **7.1 km** | AIIMS Ring Road underpass and the flyover approach |
| Rajpur Road → LNJP | 5.9 km | **no dry path** | Every road out of the junction is flooded |
| Raja Garden → RML | 9.8 km | **no dry path** | Ring Road, Najafgarh Road and the flyover all go |
| Noida Sector 18 → Apollo | 7.6 km | 7.6 km | Noida's grid absorbs it — until 80 mm, when Sector 18 islands |

Re-derive them at any rainfall with `python scripts/preset_check.py --rain 50`.

## What is in the box

| Piece | Where |
|---|---|
| Hotspots CSV | `data/hotspots.csv` |
| Hospitals, fire, schools | `data/facilities.csv` |
| Sample headlines → place names | `data/news_samples.json` + `app/news.py` |
| Cached OSM road network | `data/ncr_roads.json` (1.5 MB) |
| Named landmarks → OSM nodes | `app/graph_data.py` |
| Risk = rain × severity × underpass/elevation × news | `app/risk.py` |
| Dijkstra on dry graph, facility access | `app/routing.py` |
| Slider rain + Open-Meteo city fetch | `app/rainfall.py` |
| 4 km NCR weather squares, live rain | `app/weather_zones.py` |
| Search / reverse geocode | `app/places.py` |
| GPS traffic + Connaught Place sim | `app/traffic.py`, `app/traffic_sim.py` |

No API keys. Open-Meteo and Nominatim are used unauthenticated, with a polite User-Agent on Nominatim.

## Rebuilding the road network

`data/ncr_roads.json` is committed so the demo starts instantly. To regenerate it:

```powershell
..\..\.venv\Scripts\python.exe scripts\build_graph.py
```

It pulls `motorway|trunk|primary|secondary` and their links for a Delhi + Gurugram + Faridabad + Noida + Ghaziabad box from the Overpass API in nine tiles (roughly ten minutes, and Overpass will rate-limit you), contracts the ways at intersections, merges same-name runs under 1.2 km, keeps the largest connected component, and writes a compact JSON with real road names and real edge geometry. No new dependency — it uses the `httpx` the app already ships.

Landmark ids like `minto` and `aiims_ring` stay human-readable: `app/graph_data.py` keeps a curated landmark table and snaps each entry to its nearest routable OSM node at import, so `data/hotspots.csv` and the presets keep speaking in place names while Dijkstra runs on integer OSM ids.

## Known limits

- The graph is **undirected** and ignores one-ways and turn restrictions. Fine for a reroute demo, wrong for turn-by-turn navigation.
- Only major roads are in the graph. Where a district's parallel routes are residential or tertiary in OSM — Faridabad is the worst case — a closure on the one arterial produces a detour far longer than a local driver would accept. Treat outer-NCR numbers as indicative.
- Flood radius is a disc around a point, not a modelled inundation extent. On a dense network that means detours are usually short; the dramatic numbers come from topology (rail underpasses, river crossings, single arterials), not from puddle size.
- Facility status answers two questions. `site_flooded` means the site sits inside a hotspot's radius. `road_access` is `clear`, `degraded` (some approach roads flooded) or `cut_off` (no dry road reaches it from the main network). The sidebar only says "cut off" for the second one.
- Live squares are **4 km**. Open-Meteo's rain field is about that coarse, so finer cells would mostly repeat the same millimetres. Live rain is recent precipitation scaled like the slider, not a gauge network.
- Path squares are a display filter. Dijkstra still sees rain on every square it might enter while searching.

## Tests

```powershell
..\..\.venv\Scripts\python.exe -m pytest -q
```

Covers the things that actually broke: the cached graph loads with real geometry and names, every landmark resolves to a live OSM node, every preset routes, the safer path never touches a blocked edge, a flooded-site facility is still reported as reachable when it is, search stays empty on junk queries, squares are actually square, Gurugram is not scored as Noida, and missing live rain is not stored as 0 mm.
