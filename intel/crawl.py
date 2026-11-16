#!/usr/bin/env python3
"""
Promo Intel crawler — competitor sitemap + feed monitor, plus the content-gap counts.

One run:
  1. Collects every URL from each competitor's XML sitemaps (robots.txt discovery,
     configured sitemaps, nested indexes, .gz files) and from our own brand sites.
  2. Compares competitor URLs with the previous snapshot (snapshots/<id>.hashes — a sorted
     list of 12-char URL hashes) and records pages ADDED and the count REMOVED.
  3. Reads competitor blog feeds and industry feeds; reports items not seen before.
  4. Counts page types (industry pages, FAQs, guides, deals...) on every site for the gap finder.
  5. Writes out/latest.json and appends out/history.csv.

Snapshots and feed state are restored from / saved to the tracker database by state.py,
so the crawler keeps its memory without a git repo. Standard library only.

Usage:  python3 crawl.py [--only id1,id2] [--no-feeds]
"""
import argparse, csv, gzip, hashlib, json, re, sys, time, urllib.request, urllib.error
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


def h(url):
    """Short stable URL hash used in snapshots (collision odds are negligible at this scale)."""
    return hashlib.sha1(url.encode()).hexdigest()[:12]


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
    """Previous URL hashes for a site, or None on the first run."""
    p = SNAP_DIR / f"{cid}.hashes"
    if p.exists():
        return set(p.read_text().split())
    legacy = SNAP_DIR / f"{cid}.txt.gz"  # first version stored full URLs
    if legacy.exists():
        return {h(l.split("\t")[0]) for l in gzip.decompress(legacy.read_bytes()).decode().splitlines() if l}
    return None


def save_snapshot(cid, urls):
    (SNAP_DIR / f"{cid}.hashes").write_text("\n".join(sorted(h(u) for u in urls)))
    legacy = SNAP_DIR / f"{cid}.txt.gz"
    if legacy.exists():
        legacy.unlink()


CONTENT_HINTS = ("blog", "learn", "ideas", "guide", "resources", "education", "inspiration", "news", "write", "articles", "insights")
PRODUCT_HINTS = ("/p/", "/product", "/products/", "/item/", "/sku", "-p-")


def classify(url):
    """Rough page type from the URL path, so 50 new product pages don't drown 1 new landing page."""
    path = urlparse(url).path.lower()
    seg = path.strip("/").split("/")[0] if path.strip("/") else "(home)"
    if any(x in path for x in CONTENT_HINTS):
        kind = "content"
    elif any(x in path for x in PRODUCT_HINTS) or re.search(r"/\d{4,}", path):
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
    """Biggest URL sections (first path segment) — a map of where a site invests in pages."""
    by = {}
    for u in urls:
        s = classify(u)[1]
        by[s] = by.get(s, 0) + 1
    return dict(sorted(by.items(), key=lambda kv: -kv[1])[:n])


