#!/usr/bin/env python3
"""
Promo Intel state + publishing — the tracker database is the crawler's memory.

  python3 state.py restore <export_dir>
      <export_dir>/crawlstate/*.json is what ArtifactData "list" (collection "crawlstate",
      out_dir=<export_dir>) saves. Rebuilds snapshots/, state/feeds.json and state/pages/
      from the newest run, and remembers every stored doc id so publish can delete them.

  python3 state.py uploads
      Lists screenshots that need uploading (changed pages + pages never uploaded) into
      out/upload_list.json. Claude uploads them with the Artifact tool (asset upload) and
      writes out/asset_map.json as {"<pageId>": "<asset url>", ...}.

  python3 state.py publish
      Builds out/batches.json: ArtifactData "batch" payloads (<= 50 writes, <= ~850 KB each).
      Every document is write-once (version 1), so no version bookkeeping is needed:
        crawlstate/*   new memory for this run, old run's memory deleted (if_version 1)
        runs/<run>     crawl summary per site (competitors + own brands)
        gaps/<run>     content-gap counts per site
        boards/<run>   current state of every watched key page (screenshot, offers, banners, nav, tech)
        pagechanges/*  one doc per key page that changed this week
        pages/*        new pages from sitemaps, new blog posts, industry headlines
        signals/*      offers spotted on competitor pages (status New, flagged auto)
"""
import hashlib, json, re, sys
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import crawl  # fetch(), polite user agent, config

OUT, SNAP, STATE = ROOT / "out", ROOT / "snapshots", ROOT / "state"
PAGES_STATE = STATE / "pages"
DOCS = OUT / "docs"
CFG = crawl.CFG
BRAND = {c["id"]: c.get("brand", "Proimprint") for c in CFG["competitors"]}
SHARD = 17000          # hashes per snapshot doc (~221 KB)
BATCH_BYTES = 850_000  # ArtifactData batch body limit is 1 MiB
TRACK = "w4h"
STATE_ONLY = False


def jload(p, default=None):
    p = Path(p)
    return json.loads(p.read_text()) if p.exists() else default


# ---------------- restore ----------------
def restore(export_dir):
    src = Path(export_dir) / "crawlstate"
    docs = {f.stem: json.loads(f.read_text()) for f in src.glob("*.json")} if src.exists() else {}
    index = sorted(docs)
    if not docs:
        print("no stored state: first run starts from local files / a fresh baseline")
    latest = {}
    for did, d in docs.items():
        key = (d["kind"], d.get("key", "") if d["kind"] != "pagebundle" else "")
        if key not in latest or d["runId"] > latest[key]:
            latest[key] = d["runId"]
    snaps = {}
    for did, d in docs.items():
        if latest.get((d["kind"], d.get("key", "") if d["kind"] != "pagebundle" else "")) != d["runId"]:
            continue
        if d["kind"] == "snap":
            snaps.setdefault(d["key"], []).append((d["part"], d["payload"]))
        elif d["kind"] == "feeds":
            (STATE / "feeds.json").write_text(json.dumps(d["payload"]))
        elif d["kind"] == "page":
            PAGES_STATE.mkdir(parents=True, exist_ok=True)
            (PAGES_STATE / f"{d['key']}.json").write_text(json.dumps(d["payload"]))
        elif d["kind"] == "pagebundle":
            PAGES_STATE.mkdir(parents=True, exist_ok=True)
            for pid, st in d["payload"].items():
                (PAGES_STATE / f"{pid}.json").write_text(json.dumps(st))
    SNAP.mkdir(exist_ok=True)
    for cid, parts in snaps.items():
        hashes = "\n".join(p for _, p in sorted(parts))
        (SNAP / f"{cid}.hashes").write_text(hashes)
        legacy = SNAP / f"{cid}.txt.gz"
        if legacy.exists():
            legacy.unlink()
    (STATE / "db_index.json").write_text(json.dumps(index))
    known = sorted({json.loads(f.read_text()).get("url", "") for f in (Path(export_dir) / "pages").glob("*.json")} - {""}) \
        if (Path(export_dir) / "pages").exists() else []
    (STATE / "known_urls.json").write_text(json.dumps(known))
    print(f"restored {len(snaps)} snapshots, {len(list(PAGES_STATE.glob('*.json'))) if PAGES_STATE.exists() else 0} page states; {len(index)} stored docs indexed")


# ---------------- uploads ----------------
def uploads():
    pw = jload(OUT / "pagewatch.json", {"pages": []})
    todo = [{"pageId": p["id"], "file": p["screenshot"], "label": f"{p['competitorName']} · {p['label']}"}
            for p in pw["pages"] if p.get("needsUpload") and p.get("screenshot")]
    (OUT / "upload_list.json").write_text(json.dumps(todo, indent=1))
    print(f"{len(todo)} screenshots to upload -> out/upload_list.json")
    for i in range(0, len(todo), 25):
        print(f"  group {i//25+1}: " + json.dumps([t["file"] for t in todo[i:i+25]]))


