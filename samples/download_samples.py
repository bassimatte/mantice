"""Download CC0 samples from Freesound for granular synthesis."""
import urllib.request
import json
import os

API_KEY = "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE"
BASE = "https://freesound.org/apiv2"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

queries = [
    ("singing bowl", "singing_bowl"),
    ("wine glass bowed", "bowed_glass"),
    ("gong sustained", "gong"),
    ("metal resonant", "metal_resonance"),
    ("wind ambient nature", "wind"),
    ("water stream gentle", "water"),
    ("singing saw", "singing_saw"),
    ("chime bell", "chime"),
    ("breath exhale slow", "breath"),
    ("throat singing drone", "throat_singing"),
]

results = []
for query, label in queries:
    filter_str = urllib.request.quote(f'license:"Creative Commons 0" duration:[1 TO 15]')
    url = (
        f"{BASE}/search/text/"
        f"?query={urllib.request.quote(query)}"
        f"&filter={filter_str}"
        f"&sort=rating_desc"
        f"&fields=id,name,duration,previews,tags,username"
        f"&page_size=3"
        f"&token={API_KEY}"
    )
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read())
            for s in data.get("results", [])[:2]:
                preview_url = s["previews"].get(
                    "preview-hq-ogg", s["previews"].get("preview-hq-mp3", "")
                )
                results.append({
                    "id": s["id"],
                    "name": s["name"],
                    "label": label,
                    "duration": s["duration"],
                    "user": s["username"],
                    "preview": preview_url,
                })
                print(f"  [{label}] {s['name']} ({s['duration']:.1f}s) by {s['username']} - ID:{s['id']}")
    except Exception as e:
        print(f"  SKIP {label}: {e}")

print(f"\nFound {len(results)} candidates. Downloading best for each category...")

# Pick best (first) per label and download
downloaded = []
seen_labels = set()
for item in results:
    if item["label"] in seen_labels:
        continue
    seen_labels.add(item["label"])
    if not item["preview"]:
        continue

    ext = "ogg" if "ogg" in item["preview"] else "mp3"
    filename = f"{item['label']}.{ext}"
    filepath = os.path.join(OUT_DIR, filename)

    print(f"  Downloading: {filename} ({item['name']})")
    try:
        urllib.request.urlretrieve(item["preview"], filepath)
        downloaded.append({"file": filename, **item})
        print(f"    OK -> {filename}")
    except Exception as e:
        print(f"    FAIL: {e}")

# Save manifest
manifest_path = os.path.join(OUT_DIR, "manifest.json")
with open(manifest_path, "w") as f:
    json.dump(downloaded, f, indent=2)

print(f"\nDone! Downloaded {len(downloaded)} samples to {OUT_DIR}")
