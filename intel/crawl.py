#!/usr/bin/env python3
"""
Promo Intel crawler — competitor sitemap + feed monitor.

What it does (one run):
  1. For each competitor in config.json, collects every URL from its XML sitemaps
     (robots.txt discovery + configured sitemaps, nested sitemap indexes, .gz files).
  2. Compares against the previous snapshot in snapshots/<id>.txt.gz and records
     pages ADDED and REMOVED since the last run.
  3. Reads competitor blog RSS/Atom feeds and industry news feeds; reports items not seen before.
  4. Writes out/latest.json (what changed this run) and appends out/history.csv (URL counts over time).

The Promo Intel Desk artifact is updated from out/latest.json by a Claude scheduled task
(see README.md). Standard library only — no pip installs needed.

Usage:  python3 intel/crawl.py [--only id1,id2] [--no-feeds]
"""
import argparse, csv, gzip, io, json, re, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
SNAP_DIR, STATE_DIR, OUT_DIR = ROOT / "snapshots", ROOT / "state", ROOT / "out"
for d in (SNAP_DIR, STATE_DIR, OUT_DIR):
    d.mkdir(exist_ok=True)

CFG = json.loads((ROOT / "config.json").read_text())
UA = CFG["user_agent"]
LIM = CFG["limits"]
NOW = datetime.now(timezone.utc)


# ---------- HTTP ----------
def fetch(url, timeout=40):
    """GET a URL; returns (status, final_url, bytes). Never raises."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                try:
                    data = gzip.decompress(data)
                except OSError:
                    pass
            return r.status, r.geturl(), data
    except urllib.error.HTTPError as e:
        return e.code, url, b""
    except Exception as e:  # DNS, timeout, proxy refusal
        return 0, url, str(e).encode()
    finally:
        time.sleep(LIM["delay_seconds"])  # be polite


def local(tag):
    return tag.rsplit("}", 1)[-1]


# ---------- Sitemaps ----------
def robots_sitemaps(domain):
    st, _, body = fetch(f"https://{domain}/robots.txt")
    if st != 200:
        return []
    return [l.split(":", 1)[1].strip() for l in body.decode("utf-8", "ignore").splitlines()
            if l.lower().startswith("sitemap:")]


def crawl_sitemaps(seeds):
    """Breadth-first over sitemap indexes. Returns ({url: lastmod}, files_read, errors)."""
    urls, seen, queue, errors, files = {}, set(), list(dict.fromkeys(seeds)), [], 0
    while queue and files < LIM["max_sitemap_files"] and len(urls) < LIM["max_urls"]:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        st, final, body = fetch(sm)
        files += 1
        if st != 200 or not body.strip().startswith((b"<", b"\xef\xbb\xbf<")):
            errors.append(f"{sm} -> HTTP {st}")
            continue
        try:
            root = ET.fromstring(body.lstrip(b"\xef\xbb\xbf"))
        except ET.ParseError as e:
            errors.append(f"{sm} -> XML error {e}")
            continue
        kind = local(root.tag)
        for node in root:
            loc = lastmod = None
            for ch in node:
                t = local(ch.tag)
                if t == "loc" and ch.text:
                    loc = ch.text.strip()
                elif t == "lastmod" and ch.text:
                    lastmod = ch.text.strip()[:10]
            if not loc:
                continue
            if kind == "sitemapindex":
                queue.append(loc)
            else:
                urls[loc] = lastmod or ""
    if queue:
        errors.append(f"stopped early: {len(queue)} sitemap files not read (limit {LIM['max_sitemap_files']})")
    return urls, files, errors


def load_snapshot(cid):
    p = SNAP_DIR / f"{cid}.txt.gz"
    if not p.exists():
        return None
    out = {}
    for line in gzip.decompress(p.read_bytes()).decode().splitlines():
        u, _, lm = line.partition("\t")
        out[u] = lm
    return out


def save_snapshot(cid, urls):
    body = "\n".join(f"{u}\t{urls[u]}" for u in sorted(urls)).encode()
    # mtime=0 keeps the gzip byte-identical when nothing changed (clean git diffs)
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as g:
        g.write(body)
    (SNAP_DIR / f"{cid}.txt.gz").write_bytes(buf.getvalue())


CONTENT_HINTS = ("blog", "learn", "ideas", "guide", "resources", "education", "inspiration", "news", "write", "articles", "insights")
PRODUCT_HINTS = ("/p/", "/product", "/products/", "/item/", "/sku", "-p-")


def classify(url):
    """Rough page type from the URL path, so 50 new product pages don't drown 1 new landing page."""
    path = urlparse(url).path.lower()
    seg = path.strip("/").split("/")[0] if path.strip("/") else "(home)"
    if any(h in path for h in CONTENT_HINTS):
        kind = "content"
    elif any(h in path for h in PRODUCT_HINTS) or re.search(r"/\d{4,}", path):
        kind = "product"
    else:
        kind = "page"
    return kind, seg