# ---------------- publish helpers ----------------
def did(prefix, s):
    return f"{prefix}-" + hashlib.sha1(s.encode()).hexdigest()[:20]


def slug_title(url):
    """Readable title from the URL: the most descriptive path segment, not a trailing product code."""
    segs = [re.sub(r"\.(html?|aspx|php|htm)$", "", x) for x in urlparse(url).path.split("/") if x]
    if not segs:
        return "Home page"
    words = lambda seg: [w for w in re.split(r"[-_]+", seg) if re.search(r"[a-z]{3,}", w.lower())]
    best = max(segs, key=lambda seg: (len(words(seg)), len(seg)))
    text = re.sub(r"[-_]+", " ", best).strip()
    return text[:1].upper() + text[1:] if text else url


def page_title(url):
    st, _, body = crawl.fetch(url, timeout=25)
    if st != 200:
        return None
    m = re.search(rb"<title[^>]*>(.*?)</title>", body[:200000], re.S | re.I)
    if not m:
        return None
    t = re.sub(r"\s+", " ", unescape(m.group(1).decode("utf-8", "ignore"))).strip()
    return t[:200] or None


STRONG_OFFER = re.compile(r"(\d{1,2}\s?%\s?off|save\s+\$?\d|\$\d+\s+off|free\s+(shipping|setup|set-up|samples?|rush|design)|promo code|use code|code:?\s*[A-Z0-9]{5,}|no\s+minimum|sale ends|limited time|black friday|cyber monday)", re.I)