# ---------- Gap finder taxonomy ----------
# Page types that drive conversion or search demand. Matching is whole-word, and (except for
# guides/FAQ/proof, which are judged by their folder) only counts landing-style pages: short
# slugs that aren't products or blog posts — so a product called "Tech-Support-Earbuds" is not an FAQ.
L = r"(?<![a-z])"   # left word boundary inside a URL path
R = r"(?![a-z])"    # right word boundary
GAP_TYPES = [
    ("industry", "Industry pages", L + r"(industr|healthcare|medical|dental|dentist|real-?estate|realtor|law-?firm|attorney|legal|veterinar|construction|contractor|automotive|auto-?repair|dealership|restaurant|schools?" + R + r"|teacher|nonprofit|non-profit|church|hospital|nurs(e|es|ing)" + R + r"|pharma|banking|financial|insurance|fitness|gyms?" + R + r"|salon|government|military|police|firefight|hotel|hospitality|university|college|for-it-)"),
    ("occasion", "Events and occasions", L + r"(trade-?shows?|events?" + R + r"|conferences?|holidays?|christmas|graduation|back-to-school|weddings?|awards?" + R + r"|appreciation|anniversar|onboarding|new-?hire|employee|years?-?of-?service|recognition|fundrais|giveaways?|team-?building|thank-?you|halloween|valentine|mothers-?day|fathers-?day|awareness)"),
    ("guide", "Buying guides and blog", None),
    ("faq", "FAQ and help", None),
    ("proof", "Case studies and reviews", None),
    ("deals", "Deals and clearance", L + r"(sale|sales|deals?|clearance|discounts?|coupons?|specials?|closeouts?|price-?drops?|promo-?codes?|outlet)" + R),
    ("speed", "Rush and fast turnaround", L + r"(rush|24-?hours?|next-?day|quick-?ship|same-?day|fast-?turn|fast-?ship)" + R),
    ("price", "Price-point pages", L + r"((under|below|less-than)-?\$?\d+|\d+-dollars?|cheap|budget|low-?cost|bulk|wholesale|gifts?-\d+-to-\d+)" + R),
    ("eco", "Eco and made in USA", L + r"(eco|eco-?friendly|sustainab\w*|recycl\w*|organic|bamboo|usa-?made|made-in-(the-)?usa|american-?made)" + R),
    ("stores", "Company stores, kits, gifting", L + r"(company-?stores?|swag-?packs?|kits?|swag-?box(es)?|gift-?box(es)?|bundles?|redeem|gifting|corporate-?gifts?|distribution|fulfillment)" + R),
    ("design", "Design tools and templates", L + r"(templates?|design-?(tool|lab|studio|ideas|online)s?|logo-?maker|mockups?|online-?designer)" + R),
    ("samples", "Free samples", L + r"(free-?samples?|samples?-?request|request-?a-?sample)" + R),
    ("brands", "Retail brand pages", L + r"(brands?|yeti|nike|stanley|north-?face|carhartt|ogio|patagonia|under-?armour|adidas|igloo|hydro-?flask|camelbak|moleskine|swiss-?gear|callaway|titleist|columbia|otterbox|cutter-?buck|eddie-?bauer|travismathew|peter-?millar)" + R),
]
# folder-based types: the folder name says what the page is
FOLDER_RX = {
    "guide": re.compile(L + r"(blog|learn|guides?|ideas|resources|articles?|insights|write|hub|printing-101|how-to|education|inspiration|news)" + R),
    "faq": re.compile(L + r"(faqs?|help|help-?center|support|questions)" + R),
    "proof": re.compile(L + r"(case-?stud\w*|customer-?stor\w*|success-?stor\w*|testimonials?|reviews?|past-?work|portfolio)" + R),
}
GAP_RX = [(k, label, re.compile(rx) if rx else None) for k, label, rx in GAP_TYPES]


def gap_counts(urls):
    counts, examples = {}, {}

    def hit(k, u):
        counts[k] = counts.get(k, 0) + 1
        ex = examples.setdefault(k, [])
        if len(ex) < 3:
            ex.append(u)

    for u in urls:
        path = urlparse(u).path.lower().rstrip("/")
        segs = [s for s in path.split("/") if s]
        folders = "/" + "/".join(segs[:-1]) + "/" if len(segs) > 1 else "/"
        last = segs[-1] if segs else ""
        last_tokens = [t for t in re.split(r"[-_.]+", re.sub(r"\.(html?|aspx|php|htm)$", "", last)) if t]
        is_content = bool(FOLDER_RX["guide"].search(folders)) or bool(FOLDER_RX["guide"].fullmatch(last or "-"))
        # folder-judged types
        for k, rx in FOLDER_RX.items():
            if rx.search(folders) or (rx.fullmatch(last or "-")):
                hit(k, u)
        if is_content or classify(u)[0] == "product" or len(last_tokens) > 5 or not segs:
            continue  # only landing-style pages below
        for k, _, rx in GAP_RX:
            if rx is not None and rx.search(path):
                hit(k, u)
    return counts, examples


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


