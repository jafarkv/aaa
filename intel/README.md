# Promo Intel: competitor watch

Feeds the **Promo Intel Desk** tracker (https://claude.ai/artifact/U6ZMtD9W6HN9tJ8AZuGboa).

The tracker's own database holds this code and the crawler's memory, so a weekly Claude task runs without a git repo. Nothing here needs API keys.

## What runs each week

| Step | Script | What it does |
|---|---|---|
| 1 | `state.py restore <export>` | Rebuilds the crawler's memory from the tracker database: sitemap snapshots, seen feed items and key-page states |
| 2 | `crawl.py` | Reads every competitor sitemap and diffs it against last week. Also reads blog/industry RSS, public job boards and your 6 brand sites, and counts page types for the gap finder |
| 3 | `pagewatch.js` | Opens each competitor homepage and key pages in Chromium. Records screenshot, offers, banners, navigation, headline and tech stack, and diffs them against last week |
| 4 | `state.py uploads` → upload → `state.py assetmap` | Uploads screenshots for changed pages (and first sightings) to the tracker |
| 5 | `state.py publish` | Writes `out/batches.json`: the new crawler memory, the run summary, gaps, the page board, page changes, new pages/posts/jobs and offer signals. Deletes last week's memory |

## Tracker collections

| Collection | Contents | Written |
|---|---|---|
| `runs` | Pages per competitor and the change since last run | Weekly, one doc |
| `gaps` | Page-type counts per site, ours vs competitors | Weekly, one doc |
| `boards` | Current state of every watched key page | Weekly, one doc |
| `pagechanges` | One doc per key page that changed | Weekly |
| `pages` | New pages from sitemaps, blog posts, job postings, industry headlines | Weekly |
| `signals` | Offers spotted on competitor pages (`auto: true`) | Weekly |
| `feed` | Launch entries with a "For us" note (team or Claude) | Any time |
| `crawlstate` | Crawler memory. Editors read, only the owner writes | Weekly, replaced |
| `system` | This code. Editors read, only the owner writes | When code changes |

Every weekly document is write-once (version 1). A run never edits an existing doc, so no version bookkeeping is needed.

## Noise controls (learned the hard way)

- **Flickering items:** an item is "new" only if it hasn't been seen in the last 8 weeks, and "removed" only after it has been missing 2 runs in a row. A new tech tool has to show up 2 runs in a row before it's reported.
- **Removals alone:** they never flag a page as changed. Only additions do (new offer, banner, headline, nav item, tool, job).
- **Countdown timers** ("ends in 4 hours 52 minutes") are masked. Day counts ("4 day turnaround") are kept, because those changes matter.
- **Bare price tiles** ("as low as $7.89") and staff testimonials ("Jon with 4imprint 15 years") are ignored.
- **Filter/facet URLs** (`?brand[]=…`) are counted, not listed. Custom Ink added 95k of them in one weekend.
- **Partial crawls:** if a crawl returns under 60% of last week's URLs, it's treated as partial and no diff is recorded.
- **`--warm`:** `node pagewatch.js --warm` learns rotating content without reporting anything. Use it after adding a key page.

## Add a competitor or key page

1. In the tracker's Competitors tab, add the competitor. Note its document id.
2. Add it to `config.json` with the same `id`:
   ```json
   { "id": "newco", "name": "NewCo", "domain": "www.newco.com", "brand": "Proimprint", "robots": true,
     "discover": ["https://www.newco.com/blog"], "keypages": [["Deals", "https://www.newco.com/sale"]] }
   ```
   `jobs` takes `{"ashby": "<board>"}`, `{"greenhouse": "<board>"}` or `{"lever": "<company>"}`.
3. Store the new code in the tracker. The weekly task always runs the newest `system` doc.

The Promo Intel cloud environment has open network access, so no host changes are needed.

## Known limits

- **Sites that block bots:** EverythingBranded, Oriental Trading and Totally Promotional block automated browsers (Cloudflare). Their sitemaps still work except EverythingBranded and Oriental Trading. Track their pages with the tracker's research links. Nothing here tries to get around a block.
- **Ads, traffic, reviews:** these are one-click research links (Meta Ad Library, Google Ads Transparency, Similarweb, BuiltWith, Trustpilot). Those services don't allow automated access without paid APIs.
- **Job boards:** only Sticker Mule publishes jobs on a public board. Custom Ink, Vistaprint and BuildASign are watched through their careers pages.
