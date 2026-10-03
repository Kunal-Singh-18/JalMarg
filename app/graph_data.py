"""Road network for Delhi NCR: a cached OpenStreetMap extract plus a curated
landmark table.

The extract is produced offline by scripts/build_graph.py and read from
data/ncr_roads.json, so the app boots with no network.

OSM node ids are integers. Landmark ids are the human-readable strings the rest
of the project speaks in: data/hotspots.csv reuses several of them, PRESETS in
app/main.py addresses routes by them, and the frontend labels picks with them.
Each landmark snaps to its nearest OSM node at import.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GRAPH_FILE = ROOT / "data" / "ncr_roads.json"

_CLASS_LABEL = {
    "motorway": "Unnamed motorway",
    "trunk": "Unnamed trunk road",
    "primary": "Unnamed primary road",
    "secondary": "Unnamed secondary road",
    "tertiary": "Unnamed tertiary road",
    "unclassified": "Unnamed local road",
    "residential": "Unnamed residential road",
    "living_street": "Unnamed living street",
    "service": "Unnamed service road",
    "motorway_link": "Motorway link",
    "trunk_link": "Trunk link",
    "primary_link": "Primary link",
    "secondary_link": "Slip road",
    "tertiary_link": "Tertiary link",
}


def load_osm() -> dict:
    doc = json.loads(GRAPH_FILE.read_text(encoding="utf-8"))
    ids = [n[0] for n in doc["nodes"]]
    names, classes = doc["names"], doc["classes"]

    edges = []
    for u, v, ni, metres, ci, flat in doc["edges"]:
        klass = classes[ci]
        geom = [(flat[i], flat[i + 1]) for i in range(0, len(flat), 2)]
        edges.append(
            (
                ids[u],
                ids[v],
                names[ni] or _CLASS_LABEL.get(klass, "Unnamed road"),
                metres,
                klass,
                geom,
            )
        )
    return {
        "nodes": [(n[0], n[1], n[2]) for n in doc["nodes"]],
        "edges": edges,
        "meta": {
            k: doc[k]
            for k in (
                "source",
                "license",
                "generated_utc",
                "bbox",
                "highway_classes",
                "excluded",
                "exclusion_labels",
                "note",
            )
            if k in doc
        },
    }


# id, display name, lat, lon
LANDMARKS = [
    # Central Delhi
    ("cp", "Connaught Place", 28.6315, 77.2167),
    ("minto", "Minto Bridge", 28.6308, 77.2245),
    ("ito", "ITO", 28.6289, 77.2410),
    ("india_gate", "India Gate", 28.6129, 77.2295),
    ("rml", "RML Hospital", 28.6254, 77.2010),
    ("karol_bagh", "Karol Bagh", 28.6545, 77.1915),
    ("kashmere", "Kashmere Gate", 28.6675, 77.2284),
    ("civil_lines", "Civil Lines", 28.6770, 77.2230),
    ("rajpur", "Rajpur Road", 28.6795, 77.2210),
    ("lnjp", "LNJP Hospital", 28.6410, 77.2380),
    ("chandni", "Chandni Chowk", 28.6505, 77.2303),
    ("mandi_house", "Mandi House", 28.6254, 77.2340),
    ("daryaganj", "Daryaganj", 28.6430, 77.2410),
    ("bhairon", "Bhairon Marg", 28.6120, 77.2455),
    # South Delhi
    ("aiims", "AIIMS campus", 28.5668, 77.2075),
    ("aiims_ring", "AIIMS Ring Rd underpass", 28.5688, 77.2110),
    ("safdarjung", "Safdarjung Hospital", 28.5683, 77.2060),
    ("ino", "INA", 28.5744, 77.2095),
    ("south_ex", "South Extension", 28.5689, 77.2194),
    ("andrews", "Andrews Ganj", 28.5654, 77.2267),
    ("defence", "Defence Colony", 28.5734, 77.2328),
    ("lajpat", "Lajpat Nagar", 28.5706, 77.2430),
    ("ashram", "Ashram Chowk", 28.5729, 77.2591),
    ("nehru_place", "Nehru Place", 28.5494, 77.2501),
    ("kalkaji", "Kalkaji", 28.5402, 77.2608),
    ("okhla", "Okhla", 28.5470, 77.2730),
    ("holy_family", "Holy Family Hospital", 28.5645, 77.2760),
    ("sarita_vihar", "Sarita Vihar", 28.5310, 77.2900),
    ("apollo", "Apollo Hospital", 28.5410, 77.2832),
    ("badarpur", "Badarpur Border", 28.4930, 77.3040),
    ("pul_prahladpur", "Pul Prahladpur", 28.4952, 77.2810),
    ("saket", "Saket", 28.5284, 77.2192),
    ("chirag_delhi", "Chirag Delhi flyover", 28.5378, 77.2258),
    ("hauz_khas", "Hauz Khas", 28.5494, 77.2001),
    ("rk_puram", "RK Puram", 28.5633, 77.1868),
    ("moti_bagh", "Moti Bagh", 28.5760, 77.1780),
    ("munirka", "Munirka", 28.5540, 77.1730),
    ("vasant_vihar", "Vasant Vihar", 28.5590, 77.1580),
    ("vasant_kunj", "Vasant Kunj", 28.5245, 77.1570),
    ("mehrauli", "Mehrauli", 28.5175, 77.1855),
    ("dhaula_kuan", "Dhaula Kuan", 28.5918, 77.1616),
    ("nizamuddin", "Nizamuddin", 28.5892, 77.2534),
    ("sarai_kk", "Sarai Kale Khan", 28.5885, 77.2586),
    ("barapullah", "Barapullah", 28.5834, 77.2458),
    # West Delhi
    ("punjabi_bagh", "Punjabi Bagh", 28.6686, 77.1319),
    ("raja_garden", "Raja Garden", 28.6512, 77.1245),
    ("mayapuri", "Mayapuri", 28.6378, 77.1289),
    ("naraina", "Naraina", 28.6306, 77.1408),
    ("moti_nagar", "Moti Nagar", 28.6578, 77.1424),
    ("zakhira", "Zakhira underpass", 28.6635, 77.1520),
    ("hari_nagar", "Hari Nagar / DDU Hospital", 28.6295, 77.1215),
    ("janakpuri", "Janakpuri", 28.6210, 77.0878),
    ("tilak_nagar", "Tilak Nagar", 28.6365, 77.0964),
    ("peeragarhi", "Peeragarhi", 28.6795, 77.0930),
    ("nangloi", "Nangloi", 28.6820, 77.0640),
    ("mangolpuri", "Mangolpuri", 28.6825, 77.0800),
    # South-west Delhi
    ("dwarka_mor", "Dwarka Mor", 28.6193, 77.0333),
    ("dwarka", "Dwarka Sec 10", 28.5810, 77.0570),
    ("dwarka_21", "Dwarka Sector 21", 28.5525, 77.0585),
    ("najafgarh", "Najafgarh", 28.6090, 76.9800),
    ("palam", "Palam", 28.5772, 77.1065),
    ("mahipalpur", "Mahipalpur", 28.5450, 77.1250),
    ("kapashera", "Kapashera Border", 28.5230, 77.0850),
    # North Delhi
    ("azadpur", "Azadpur", 28.7116, 77.1734),
    ("jahangirpuri", "Jahangirpuri", 28.7259, 77.1627),
    ("pitampura", "Pitampura", 28.7031, 77.1322),
    ("rohini", "Rohini West", 28.7149, 77.1156),
    ("rithala", "Rithala", 28.7210, 77.1070),
    ("shalimar_bagh", "Shalimar Bagh", 28.7015, 77.1585),
    ("model_town", "Model Town", 28.7026, 77.1937),
    ("mukarba", "Mukarba Chowk", 28.7385, 77.1585),
    ("burari", "Burari", 28.7480, 77.1970),
    ("wazirabad", "Wazirabad", 28.7100, 77.2300),
    ("narela", "Narela", 28.8390, 77.0995),
    ("bawana", "Bawana", 28.7970, 77.0450),
    # East Delhi / trans-Yamuna
    ("yamuna_bank", "Yamuna Bank", 28.6230, 77.2680),
    ("laxmi_nagar", "Laxmi Nagar", 28.6304, 77.2773),
    ("mayur_vihar", "Mayur Vihar", 28.6038, 77.2915),
    ("anand_vihar", "Anand Vihar", 28.6469, 77.3159),
    ("akshardham", "Akshardham", 28.6127, 77.2773),
    ("dilshad", "Dilshad Garden", 28.6820, 77.3090),
    ("geeta_colony", "Geeta Colony", 28.6550, 77.2680),
    ("shastri_park", "Shastri Park", 28.6690, 77.2510),
    ("seelampur", "Seelampur", 28.6700, 77.2680),
    ("shahdara", "Shahdara", 28.6700, 77.2890),
    ("karkardooma", "Karkardooma", 28.6540, 77.3010),
    ("ghazipur", "Ghazipur", 28.6250, 77.3260),
    ("khichripur", "Khichripur", 28.6250, 77.3050),
    ("chilla", "Chilla Border", 28.5990, 77.2960),
    # Gurugram
    ("iffco", "IFFCO Chowk", 28.4722, 77.0718),
    ("mg_road", "MG Road", 28.4805, 77.0805),
    ("cyber_hub", "Cyber Hub", 28.4950, 77.0890),
    ("golf_course", "Golf Course Road", 28.4590, 77.0960),
    ("rajiv_chowk", "Rajiv Chowk NH-48", 28.4590, 77.0720),
    ("hero_honda", "Hero Honda Chowk", 28.4390, 77.0330),
    ("basai", "Basai", 28.4730, 77.0175),
    ("ggm_civil", "Civil Hospital Gurugram", 28.4620, 77.0250),
    ("fortis_ggm", "Fortis Memorial Gurugram", 28.4568, 77.0726),
    ("medanta", "Medanta", 28.4395, 77.0408),
    ("sohna", "Sohna Road / Badshahpur", 28.4080, 77.0470),
    # Noida / Greater Noida
    ("dnd", "DND (Noida end)", 28.5750, 77.3050),
    ("noida_18", "Noida Sector 18", 28.5701, 77.3210),
    ("botanical", "Botanical Garden", 28.5642, 77.3344),
    ("mahamaya", "Mahamaya Flyover", 28.5675, 77.3260),
    ("noida_30", "Noida Sector 30", 28.5810, 77.3520),
    ("noida_62", "Noida Sector 62", 28.6198, 77.3715),
    ("noida_128", "Noida Sector 128", 28.5155, 77.3800),
    ("noida_137", "Noida Sector 137", 28.5065, 77.4090),
    ("pari_chowk", "Pari Chowk, Greater Noida", 28.4640, 77.5040),
    ("gims", "GIMS Greater Noida", 28.4550, 77.5060),
    # Ghaziabad
    ("indirapuram", "Indirapuram", 28.6420, 77.3770),
    ("vaishali", "Vaishali", 28.6498, 77.3395),
    ("vasundhara", "Vasundhara", 28.6600, 77.3720),
    ("mohan_nagar", "Mohan Nagar", 28.6830, 77.3450),
    ("kavi_nagar", "Ghaziabad (Kavi Nagar)", 28.6740, 77.4260),
    ("loni", "Loni", 28.7530, 77.2880),
    # Faridabad
    ("badkhal", "Badkhal Mor, Faridabad", 28.4090, 77.3080),
    ("bata_chowk", "Bata Chowk, Faridabad", 28.3830, 77.3130),
    ("faridabad_21", "Faridabad Sector 21", 28.4140, 77.3105),
    ("ballabgarh", "Ballabgarh", 28.3390, 77.3230),
]
