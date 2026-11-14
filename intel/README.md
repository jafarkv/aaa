# Promo Intel — competitor site watch

Feeds the **Promo Intel Desk** tracker (https://claude.ai/artifact/U6ZMtD9W6HN9tJ8AZuGboa).

The crawler reads each competitor's XML sitemaps and blog feeds every week, compares them with last week's copy, and reports:

- **New and removed pages:** landing pages, content pages and products, from the sitemap diff.
- **New blog posts:** from RSS/Atom feeds, found automatically from a blog page's `<link rel="alternate">`.
- **Industry headlines:** from the ASI, PPAI and Print+Promo Marketing feeds.
- **Where each competitor builds pages:** the top URL sections, a quick map of its content strategy.

Python standard library only. No API keys.

## Files

| Path | What it is |
|---|---|
| `config.json` | Watch list. Add a competitor here. |
| `crawl.py` | Fetches sitemaps and feeds, diffs them and writes `out/latest.json` + `out/history.csv` |
| `to_artifact.py` | Converts `out/latest.json` into ArtifactData batches (`out/artifact_batches_files.json`) |
| `snapshots/<id>.txt.gz` | Last known URL list per competitor. Committed, so the next run can diff. |
| `state/feeds.json` | Feed items already seen |
| `out/history.csv` | Pages per competitor over time. Shows when someone is scaling content. |
| `tracker/promo-intel-desk.html` | Source of the tracker page |

## Weekly run (what the scheduled task does)

```bash
python3 intel/crawl.py          # about 3–5 minutes for 14 sites, polite 0.4 s delay between requests
python3 intel/to_artifact.py    # builds the write batches
# Claude sends each batch in out/artifact_batches_files.json to the artifact with ArtifactData "batch",
# reviews new pages/posts and logs the important ones as Launch feed entries with a "For us" note,
# then commits snapshots/, state/ and out/ back to this branch.
```

## Add a competitor

1. Add an entry to `config.json`:
   ```json
   { "id": "newco", "name": "NewCo", "domain": "www.newco.com", "robots": true, "discover": ["https://www.newco.com/blog"] }
   ```
   `id` must match the competitor's document id in the tracker. Add them in the tracker's Competitors tab first. The id is the document id the tracker gives them, or ask Claude to add both.
2. Add the domain (and any sitemap or blog subdomain it redirects to) to the **Promo Intel** cloud environment's allowed hosts. Without it, requests are refused.
3. The first run saves a baseline. Changes are reported from the second run onward.

Options per competitor: `sitemaps` (explicit sitemap URLs), `robots` (also read `Sitemap:` lines in robots.txt), `feeds` (RSS URLs), `discover` (pages to scan for feed links), `include` (keep only URLs whose path contains one of these, e.g. `["/us/"]`), `blocked` (skip; track manually).

## Known limits

- **Sites that block bots:** EverythingBranded and Oriental Trading block automated requests (403). Track them with the tracker's research links. Nothing here tries to get around a block.
- **Pages missing from sitemaps:** a page that isn't in the sitemap won't be caught. Most big sites list everything.
- **Sitemap dates:** `lastmod` is ignored when a site stamps most pages with the same date, which is common.
- **Partial crawls:** if a crawl returns under 60% of last week's URLs, it's treated as partial. The diff is skipped so a server error doesn't show up as thousands of "removed" pages.
- **Ads, traffic and tech stack:** these come from one-click links in the tracker (Meta Ad Library, Google Ads Transparency, Similarweb, BuiltWith, Trustpilot, Wayback, LinkedIn Jobs). Those services don't allow automated fetching without paid APIs.