# ---------------- publish ----------------
def publish():
    latest = jload(OUT / "latest.json")
    pw = jload(OUT / "pagewatch.json", {"pages": [], "runAt": None})
    if latest is None:
        if not STATE_ONLY:
            sys.exit("out/latest.json missing: run crawl.py first")
        latest = {"runAt": (pw.get("runAt") or datetime.utcnow().isoformat(timespec="seconds")).replace("Z", "+00:00"), "competitors": {}}
    amap = jload(OUT / "asset_map.json", {})
    run_at = latest["runAt"]
    run_id = run_at[:16].replace(":", "").replace("T", "-")
    run_date = run_at[:10]
    created = int(datetime.fromisoformat(run_at).timestamp() * 1000)
    writes = []

    def put(col, doc_id, data):
        writes.append({"op": "set", "collection": col, "doc_id": doc_id, "data": data})

    # --- page states: attach freshly uploaded screenshot URLs before storing memory ---
    pages_now = {p["id"]: p for p in pw["pages"]}
    for pid, url in amap.items():
        sp = PAGES_STATE / f"{pid}.json"
        if sp.exists():
            s = json.loads(sp.read_text()); s["shotUrl"] = url; sp.write_text(json.dumps(s))
    def shot(pid):
        if pid in amap:
            return amap[pid]
        s = jload(PAGES_STATE / f"{pid}.json", {})
        return s.get("shotUrl")

    # --- 1. crawler memory (write-once) + delete last run's memory ---
    for f in sorted(SNAP.glob("*.hashes")):
        hs = f.read_text().split()
        parts = max(1, -(-len(hs) // SHARD))
        for i in range(parts):
            put("crawlstate", f"snap-{run_id}-{f.stem}-{i}", {"kind": "snap", "key": f.stem, "runId": run_id, "part": i,
                                                                "parts": parts, "payload": "\n".join(hs[i*SHARD:(i+1)*SHARD])})
    put("crawlstate", f"feeds-{run_id}", {"kind": "feeds", "key": "", "runId": run_id, "payload": jload(STATE / "feeds.json", {})})
    # page states bundled into ~200 KB docs so a weekly run sends a handful of writes, not one per page
    bundle, bsize, bn = {}, 0, 0
    files = sorted(PAGES_STATE.glob("*.json")) if PAGES_STATE.exists() else []
    for i, f in enumerate(files):
        body = f.read_text()
        if bundle and bsize + len(body) > 200_000:
            put("crawlstate", f"pages-{run_id}-{bn}", {"kind": "pagebundle", "key": str(bn), "runId": run_id, "payload": bundle})
            bundle, bsize, bn = {}, 0, bn + 1
        bundle[f.stem] = json.loads(body); bsize += len(body)
    if bundle:
        put("crawlstate", f"pages-{run_id}-{bn}", {"kind": "pagebundle", "key": str(bn), "runId": run_id, "payload": bundle})
    new_ids = {w["doc_id"] for w in writes}
    deletes = [{"op": "delete", "collection": "crawlstate", "doc_id": d, "if_version": 1}
               for d in jload(STATE / "db_index.json", []) if d not in new_ids]

    if STATE_ONLY:
        writes[:] = [w for w in writes if w["collection"] == "crawlstate"]
        return finish(writes, deletes)

    # --- 2. run summary ---
    comp = {}
    for cid, c in latest["competitors"].items():
        comp[cid] = {k: c.get(k) for k in ("name", "domain", "status", "urlCount", "addedCount", "removedCount", "byKind", "topSections", "note", "openJobs", "facetAdded")
                     if c.get(k) is not None}
        comp[cid]["feedCount"] = len(c.get("feeds") or [])
    own = {oid: {k: o.get(k) for k in ("name", "brand", "domain", "status", "urlCount", "byKind", "topSections")} for oid, o in latest.get("own", {}).items()}
    put("runs", run_id, {"runAt": run_at, "date": run_date, "competitors": comp, "own": own, "track": TRACK, "createdAt": created})

    # --- 3. gap counts ---
    sites = []
    for cid, c in latest["competitors"].items():
        if c.get("gaps") is not None:
            sites.append({"id": cid, "name": c["name"], "own": False, "brand": BRAND.get(cid, ""), "urlCount": c.get("urlCount", 0),
                          "counts": c["gaps"], "examples": c.get("gapExamples", {})})
    for oid, o in latest.get("own", {}).items():
        sites.append({"id": oid, "name": o["name"], "own": True, "brand": o["brand"], "urlCount": o.get("urlCount", 0),
                      "counts": o.get("gaps", {}), "examples": o.get("gapExamples", {})})
    put("gaps", run_id, {"date": run_date, "types": latest.get("gapTypes", []), "sites": sites, "track": TRACK, "createdAt": created})

    # --- 4. key-page board + changes + offers spotted ---
    board = []
    for p in pw["pages"]:
        board.append({k: p.get(k) for k in ("id", "competitorId", "competitorName", "label", "url", "status", "title", "h1", "banners",
                                             "nav", "offers", "tech", "changed", "baseline")} | {"shot": shot(p["id"]), "brand": BRAND.get(p["competitorId"], "")})
        if p.get("changed"):
            ch = p.get("changes", {})
            bits = []
            for k, label in (("offers", "offers"), ("banners", "banners"), ("h1", "headline"), ("nav", "navigation"), ("tech", "tech"), ("content", "careers listings")):
                if k in ch:
                    a, r = len(ch[k]["added"]), len(ch[k]["removed"])
                    bits.append(f"{label} +{a}/-{r}")
            if "title" in ch:
                bits.append("page title")
            put("pagechanges", did("pc", p["id"] + run_id), {
                "date": run_date, "pageId": p["id"], "competitorId": p["competitorId"], "competitorName": p["competitorName"],
                "brand": BRAND.get(p["competitorId"], ""), "label": p["label"], "url": p["url"], "summary": "Changed: " + ", ".join(bits),
                "changes": ch, "textChange": p.get("textChange"), "shot": shot(p["id"]), "prevShot": p.get("prevShotUrl"),
                "track": TRACK, "createdAt": created})
        # offers -> Signals: new offers on changed pages; on a page's first run, strong homepage offers only
        new_offers = (p.get("changes", {}).get("offers", {}).get("added", []) if p.get("changed")
                      else (p.get("offers", []) if p.get("baseline") and p["label"] == "Homepage" else []))
        new_offers += [b for b in (p.get("changes", {}).get("banners", {}).get("added", []) if p.get("changed") else (p.get("banners", []) if p.get("baseline") and p["label"] == "Homepage" else []))]
        strong = list(dict.fromkeys(o for o in new_offers if STRONG_OFFER.search(o)))[:3]
        if strong and p.get("status") == "ok":
            put("signals", did("sg", p["id"] + run_id), {
                "date": run_date, "competitorName": p["competitorName"], "brand": BRAND.get(p["competitorId"], "Proimprint"),
                "module": "Offer / coupon", "impact": 2, "owner": "", "status": "New", "auto": True,
                "summary": f"{p['label']} offer: " + " | ".join(strong), "action": "",
                "source": p["url"], "track": TRACK, "createdAt": created})
    if board:
        put("boards", run_id, {"date": run_date, "runAt": pw.get("runAt"), "pages": board, "track": TRACK, "createdAt": created})

    # --- 5. new pages, posts, headlines (skip anything already in the tracker) ---
    known = set(jload(STATE / "known_urls.json", []))
    for cid, c in latest["competitors"].items():
        if (c.get("facetAdded") or 0) >= 200:  # a bulk facet push is worth one line in the feed
            put("pages", did("p", cid + "facets" + run_id), {"url": f"https://{c['domain']}/", "competitorId": cid, "competitorName": c["name"],
                "title": f"Added {c['facetAdded']:,} filtered category URLs (brand/material/style filters) to its sitemap",
                "kind": "page", "section": "facet SEO", "date": run_date, "source": "sitemap", "track": TRACK, "createdAt": created})
        added = c.get("added") or []
        nonprod = [a for a in added if a["kind"] != "product"][:40]
        prods = [a for a in added if a["kind"] == "product"][:15]
        fetched = 0
        for a in nonprod + prods:
            if a["url"] in known:
                continue
            title = None
            if a["kind"] != "product" and fetched < 25:
                title = page_title(a["url"]); fetched += 1
            put("pages", did("p", a["url"] + run_id), {"url": a["url"], "title": title or slug_title(a["url"]), "competitorId": cid,
                "competitorName": c["name"], "kind": a["kind"], "section": a["section"], "date": run_date, "source": "sitemap",
                "track": TRACK, "createdAt": created})
    for p in latest.get("posts", []):
        if p["link"] in known:
            continue
        put("pages", did("p", p["link"] + run_id), {"url": p["link"], "title": p["title"], "competitorId": p["competitorId"],
            "competitorName": p["competitorName"], "kind": "post", "section": ", ".join(p.get("categories", [])[:3]),
            "date": p.get("date") or run_date, "source": "rss", "track": TRACK, "createdAt": created})
    for j in latest.get("jobs", []):
        if j["link"] in known:
            continue
        put("pages", did("p", j["link"] + run_id), {"url": j["link"], "title": j["title"], "competitorId": j["competitorId"],
            "competitorName": j["competitorName"], "kind": "job", "section": " · ".join(x for x in (j.get("team"), j.get("location")) if x),
            "date": run_date, "source": "jobs", "track": TRACK, "createdAt": created})
    for p in latest.get("industry", []):
        if p.get("error") or p["link"] in known:
            continue
        put("pages", did("p", p["link"] + run_id), {"url": p["link"], "title": p["title"], "competitorId": "", "competitorName": p["source"],
            "kind": "industry", "section": ", ".join(p.get("categories", [])[:3]), "date": p.get("date") or run_date,
            "source": "rss", "track": TRACK, "createdAt": created})

    finish(writes, deletes)


def finish(writes, deletes):
    """De-dupe, write one file per document, pack ArtifactData batches by count and size."""
    seen, uniq = set(), []
    for w in writes:
        k = (w["collection"], w["doc_id"])
        if k not in seen:
            seen.add(k); uniq.append(w)
    DOCS.mkdir(parents=True, exist_ok=True)
    for f in DOCS.glob("*.json"):
        f.unlink()
    batches, cur, size = [], [], 0
    for w in uniq:
        body = json.dumps(w["data"])
        if len(body) > 250_000:
            print(f"WARNING: {w['collection']}/{w['doc_id']} is {len(body)} bytes (limit 256 KiB)")
        p = DOCS / f"{w['collection']}__{w['doc_id']}.json"
        p.write_text(body)
        entry = {"op": "set", "collection": w["collection"], "doc_id": w["doc_id"], "file_path": str(p)}
        if cur and (len(cur) >= 50 or size + len(body) > BATCH_BYTES):
            batches.append(cur); cur, size = [], 0
        cur.append(entry); size += len(body)
    if cur:
        batches.append(cur)
    for i in range(0, len(deletes), 50):  # deletes go last, after the new memory is safely stored
        batches.append(deletes[i:i + 50])
    (OUT / "batches.json").write_text(json.dumps(batches, indent=1))
    cnt = {}
    for w in uniq:
        cnt[w["collection"]] = cnt.get(w["collection"], 0) + 1
    print(f"{len(uniq)} writes {cnt}, {len(deletes)} deletes, {len(batches)} batches -> out/batches.json")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "restore":
        restore(sys.argv[2])
    elif cmd == "uploads":
        uploads()
    elif cmd == "assetmap":
        # Paste the Artifact asset-upload result text into a file and pass it here:
        # lines look like  "/.../shots/pg-xxxx.jpg" (...) → "/_blob/<id>" (id <id>)
        txt = Path(sys.argv[2]).read_text()
        found = dict(re.findall(r'shots/(pg-[0-9a-f]+)\.jpg"[^\n]*?"(/_blob/[0-9a-f]+)"', txt))
        amap = jload(OUT / "asset_map.json", {})
        amap.update(found)
        (OUT / "asset_map.json").write_text(json.dumps(amap, indent=1))
        print(f"{len(found)} screenshot URLs added -> out/asset_map.json ({len(amap)} total)")
    elif cmd == "publish":
        STATE_ONLY = "--state-only" in sys.argv  # only refresh the crawler's memory (after a --warm run)
        publish()
    else:
        print(__doc__)
