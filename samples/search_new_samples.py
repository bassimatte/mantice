"""Search Freesound for new granular samples and print top candidates."""
import json, urllib.request, time

API_KEY = "zwjXCAeWopixCMievVQ5q1FLmyh1DBvMf4HJuqNE"
BASE = "https://freesound.org/apiv2"

SEARCHES = [
    ("water stream river deep flowing",          "water",     "REPLACE"),
    ("hammer metal strike impact blow",          "hammer",    "NEW"),
    ("heavy gears grinding industrial turning",  "gears",     "NEW"),
    ("chain metallic rattle drag clank",         "chain",     "NEW"),
    ("machine engine industrial hum drone",      "machine",   "NEW"),
    ("ice crack cracking freeze cold",           "ice_crack", "NEW"),
    ("glacier ice deep groan rumble slow",       "glacier",   "NEW"),
]


def search(query, n=5):
    lic = "license:\"Creative Commons 0\" duration:[3 TO 30]"
    filt = urllib.request.quote(lic)
    url = (
        f"{BASE}/search/text/"
        f"?query={urllib.request.quote(query)}"
        f"&filter={filt}"
        f"&sort=rating_desc"
        f"&fields=id,name,duration,previews,username,avg_rating,num_downloads"
        f"&page_size={n}"
        f"&token={API_KEY}"
    )
    with urllib.request.urlopen(urllib.request.Request(url), timeout=15) as r:
        return json.loads(r.read()).get("results", [])


for query, label, status in SEARCHES:
    print(f"\n=== {label} ({status})")
    print(f"    query: {query}")
    try:
        results = search(query)
        for r in results[:4]:
            preview = r["previews"].get("preview-hq-ogg", "")
            print(f"  [{r['id']}] {r['name'][:58]:<58}  {r['duration']:5.1f}s  @{r['username']}")
            print(f"           preview: {preview}")
    except Exception as e:
        print(f"  ERROR: {e}")
    time.sleep(1.5)

print("\nDone.")
