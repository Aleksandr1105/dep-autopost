import json, re, sys, time, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import publish_week as pw

API = "https://commons.wikimedia.org/w/api.php?"
def api(**kw):
    kw.update(action="query", format="json")
    for a in range(5):
        try:
            return json.loads(pw.http_get(API + urllib.parse.urlencode(kw)))
        except Exception as e:
            time.sleep(2 + a * 2)
    return {}

def clean(title):
    t = re.sub(r"^File:", "", title); t = re.sub(r"\.\w+$", "", t)
    t = re.sub(r"\([^)]*\)", " ", t); t = re.sub(r"[_\-]+", " ", t); t = re.sub(r"\b\d+\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()

def search(q, limit=40):
    d = api(generator="search", gsrnamespace=6, gsrsearch=q + " filetype:bitmap", gsrlimit=limit,
            prop="imageinfo", iiprop="extmetadata|size|mime|url", iiurlwidth=300)
    pages = sorted(d.get("query", {}).get("pages", {}).values(), key=lambda p: p.get("index", 0))
    out = []
    for p in pages:
        ii = (p.get("imageinfo") or [{}])[0]
        md = ii.get("extmetadata", {})
        if str(md.get("AttributionRequired", {}).get("value", "true")).lower() != "false": continue
        if ii.get("mime") != "image/jpeg": continue
        if ii.get("width", 0) < 1000 or ii.get("height", 0) < 600: continue
        if "svg" in p["title"].lower(): continue
        desc = pw.strip_html(md.get("ImageDescription", {}).get("value", ""))[:100]
        lic = pw.strip_html(md.get("LicenseShortName", {}).get("value", ""))
        out.append((p["title"], lic, desc))
    return out

BAD = re.compile(r"nude|vulva|woman|women|naked|bottomless|buttock|sex|breast|girl|bikini|erotic", re.I)

def good(r):
    return not BAD.search(r[0] + " " + r[2])

if __name__ == "__main__":
    rows = [l.strip().split("|", 1) for l in (Path(__file__).parent / "find_queries.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    chunk, n = [], 0
    for slot, q in rows:
        res, seen = [], set()
        for qq in (q, q + " Unsplash", q + " NASA" if any(w in q for w in ("Jupiter", "Messier", "phytoplankton", "Everest", "Amazon")) else q + " public domain"):
            for r in search(qq, 25):
                if r[0] not in seen and good(r):
                    seen.add(r[0]); res.append(r)
        lines = [f"## {slot} {q}"] + [f"  {a[5:]} | {b} | {c[:60]}" for a, b, c in res[:9]]
        chunk.append("\n".join(lines))
        if len(chunk) == 6:
            n += 1; print(f"::notice title=cand{n}::" + "%0A".join(chunk).replace("\n", "%0A")); chunk = []
    if chunk:
        print(f"::notice title=cand{n+1}::" + "%0A".join(chunk).replace("\n", "%0A"))