def new_feed_items(url, feed_state, window_days):
    """Items not seen before. On a feed's first read, only the last N days are reported."""
    items, err = read_feed(url)
    if err:
        return None, err
    seen = set(feed_state.get(url, []))
    first_time = url not in feed_state
    cut = (NOW - timedelta(days=window_days)).date().isoformat()
    fresh = [it for it in items if h(it["link"]) not in seen and not (first_time and it["date"] and it["date"] < cut)]
    feed_state[url] = sorted(seen | {h(i["link"]) for i in items})[-400:]
    return fresh, None


# ---------- Jobs (public job boards) ----------
def read_jobs(spec):
    """Open roles from a public job-board API. Returns [{title, link, team, location}] or None."""
    if spec.get("ashby"):
        st, _, body = fetch(f"https://api.ashbyhq.com/posting-api/job-board/{spec['ashby']}")
        if st != 200:
            return None
        return [{"title": j.get("title", ""), "link": j.get("jobUrl") or j.get("applyUrl", ""), "team": j.get("department") or j.get("team") or "",
                 "location": j.get("location", "")} for j in json.loads(body).get("jobs", [])]
    if spec.get("greenhouse"):
        st, _, body = fetch(f"https://boards-api.greenhouse.io/v1/boards/{spec['greenhouse']}/jobs")
        if st != 200:
            return None
        return [{"title": j.get("title", ""), "link": j.get("absolute_url", ""), "team": "", "location": (j.get("location") or {}).get("name", "")}
                for j in json.loads(body).get("jobs", [])]
    if spec.get("lever"):
        st, _, body = fetch(f"https://api.lever.co/v0/postings/{spec['lever']}?mode=json")
        if st != 200:
            return None
        return [{"title": j.get("text", ""), "link": j.get("hostedUrl", ""), "team": (j.get("categories") or {}).get("team", ""),
                 "location": (j.get("categories") or {}).get("location", "")} for j in json.loads(body)]
    return None


