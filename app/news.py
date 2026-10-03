from __future__ import annotations

# Tokens that name a road feature or a district rather than a place. Matching on
# these turns one headline about one chowk into a citywide news boost.
GENERIC = frozenset(
    {
        "delhi",
        "gurugram",
        "gurgaon",
        "noida",
        "ghaziabad",
        "faridabad",
        "greater",
        "north",
        "south",
        "east",
        "west",
        "central",
        "bridge",
        "chowk",
        "underpass",
        "flyover",
        "tunnel",
        "border",
        "market",
        "sector",
        "colony",
        "nagar",
        "vihar",
        "garden",
        "puram",
        "marg",
        "road",
        "roads",
        "expressway",
        "stretch",
        "approach",
        "extension",
    }
)


def gazetteer(hotspots: list[dict]) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = []
    for s in hotspots:
        names.append((s["name"], s["id"]))
        for token in s["name"].replace("/", " ").replace("(", " ").replace(")", " ").split():
            if len(token) >= 5 and token.lower() not in GENERIC:
                names.append((token, s["id"]))
    # Longer names first so "Rajpur Road underpass" beats "Rajpur"
    names.sort(key=lambda x: len(x[0]), reverse=True)
    return names


def match_news(articles: list[dict], hotspots: list[dict]) -> tuple[set[str], list[dict]]:
    gaz = gazetteer(hotspots)
    mentioned: set[str] = set()
    annotated = []
    for art in articles:
        text = f"{art.get('headline', '')} {art.get('outlet', '')}".lower()
        hits = []
        seen = set()
        for name, sid in gaz:
            if name.lower() in text and sid not in seen:
                seen.add(sid)
                hits.append(sid)
                mentioned.add(sid)
        annotated.append({**art, "hotspot_ids": hits})
    return mentioned, annotated