def summarize(urls):
    by = {}
    for u in urls:
        k, _ = classify(u)
        by[k] = by.get(k, 0) + 1
    return by


def top_sections(urls, n=15):
    """Biggest URL sections (first path segment) — a map of where a competitor invests in pages."""
    by = {}
    for u in urls:
        s = classify(u)[1]
        by[s] = by.get(s, 0) + 1
    return dict(sorted(by.items(), key=lambda kv: -kv[1])[:n])


def recent_by_lastmod(urls, days):
    """Pages whose sitemap lastmod is within N days. Ignored when the site stamps everything with one date."""
    dates = [d for d in urls.values() if d]
    if not dates:
        return []
    top = max(set(dates), key=dates.count)
    if dates.count(top) > 0.5 * len(dates):  # site sets same lastmod on most pages -> meaningless
        return []
    cut = (NOW - timedelta(days=days)).date().isoformat()
    return sorted([(d, u) for u, d in urls.items() if d and d >= cut], reverse=True)


# ---------- Feeds ----------
class FeedLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.feeds = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and (a.get("rel") or "").lower() == "alternate" and \
                (a.get("type") or "").lower() in ("application/rss+xml", "application/atom+xml") and a.get("href"):
            self.feeds.append(a["href"])


def discover_feeds(page):
    st, final, body = fetch(page)
    if st != 200:
        return []
    p = FeedLinkParser()
    try:
        p.feed(body.decode("utf-8", "ignore"))
    except Exception:
        return []
    # skip comment feeds
    return [urljoin(final, f) for f in p.feeds if "comments" not in f.lower()]


def parse_date(s):
    if not s:
        return ""
    s = s.strip()
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"\d{4}-\d{2}-\d{2}", s)
    return m.group(0) if m else ""