# ---------- Main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma-separated site ids")
    ap.add_argument("--no-feeds", action="store_true")
    args = ap.parse_args()
    only = set(args.only.split(",")) if args.only else None

    feed_state_p = STATE_DIR / "feeds.json"
    feed_state = json.loads(feed_state_p.read_text()) if feed_state_p.exists() else {}
    # older state stored full links; convert to hashes
    feed_state = {k: [x if re.fullmatch(r"[0-9a-f]{12}", x) else h(x) for x in v] for k, v in feed_state.items()}

    result = {"runAt": NOW.isoformat(timespec="seconds"), "competitors": {}, "own": {}, "posts": [], "industry": [], "jobs": [],
              "gapTypes": [{"key": k, "label": label} for k, label, _ in GAP_TYPES]}
    hist_rows = []

    for c in CFG["competitors"]:
        cid = c["id"]
        if only and cid not in only:
            continue
        rec = {"name": c["name"], "domain": c["domain"]}
        if c.get("blocked") or c.get("paused"):
            rec["status"] = "blocked" if c.get("blocked") else "paused"
            result["competitors"][cid] = rec
            print(f"[skip] {cid}: {rec['status']}")
            continue

        seeds = list(c.get("sitemaps", []))
        if c.get("robots", True):
            seeds += robots_sitemaps(c["domain"])
        urls, files, errors = crawl_sitemaps(seeds)
        if c.get("include"):
            urls = {u: lm for u, lm in urls.items() if any(p in urlparse(u).path for p in c["include"])}
        prev = load_snapshot(cid)
        gc, gx = gap_counts(urls)
        rec.update({"sitemapFiles": files, "urlCount": len(urls), "errors": errors[:10],
                    "byKind": summarize(urls), "topSections": top_sections(urls), "gaps": gc, "gapExamples": gx})

        if not urls:
            rec["status"] = "error"
            print(f"[err ] {cid}: no URLs ({'; '.join(errors[:3])})")
        else:
            rec["status"] = "baseline" if prev is None else "ok"
            added, removed_n = [], 0
            if prev is not None:
                cur = {h(u) for u in urls}
                if len(urls) < 0.6 * len(prev):
                    # a partial crawl looks like mass removal — keep the old snapshot, skip the diff
                    rec["status"] = "partial"
                    rec["note"] = f"Only {len(urls)} URLs vs {len(prev)} last run; snapshot kept, diff skipped."
                else:
                    added_all = sorted(u for u in urls if h(u) not in prev)
                    # filter/facet URLs (?brand[]=...) are counted, not listed — one competitor can add 90k at once
                    added = [u for u in added_all if "?" not in u]
                    rec["facetAdded"] = len(added_all) - len(added)
                    removed_n = len(prev - cur)
                    save_snapshot(cid, urls)
            else:
                save_snapshot(cid, urls)
            rec["addedCount"], rec["removedCount"] = len(added), removed_n
            rec["added"] = [{"url": u, "kind": classify(u)[0], "section": classify(u)[1]} for u in added[:LIM["max_added_reported"]]]
            hist_rows.append([NOW.date().isoformat(), cid, len(urls), len(added), removed_n])
            print(f"[ok  ] {cid}: {len(urls)} urls from {files} files, +{len(added)} -{removed_n} ({rec['status']})")

        if not args.no_feeds:
            feeds = list(c.get("feeds", []))
            for page in c.get("discover", []):
                feeds += discover_feeds(page)
            feeds = list(dict.fromkeys(feeds))
            rec["feeds"] = feeds
            for f in feeds:
                fresh, err = new_feed_items(f, feed_state, 60)
                if err:
                    rec.setdefault("feedErrors", []).append(f"{f} -> {err}")
                    continue
                for it in fresh:
                    result["posts"].append({"competitorId": cid, "competitorName": c["name"], **it})
        # open roles: new postings since last run (first run reports all current openings)
        if c.get("jobs") and not args.no_feeds:
            jobs = read_jobs(c["jobs"])
            if jobs is not None:
                key = "jobs:" + json.dumps(c["jobs"], sort_keys=True)
                seen = set(feed_state.get(key, []))
                for j in jobs:
                    if j["link"] and h(j["link"]) not in seen:
                        result["jobs"].append({"competitorId": cid, "competitorName": c["name"], **j})
                feed_state[key] = sorted(seen | {h(j["link"]) for j in jobs if j["link"]})[-400:]
                rec["openJobs"] = len(jobs)
        result["competitors"][cid] = rec

    # our own sites: only counted for the gap finder (no diff alerts)
    for o in CFG.get("own", []):
        if only and o["id"] not in only:
            continue
        seeds = list(o.get("sitemaps", []))
        if o.get("robots", True):
            seeds += robots_sitemaps(o["domain"])
        urls, files, errors = crawl_sitemaps(seeds)
        gc, gx = gap_counts(urls)
        result["own"][o["id"]] = {"name": o["name"], "brand": o["brand"], "domain": o["domain"], "urlCount": len(urls),
                                  "byKind": summarize(urls), "topSections": top_sections(urls), "gaps": gc, "gapExamples": gx,
                                  "status": "ok" if urls else "error", "errors": errors[:5]}
        print(f"[own ] {o['id']}: {len(urls)} urls")

    if not args.no_feeds and not only:
        for f in CFG.get("industry_feeds", []):
            fresh, err = new_feed_items(f["url"], feed_state, 21)
            if err:
                result["industry"].append({"source": f["name"], "error": err})
                continue
            for it in fresh:
                result["industry"].append({"source": f["name"], **it})

    feed_state_p.write_text(json.dumps(feed_state, indent=1, sort_keys=True))
    (OUT_DIR / "latest.json").write_text(json.dumps(result, indent=1))
    hist_p = OUT_DIR / "history.csv"
    new_file = not hist_p.exists()
    with hist_p.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new_file:
            w.writerow(["date", "competitor", "urls", "added", "removed"])
        w.writerows(hist_rows)
    print(f"\nposts: {len(result['posts'])}  industry: {len(result['industry'])}  jobs: {len(result['jobs'])}  -> {OUT_DIR/'latest.json'}")


if __name__ == "__main__":
    sys.exit(main())
