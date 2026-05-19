"""Retry downloading remaining samples."""
import urllib.request
import json
import time
import os

API_KEY = "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE"
BASE = "https://freesound.org/apiv2"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

queries = [
    ("singing saw", "singing_saw"),
    ("chime bell", "chime"),
    ("breath exhale", "breath"),
    ("throat singing", "throat_singing"),
]

for query, label in queries:
    filepath = os.path.join(OUT_DIR, f"{label}.ogg")
    if os.path.exists(filepath):
        print(f"  SKIP {label}: already exists")
        continue

    filter_str = urllib.request.quote('license:"Creative Commons 0" duration:[1 TO 15]')
    url = (
        f"{BASE}/search/text/"
        f"?query={urllib.request.quote(query)}"
        f"&filter={filter_str}"
        f"&sort=rating_desc"
        f"&fields=id,name,duration,previews,username"
        f"&page_size=2"
        f"&token={API_KEY}"
    )
    try:
        time.sleep(2)
        with urllib.request.urlopen(urllib.request.Request(url), timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("results"):
                s = data["results"][0]
                preview = s["previews"].get("preview-hq-ogg", s["previews"].get("preview-hq-mp3", ""))
                if preview:
                    time.sleep(2)
                    urllib.request.urlretrieve(preview, filepath)
                    print(f"  OK: {label}.ogg ({s['name']} by {s['username']})")
                else:
                    print(f"  NO PREVIEW: {label}")
            else:
                print(f"  NO RESULTS: {label}")
    except Exception as e:
        print(f"  FAIL {label}: {e}")
