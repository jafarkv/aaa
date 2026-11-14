#!/usr/bin/env python3
"""
Turn intel/out/latest.json into write batches for the Promo Intel Desk artifact database.

Writes intel/out/artifact_batches.json: a list of batches (<= 50 writes each) in the exact
shape the ArtifactData "batch" action takes. Every write CREATES a new document, so no
versions are needed:
  runs/<date>-<hhmm>   one summary doc per crawl (URL counts, changes, top sections)
  pages/<hash>         one doc per new page found in a sitemap, new blog post, or industry headline

New non-product pages get their real <title> fetched so the feed reads like headlines.
Usage: python3 intel/to_artifact.py
"""
import hashlib, json, re, sys
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crawl  # reuses fetch() and the polite user agent

ROOT = Path(__file__).resolve().parent
latest = json.loads((ROOT / "out" / "latest.json").read_text())
run_at = latest["runAt"]
run_date = run_at[:10]
created = int(datetime.fromisoformat(run_at).timestamp() * 1000)

PER_COMP_PAGES = 40      # cap non-product pages per competitor per run
PER_COMP_PRODUCTS = 15   # products are noisy; keep a sample
TITLE_FETCH_CAP = 25     # titles fetched per competitor per run


def doc_id(url):
    return "p-" + hashlib.sha1(url.encode()).hexdigest()[:20]


def slug_title(url):
    """Readable fallback title from the URL slug."""
    path = urlparse(url).path.rstrip("/")
    last = path.split("/")[-1] if path else "home"
    last = re.sub(r"\.(html?|aspx|php)$", "", last)
    last = re.sub(r"[-_]+", " ", last).strip()
    return last[:1].upper() + last[1:] if last else url


def page_title(url):
    st, _, body = crawl.fetch(url, timeout=25)
    if st != 200:
        return None
    m = re.search(rb"<title[^>]*>(.*?)</title>", body[:200000], re.S | re.I)
    if not m:
        return None
    t = unescape(m.group(1).decode("utf-8", "ignore")).strip()
    return re.sub(r"\s+", " ", t)[:200] or None


writes = []

# 1) run summary
summary = {}
for cid, c in latest["competitors"].items():
    summary[cid] = {k: c.get(k) for k in ("name", "domain", "status", "urlCount", "addedCount", "removedCount",
                                          "byKind", "topSections", "note") if c.get(k) is not None}
    summary[cid]["feedCount"] = len(c.get("feeds") or [])
run_id = run_at[:16].replace(":", "").replace("T", "-")
writes.append({"op": "set", "collection": "runs", "doc_id": run_id,
               "data": {"runAt": run_at, "date": run_date, "competitors": summary, "track": "w4h", "createdAt": created}})

# 2) new pages from sitemap diffs
for cid, c in latest["competitors"].items():
    added = c.get("added") or []
    pages = [a for a in added if a["kind"] != "product"][:PER_COMP_PAGES]
    prods = [a for a in added if a["kind"] == "product"][:PER_COMP_PRODUCTS]
    fetched = 0
    for a in pages + prods:
        title = None
        if a["kind"] != "product" and fetched < TITLE_FETCH_CAP:
            title = page_title(a["url"]); fetched += 1
        writes.append({"op": "set", "collection": "pages", "doc_id": doc_id(a["url"]), "data": {
            "url": a["url"], "title": title or slug_title(a["url"]), "competitorId": cid, "competitorName": c["name"],
            "kind": a["kind"], "section": a["section"], "date": run_date, "source": "sitemap",
            "track": "w4h", "createdAt": created}})

# 3) new competitor blog posts (RSS)
for p in latest.get("posts", []):
    writes.append({"op": "set", "collection": "pages", "doc_id": doc_id(p["link"]), "data": {
        "url": p["link"], "title": p["title"], "competitorId": p["competitorId"], "competitorName": p["competitorName"],
        "kind": "post", "section": ", ".join(p.get("categories", [])[:3]), "date": p.get("date") or run_date,
        "source": "rss", "track": "w4h", "createdAt": created}})

# 4) industry headlines (RSS)
for p in latest.get("industry", []):
    if p.get("error"):
        continue
    writes.append({"op": "set", "collection": "pages", "doc_id": doc_id(p["link"]), "data": {
        "url": p["link"], "title": p["title"], "competitorId": "", "competitorName": p["source"],
        "kind": "industry", "section": ", ".join(p.get("categories", [])[:3]), "date": p.get("date") or run_date,
        "source": "rss", "track": "w4h", "createdAt": created}})

# de-duplicate by doc id (same URL can appear in a sitemap and a feed)
seen, uniq = set(), []
for w in writes:
    key = (w["collection"], w["doc_id"])
    if key not in seen:
        seen.add(key); uniq.append(w)

batches = [uniq[i:i + 50] for i in range(0, len(uniq), 50)]
(ROOT / "out" / "artifact_batches.json").write_text(json.dumps(batches, indent=1))

# Compact form for the ArtifactData tool: each document body goes in its own file and the
# batch references it by file_path, so the weekly task never pastes large JSON.
docs_dir = ROOT / "out" / "docs"
docs_dir.mkdir(exist_ok=True)
for f in docs_dir.glob("*.json"):
    f.unlink()
compact = []
for b in batches:
    cb = []
    for w in b:
        p = docs_dir / f"{w['collection']}__{w['doc_id']}.json"
        p.write_text(json.dumps(w["data"]))
        cb.append({"op": "set", "collection": w["collection"], "doc_id": w["doc_id"], "file_path": str(p)})
    compact.append(cb)
(ROOT / "out" / "artifact_batches_files.json").write_text(json.dumps(compact, indent=1))
print(f"{len(uniq)} writes in {len(batches)} batches -> intel/out/artifact_batches_files.json")
