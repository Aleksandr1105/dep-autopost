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

if __name__ == "__main__":
    titles = [l.strip() for l in (Path(__file__).parent / "find_queries.txt").read_text(encoding="utf-8").splitlines() if l.strip()]
    chunk, n = [], 0
    for t in titles:
        q = clean(t)
        res = search(q)
        if len(res) < 2:
            res += search(" ".join(q.split()[:2]))
        lines = [f"## {t}"] + [f"  {a} | {b} | {c}" for a, b, c in res[:5]]
        chunk.append("\n".join(lines))
        if len(chunk) == 8:
            n += 1; print(f"::notice title=cand{n}::" + " ## ".join(chunk).replace("\n", "%0A")); chunk = []
    if chunk:
        print(f"::notice title=cand{n+1}::" + " ## ".join(chunk).replace("\n", "%0A"))
