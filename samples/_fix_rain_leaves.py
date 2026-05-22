"""Re-fetch rain and leaf_rustle with better queries."""
import json, os, time, urllib.request

API_KEY = "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE"
BASE = "https://freesound.org/apiv2"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
MANIFEST_PATH = os.path.join(OUT_DIR, "manifest.json")

rain_queries = [
    "rain falling",
    "light rain drizzle",
    "rain window",
    "rainstorm ambient",
    "rain drops",
]

fixes = [
    (rain_queries, "rain", 3, 60),
]

with open(MANIFEST_PATH) as f:
    manifest = json.load(f)
manifest_by_label = {e["label"]: e for e in manifest}

for queries, label, dur_min, dur_max in fixes:
    found = None
    for query in queries:
        filt = urllib.request.quote(
            'license:"Creative Commons 0" duration:[' + str(dur_min) + ' TO ' + str(dur_max) + ']'
        )
        url = (BASE + "/search/text/?query=" + urllib.request.quote(query) + "&filter=" + filt
               + "&sort=rating_desc&fields=id,name,duration,previews,username&page_size=3&token=" + API_KEY)
        time.sleep(1.5)
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
                data = json.loads(r.read())
            for s in data.get("results", []):
                preview = s["previews"].get("preview-hq-ogg", s["previews"].get("preview-hq-mp3",""))
                if preview:
                    s["preview"] = preview
                    found = s
                    print(f"[{label}] via '{query}': '{s['name']}' by {s['username']} ({s['duration']:.1f}s)")
                    break
        except Exception as e:
            print(f"  Error: {e}")
        if found:
            break
    if not found:
        print(f"[{label}] No results for any query")
        continue
    time.sleep(1.5)
    filepath = os.path.join(OUT_DIR, label + ".ogg")
    urllib.request.urlretrieve(found["preview"], filepath)
    size = os.path.getsize(filepath) // 1024
    print(f"  Downloaded -> {label}.ogg ({size} KB)")
    manifest_by_label[label] = {
        "file": label + ".ogg", "id": found["id"], "name": found["name"],
        "label": label, "duration": found["duration"],
        "user": found["username"], "preview": found["preview"],
    }

ordered = [e["label"] for e in manifest]
out = [manifest_by_label[l] for l in ordered if l in manifest_by_label]
with open(MANIFEST_PATH, "w") as f:
    json.dump(out, f, indent=2)
print("Manifest updated.")
