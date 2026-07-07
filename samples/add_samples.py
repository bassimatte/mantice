"""
Fetch new granular samples from Freesound (CC0) and update manifest.json.
Skips files that already exist. Appends new entries to manifest.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request

API_KEY = "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE"
BASE = "https://freesound.org/apiv2"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")

# --- New categories to add ---
NEW_QUERIES = [
    ("rock stone scrape rubbing",   "rock_scrape"),
    ("gravel crunch footstep",      "gravel"),
    ("fire crackle campfire",       "fire_crackle"),
    ("rain soft gentle",            "rain"),
    ("leaves rustle wind forest",   "leaf_rustle"),
    ("bubbles water underwater",    "bubbles"),
    ("deep low rumble sub bass",    "sub_rumble"),
    ("stick crack wood snap",       "stick_crack"),
]

# --- All original queries (to ensure manifest is complete) ---
ALL_QUERIES = [
    ("singing bowl tibetan",        "singing_bowl"),
    ("wine glass bowed resonant",   "bowed_glass"),
    ("gong sustained drone",        "gong"),
    ("metal resonant door",         "metal_resonance"),
    ("wind ambient nature",         "wind"),
    ("water stream gentle brook",   "water"),
    ("singing saw",                 "singing_saw"),
    ("chime bell",                  "chime"),
    ("breath exhale slow",          "breath"),
    ("throat singing drone",        "throat_singing"),
] + NEW_QUERIES


def search_freesound(query: str, duration_max: int = 20) -> dict | None:
    filter_str = urllib.request.quote(
        f'license:"Creative Commons 0" duration:[1 TO {duration_max}]'
    )
    url = (
        f"{BASE}/search/text/"
        f"?query={urllib.request.quote(query)}"
        f"&filter={filter_str}"
        f"&sort=rating_desc"
        f"&fields=id,name,duration,previews,username"
        f"&page_size=5"
        f"&token={API_KEY}"
    )
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as resp:
            data = json.loads(resp.read())
            for result in data.get("results", []):
                preview = result["previews"].get(
                    "preview-hq-ogg", result["previews"].get("preview-hq-mp3", "")
                )
                if preview:
                    return {
                        "id": result["id"],
                        "name": result["name"],
                        "duration": result["duration"],
                        "user": result["username"],
                        "preview": preview,
                    }
    except Exception as e:
        print(f"    Search error: {e}")
    return None


def download_file(url: str, filepath: str) -> bool:
    try:
        urllib.request.urlretrieve(url, filepath)
        return True
    except Exception as e:
        print(f"    Download error: {e}")
        return False


# Load existing manifest
if os.path.exists(MANIFEST_PATH):
    with open(MANIFEST_PATH) as f:
        manifest = json.load(f)
else:
    manifest = []

manifest_by_label = {entry["label"]: entry for entry in manifest}

# Process all queries — skip existing files, download missing ones
for query, label in ALL_QUERIES:
    ext = "ogg"
    filepath = os.path.join(OUT_DIR, f"{label}.{ext}")

    if os.path.exists(filepath) and label in manifest_by_label:
        print(f"  OK (exists): {label}")
        continue

    if os.path.exists(filepath) and label not in manifest_by_label:
        # File present but not in manifest — add it with placeholder metadata
        print(f"  Fixing manifest: {label} (file exists, missing from manifest)")
        manifest_by_label[label] = {
            "file": f"{label}.{ext}",
            "id": None,
            "name": label.replace("_", " "),
            "label": label,
            "duration": None,
            "user": "unknown",
            "preview": "",
        }
        continue

    print(f"  Searching: {query} → {label}")
    time.sleep(1.5)
    result = search_freesound(query)
    if not result:
        print(f"    No results — skipping {label}")
        continue

    print(f"    Found: '{result['name']}' by {result['user']} ({result['duration']:.1f}s)")
    time.sleep(1.5)
    if download_file(result["preview"], filepath):
        print(f"    Downloaded → {label}.{ext}")
        manifest_by_label[label] = {
            "file": f"{label}.{ext}",
            "id": result["id"],
            "name": result["name"],
            "label": label,
            "duration": result["duration"],
            "user": result["user"],
            "preview": result["preview"],
        }
    else:
        print(f"    Failed to download {label}")

# Rebuild manifest in canonical order
ordered_labels = [label for _, label in ALL_QUERIES]
manifest_out = []
for label in ordered_labels:
    if label in manifest_by_label:
        manifest_out.append(manifest_by_label[label])
# Include any extras not in ALL_QUERIES
for label, entry in manifest_by_label.items():
    if label not in ordered_labels:
        manifest_out.append(entry)

with open(MANIFEST_PATH, "w") as f:
    json.dump(manifest_out, f, indent=2)

print(f"\nDone. Manifest has {len(manifest_out)} entries.")
print("Files in samples/:")
for entry in manifest_out:
    fp = os.path.join(OUT_DIR, entry["file"])
    size = os.path.getsize(fp) // 1024 if os.path.exists(fp) else 0
    print(f"  {entry['label']:<20} {entry['file']:<30} {size:>5} KB")