def read_feed(url):
    st, _, body = fetch(url)
    if st != 200:
        return None, f"HTTP {st}"
    try:
        root = ET.fromstring(body.lstrip(b"\xef\xbb\xbf"))
    except ET.ParseError as e:
        return None, f"XML error {e}"
    items = []
    for it in root.iter():
        if local(it.tag) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "date": "", "categories": []}
        for ch in it:
            t = local(ch.tag)
            if t == "title":
                rec["title"] = (ch.text or "").strip()
            elif t == "link":
                rec["link"] = (ch.text or ch.get("href") or "").strip() or rec["link"]
            elif t in ("pubDate", "published", "updated", "date") and not rec["date"]:
                rec["date"] = parse_date(ch.text)
            elif t == "category":
                c = (ch.text or ch.get("term") or "").strip()
                if c:
                    rec["categories"].append(c)
        if rec["link"]:
            items.append(rec)
    return items, None


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated competitor ids")
    ap.add_argument("--no-feeds", action="store_true")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    feed_state_p = STATE_DIR / "feeds.json"
    feed_state = json.loads(feed_state_p.read_text()) if feed_state_p.exists() else {}

    result = {"runAt": NOW.isoformat(timespec="seconds"), "competitors": {}, "posts": [], "industry": []}
    hist_rows = []

    for c in CFG["competitors"]:
        cid = c["id"]
        if only and cid not in only:
            continue
        rec = {"name": c["name"], "domain": c["domain"]}
        if c.get("blocked"):
            rec["status"] = "blocked"
            result["competitors"][cid] = rec
            print(f"[skip] {cid}: blocks automated requests")
            continue

        seeds = list(c.get("sitemaps", []))
        if c.get("robots", True):
            seeds += robots_sitemaps(c["domain"])
        urls, files, errors = crawl_sitemaps(seeds)
        # optional path filter, e.g. National Pen lists 15 countries; we only care about /us/
        if c.get("include"):
            urls = {u: lm for u, lm in urls.items() if any(p in urlparse(u).path for p in c["include"])}
        prev = load_snapshot(cid)
        rec.update({"sitemapSeeds": seeds, "sitemapFiles": files, "urlCount": len(urls), "errors": errors[:10],
                    "byKind": summarize(urls), "topSections": top_sections(urls)})

        if not urls:
            rec["status"] = "error"
            print(f"[err ] {cid}: no URLs ({'; '.join(errors[:3])})")
        else:
            rec["status"] = "baseline" if prev is None else "ok"
            if prev is not None:
                added = sorted(set(urls) - set(prev))
                removed = sorted(set(prev) - set(urls))
                # guard: a partial crawl looks like mass removal — don't report it as real
                if len(urls) < 0.6 * len(prev):
                    rec["status"] = "partial"
                    rec["note"] = f"Only {len(urls)} URLs vs {len(prev)} last run; snapshot kept, diff skipped."
                    added, removed = [], []
                else:
                    save_snapshot(cid, urls)
                rec["addedCount"], rec["removedCount"] = len(added), len(removed)
                rec["added"] = [{"url": u, "kind": classify(u)[0], "section": classify(u)[1]} for u in added[:LIM["max_added_reported"]]]
                rec["removedSample"] = removed[:40]
            else:
                save_snapshot(cid, urls)
                rec["addedCount"] = rec["removedCount"] = 0
            rec["recentLastmod"] = [{"date": d, "url": u, "kind": classify(u)[0]}
                                    for d, u in recent_by_lastmod(urls, LIM["recent_days"])[:60]]
            hist_rows.append([NOW.date().isoformat(), cid, len(urls), rec.get("addedCount", 0), rec.get("removedCount", 0)])
            print(f"[ok  ] {cid}: {len(urls)} urls from {files} files, +{rec.get('addedCount',0)} -{rec.get('removedCount',0)} ({rec['status']})")

        # competitor content feeds
        if not args.no_feeds:
            feeds = list(c.get("feeds", []))
            for page in c.get("discover", []):
                feeds += discover_feeds(page)
            feeds = list(dict.fromkeys(feeds))
            rec["feeds"] = feeds
            for f in feeds:
                items, err = read_feed(f)
                if err:
                    rec.setdefault("feedErrors", []).append(f"{f} -> {err}")
                    continue
                seen = set(feed_state.get(f, []))
                first_time = f not in feed_state
                for it in items:
                    if it["link"] in seen:
                        continue
                    # first read of a feed: keep only the last 60 days so the tracker isn't flooded
                    if first_time and it["date"] and it["date"] < (NOW - timedelta(days=60)).date().isoformat():
                        continue
                    result["posts"].append({"competitorId": cid, "competitorName": c["name"], **it})
                feed_state[f] = sorted(seen | {i["link"] for i in items})[-500:]
        result["competitors"][cid] = rec

    if not args.no_feeds and not only:
        for f in CFG.get("industry_feeds", []):
            items, err = read_feed(f["url"])
            if err:
                result["industry"].append({"source": f["name"], "error": err})
                continue
            seen = set(feed_state.get(f["url"], []))
            first_time = f["url"] not in feed_state
            for it in items:
                if it["link"] in seen:
                    continue
                if first_time and it["date"] and it["date"] < (NOW - timedelta(days=21)).date().isoformat():
                    continue
                result["industry"].append({"source": f["name"], **it})
            feed_state[f["url"]] = sorted(seen | {i["link"] for i in items})[-500:]

    feed_state_p.write_text(json.dumps(feed_state, indent=1, sort_keys=True))
    (OUT_DIR / "latest.json").write_text(json.dumps(result, indent=1))
    hist_p = OUT_DIR / "history.csv"
    new_file = not hist_p.exists()
    with hist_p.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["date", "competitor", "urls", "added", "removed"])
        w.writerows(hist_rows)
    print(f"\nposts: {len(result['posts'])}  industry: {len(result['industry'])}  -> {OUT_DIR/'latest.json'}")


if __name__ == "__main__":
    sys.exit(main())
