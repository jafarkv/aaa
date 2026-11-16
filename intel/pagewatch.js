#!/usr/bin/env node
/**
 * Promo Intel page watch — weekly look at the pages that convert.
 *
 * For every competitor homepage + its configured key pages:
 *   - takes an above-the-fold screenshot (out/shots/<pageId>.jpg)
 *   - extracts title, meta description, H1s, promo banners, top navigation,
 *     offer lines (discounts, free shipping/setup, minimums, turnaround, codes)
 *   - fingerprints the tech stack from scripts and markup (testing, search, chat,
 *     reviews, payments, email/SMS, analytics, platform)
 *   - compares with last week's state (state/pages/<pageId>.json) and records what changed
 *
 * Output: out/pagewatch.json  {runAt, pages:[current state + changes]}
 * Uses the Playwright + Chromium preinstalled in the cloud container.
 * Usage: node pagewatch.js [--only competitorId,...]
 */
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { chromium } = require('playwright');

const ROOT = __dirname;
const CFG = JSON.parse(fs.readFileSync(path.join(ROOT, 'config.json'), 'utf8'));
const STATE = path.join(ROOT, 'state', 'pages');
const SHOTS = path.join(ROOT, 'out', 'shots');
fs.mkdirSync(STATE, { recursive: true });
fs.mkdirSync(SHOTS, { recursive: true });

const onlyArg = process.argv.indexOf('--only');
// --warm: learn rotating banners, carousel offers and tag-manager tools without reporting anything
const WARM = process.argv.includes('--warm');
const ONLY = onlyArg > -1 ? new Set(process.argv[onlyArg + 1].split(',')) : null;

// ---- Tech fingerprints: name -> regex tested against script URLs + HTML ----
const TECH = {
  'Google Tag Manager': /googletagmanager\.com\/gtm\.js/i, 'Google Analytics 4': /gtag\/js\?id=G-|google-analytics\.com\/g\/collect/i,
  'Optimizely': /optimizely\.com|cdn\.optimizely/i, 'VWO': /visualwebsiteoptimizer|vwo_code/i, 'AB Tasty': /abtasty/i,
  'Dynamic Yield': /dynamicyield|dy-api/i, 'Convert': /cdn-\d+\.convertexperiments/i, 'Kameleoon': /kameleoon/i,
  'Algolia': /algolia(net)?\.(com|net)|algoliasearch/i, 'Klevu': /klevu/i, 'Searchspring': /searchspring/i, 'Bloomreach': /bloomreach|brcdn|brsrvr/i,
  'Constructor.io': /constructor\.io|cnstrc/i, 'Coveo': /coveo/i,
  'Klaviyo': /klaviyo/i, 'Attentive': /attn\.tv|attentivemobile/i, 'Postscript': /postscript\.io/i, 'Listrak': /listrak|listrakbi/i,
  'Salesforce Marketing Cloud': /exacttarget|igodigital|marketingcloud/i, 'Braze': /braze\.com|appboy/i, 'Iterable': /iterable/i, 'Bluecore': /bluecore/i,
  'Intercom': /intercom(cdn)?\.(io|com)|widget\.intercom/i, 'Zendesk': /zdassets|zendesk/i, 'Drift': /drift\.com|js\.driftt/i, 'LivePerson': /liveperson|lpsnmedia/i,
  'Gorgias': /gorgias/i, 'Tidio': /tidio/i, 'LiveChat': /livechatinc/i, 'Olark': /olark/i, 'HubSpot': /hs-scripts|hubspot|hs-analytics/i, 'Ada': /ada\.support|ada-embed/i,
  'Salesforce Chat': /salesforceliveagent|embeddedservice/i,
  'Yotpo': /yotpo/i, 'Bazaarvoice': /bazaarvoice/i, 'PowerReviews': /powerreviews/i, 'Trustpilot': /trustpilot/i, 'Okendo': /okendo/i, 'Stamped': /stamped\.io/i,
  'Shopper Approved': /shopperapproved/i, 'Google Customer Reviews': /merchantwidget\.js|renderOptIn/i,
  'Affirm': /affirm\.com\/js|cdn1\.affirm/i, 'Klarna': /klarna/i, 'Afterpay': /afterpay|clearpay/i, 'PayPal': /paypal(objects)?\.com/i, 'Stripe': /js\.stripe\.com/i,
  'Braintree': /braintree/i, 'Shop Pay': /shop-pay|shopify-pay/i, 'Apple Pay': /apple-?pay/i, 'Google Pay': /pay\.google\.com|google-?pay/i, 'Amazon Pay': /amazonpay|payments-amazon/i,
  'Hotjar': /hotjar/i, 'FullStory': /fullstory/i, 'Microsoft Clarity': /clarity\.ms/i, 'Contentsquare': /contentsquare|cs-sdk/i, 'Quantum Metric': /quantummetric/i,
  'Segment': /segment\.(com|io)\/analytics|cdn\.segment/i, 'Heap': /heap(analytics)?\.(io|com)/i, 'Amplitude': /amplitude/i, 'Mixpanel': /mixpanel/i,
  'Meta Pixel': /connect\.facebook\.net|fbevents/i, 'TikTok Pixel': /analytics\.tiktok/i, 'LinkedIn Insight': /snap\.licdn|linkedin\.com\/px/i,
  'Pinterest Tag': /pintrk|s\.pinimg\.com\/ct/i, 'Microsoft Ads (UET)': /bat\.bing\.com/i, 'Criteo': /criteo/i, 'Google Ads': /googleadservices|googlesyndication|aw-\d+/i,
  'Shopify': /cdn\.shopify|myshopify/i, 'BigCommerce': /bigcommerce/i, 'Adobe Commerce (Magento)': /Magento_|mage\/cookies|\/static\/version\d+\/frontend|magento/i, 'Salesforce Commerce Cloud': /demandware/i,
  'WordPress': /wp-content|wp-includes/i, 'Next.js': /_next\/static/i, 'Nuxt': /_nuxt\//i, 'Gatsby': /gatsby/i,
  'Cloudflare': /cdn-cgi|cloudflare/i, 'Akamai': /akamai/i, 'OneTrust': /onetrust|cookielaw/i, 'Cookiebot': /cookiebot/i, 'Osano': /osano/i,
  'reCAPTCHA': /recaptcha/i, 'Accessibility widget (accessiBe/UserWay)': /accessibe|userway/i,
};

// Lines that look like an offer or a buying promise
const OFFER_RX = /(\d{1,2}\s?%\s?off|save\s+(up to\s+)?\$?\d+|\$\d+(\.\d\d)?\s+off|free\s+(shipping|setup|set-up|samples?|rush|delivery|design|proofs?|art|logo)|no\s+(minimums?|setup fees?)|low\s+minimums?|minimum(s)?\s+(of\s+)?\d+|as low as \$|lowest price|price match|use code|promo code|coupon|code:?\s*[A-Z0-9]{4,}|sale ends|ends (today|tonight|soon)|limited time|clearance|black friday|cyber monday|\d+[- ]day (production|turnaround|delivery)|ships? (in|within) \d+|24[- ]hour|next[- ]day|same[- ]day|rush|guarantee|in[- ]hands)/i;

// countdowns ("ends in 4 hours 52 minutes", "11:59:03") tick on every load; mask them so they don't read as new offers.
// Days are kept: "4 day turnaround" -> "3 day turnaround" is a real change.
const calm = (t) => String(t).replace(/\b\d+\s*(hours?|hrs?|minutes?|mins?|seconds?|secs?)\b/gi, '# $1').replace(/\b\d{1,2}:\d{2}(:\d{2})?\b/g, '#:#');
const sha = (s) => crypto.createHash('sha1').update(s).digest('hex').slice(0, 12);
const pageId = (url) => 'pg-' + sha(url);

function pagesToWatch() {
  const list = [];
  for (const c of CFG.competitors) {
    if (c.blocked || c.paused) continue;
    if (ONLY && !ONLY.has(c.id)) continue;
    const home = `https://${c.domain}/`;
    list.push({ competitorId: c.id, competitorName: c.name, label: 'Homepage', url: home });
    for (const [label, url] of c.keypages || []) list.push({ competitorId: c.id, competitorName: c.name, label, url });
  }
  return list;
}

async function extract(page) {
  return page.evaluate(() => {
    const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
    const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none'; };
    const uniq = (a) => [...new Set(a.filter(Boolean))];
    const title = clean(document.title);
    const meta = clean(document.querySelector('meta[name="description"]')?.content);
    const h1 = uniq([...document.querySelectorAll('h1')].filter(vis).map((e) => clean(e.innerText)).filter((t) => t.length < 160)).slice(0, 5);
    const h2 = uniq([...document.querySelectorAll('h2')].filter(vis).map((e) => clean(e.innerText)).filter((t) => t.length < 120)).slice(0, 12);
    // promo bars / announcement banners near the top of the page
    const bannerSel = '[class*="promo" i],[class*="banner" i],[class*="announcement" i],[class*="ribbon" i],[class*="topbar" i],[class*="top-bar" i],[class*="sitewide" i],[class*="marquee" i],[class*="notice" i],[id*="promo" i],[id*="banner" i],[id*="announcement" i]';
    const banners = uniq([...document.querySelectorAll(bannerSel)].filter((e) => vis(e) && e.getBoundingClientRect().top < 400)
      .map((e) => clean(e.innerText)).filter((t) => t.length > 8 && t.length < 220)).slice(0, 8);
    // top navigation labels — new sections show up here first
    const navRoot = document.querySelector('header nav, nav[role="navigation"], header, nav');
    const nav = navRoot ? uniq([...navRoot.querySelectorAll('a')].filter(vis).map((a) => clean(a.innerText)).filter((t) => t.length > 1 && t.length < 40)).slice(0, 40) : [];
    const lines = uniq(clean(document.body?.innerText || '').length ? (document.body.innerText || '').split('\n').map(clean).filter((t) => t.length > 3 && t.length < 220) : []).slice(0, 600);
    const scripts = [...document.scripts].map((s) => s.src).filter(Boolean);
    const html = document.documentElement.outerHTML.slice(0, 600000);
    return { title, meta, h1, h2, banners, nav, lines, scripts, html };
  });
}

function diffList(prev = [], cur = []) {
  const p = new Set(prev), c = new Set(cur);
  return { added: cur.filter((x) => !p.has(x)), removed: prev.filter((x) => !c.has(x)) };
}

(async () => {
  const runAt = new Date().toISOString().slice(0, 19) + 'Z';
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    viewport: { width: 1366, height: 900 }, deviceScaleFactor: 1,
    userAgent: CFG.user_agent.replace('PromoIntelBot', 'PromoIntelBot-Browser'), locale: 'en-US',
  });
  const results = [];
  for (const p of pagesToWatch()) {
    const id = pageId(p.url);
    const prevPath = path.join(STATE, id + '.json');
    const prev = fs.existsSync(prevPath) ? JSON.parse(fs.readFileSync(prevPath, 'utf8')) : null;
    const page = await ctx.newPage();
    const rec = { id, ...p, checkedAt: runAt, status: 'ok' };
    try {
      const resp = await page.goto(p.url, { waitUntil: 'domcontentloaded', timeout: 45000 });
      rec.httpStatus = resp ? resp.status() : 0;
      await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
      await page.mouse.wheel(0, 600).catch(() => {});
      await page.waitForTimeout(4000);
      await page.mouse.wheel(0, -600).catch(() => {});
      await page.waitForTimeout(800);
      const x = await extract(page);
      const blocked = rec.httpStatus >= 400 || x.lines.length < 5 || /access denied|are you a robot|verify you are human|attention required|request blocked/i.test(x.title + ' ' + x.lines.slice(0, 20).join(' '));
      if (blocked) { rec.status = 'blocked'; }
      const shot = path.join(SHOTS, id + '.jpg');
      await page.screenshot({ path: shot, type: 'jpeg', quality: 55, fullPage: false });
      rec.screenshot = shot;
      const techSrc = x.scripts.join('\n') + '\n' + x.html;
      rec.tech = Object.entries(TECH).filter(([, rx]) => rx.test(techSrc)).map(([n]) => n).sort();
      rec.title = x.title; rec.meta = x.meta; rec.h1 = x.h1; rec.h2 = x.h2; rec.banners = x.banners; rec.nav = x.nav;
      // countdowns ("ends in 4 hours 52 minutes", "11:59:03") tick every load; mask them so they don't read as new offers
      // rotating staff testimonials ("Jon with 4imprint 15 years") are not promotions
      rec.banners = [...new Set(x.banners.map(calm))].filter((b) => !/^[A-Z][\w.'-]+ with [\w .&'-]+ \d+ years?$/i.test(b));
      // bare product price tiles ("as low as $7.89 ea.") rotate with the products shown — not an offer
      const priceTile = /^(as low as|starting at|from)\s*\$[\d.,]+(\s*(ea\.?|each))?$/i;
      rec.offers = [...new Set(x.lines.filter((l) => OFFER_RX.test(l) && l.length < 160 && !priceTile.test(l.trim())).map(calm))].slice(0, 20);
      rec.textHash = sha(x.lines.join('\n'));
      rec.lineCount = x.lines.length;
      const linesForDiff = x.lines;

      // ---- compare with last week ----
      // memo[field][item] = weeks missing in a row (0 = seen this week). Tag managers, carousels and
      // A/B tests make items flicker between loads, so an item is "added" only if it was not seen in
      // recent weeks, and "removed" only after it has been missing two weeks running.
      const memo = JSON.parse(JSON.stringify(prev?.memo || {}));
      const flick = {};
      for (const k of ['h1', 'banners', 'nav', 'offers', 'tech']) {
        // stored items are normalised the same way, so older state compares cleanly
        const norm = (x) => (k === 'offers' || k === 'banners') ? calm(x) : x;
        const m = {};
        for (const [x, v] of Object.entries(memo[k] || (prev ? Object.fromEntries((prev[k] || []).map((y) => [y, 0])) : {}))) {
          const nx = norm(x); m[nx] = nx in m ? Math.min(m[nx], v) : v;
        }
        const cur = new Set(rec[k] || []);
        const added = [], removed = [];
        for (const x of cur) {
          if (!(x in m)) {
            // tech flickers most (tag managers): a new tool must show up two runs in a row (-1 = pending)
            if (k === 'tech' && !WARM) { m[x] = -1; } else { m[x] = 0; if (!WARM) added.push(x); }
          } else if (m[x] === -1) { m[x] = 0; added.push(x); }
        }
        for (const x of Object.keys(m)) {
          if (cur.has(x)) { if (m[x] > 0) m[x] = 0; continue; }
          if (m[x] === -1) { delete m[x]; continue; }  // pending tool did not come back: it was noise
          m[x] += 1;
          if (m[x] === 2 && !WARM) removed.push(x);
          if (m[x] >= 8) delete m[x];                  // forget after 8 weeks, so a return counts as new
        }
        memo[k] = m;
        flick[k] = { added, removed };
      }
      rec.memo = memo;
      if (prev && rec.status === 'ok') {
        const ch = {};
        // a page coming back from an error/challenge screen is a recovery, not a change
        const errPage = /error|could not be satisfied|access denied|just a moment|attention required|not found/i;
        if (prev.title !== rec.title && !errPage.test(prev.title || '')) ch.title = { from: prev.title, to: rec.title };
        if (prev.meta !== rec.meta && !errPage.test(prev.title || '')) ch.meta = { from: prev.meta, to: rec.meta };
        for (const k of ['h1', 'banners', 'nav', 'offers', 'tech']) {
          const d = flick[k];
          if (d.added.length || d.removed.length) ch[k] = d;
        }
        const td = diffList(prev.lines || [], linesForDiff);
        rec.textChange = { added: td.added.length, removed: td.removed.length, sampleAdded: td.added.filter((l) => l.length > 20).slice(0, 12) };
        // careers pages: new lines are usually new job titles, which is the signal we want
        if (/careers|jobs/i.test(p.label) && (td.added.length || td.removed.length)) {
          ch.content = { added: td.added.filter((l) => l.length > 6 && l.length < 120 && !/^(chat|apply|search|sign in|log in|view|learn more|see all)\b/i.test(l)).slice(0, 15), removed: td.removed.filter((l) => l.length > 6 && l.length < 120).slice(0, 15) };
        }
        // significant = anything except pure body-text churn (product grids rotate constantly)
        // flag a page only for something NEW (offer, banner, headline, nav item, tool, job) or a title change;
        // removals are kept in the detail but rotation makes them too noisy to raise a flag on their own
        rec.changed = !WARM && (Boolean(ch.title) || Object.values(ch).some((d) => d && Array.isArray(d.added) && d.added.length > 0));
        rec.changes = ch;
      } else {
        rec.changed = false;
        rec.baseline = !prev;
      }
      // keep body lines in state only (not in the published output)
      // screenshot upload bookkeeping: keep last published screenshot URL; upload again only when something changed
      rec.prevShotUrl = prev?.shotUrl || null;
      rec.needsUpload = !WARM && rec.status === 'ok' && (rec.changed || !prev?.shotUrl);
      fs.writeFileSync(prevPath, JSON.stringify({ ...rec, lines: linesForDiff, shotUrl: prev?.shotUrl || null, screenshot: undefined, changes: undefined, textChange: undefined, needsUpload: undefined, prevShotUrl: undefined }));
      delete rec.memo;
    } catch (e) {
      rec.status = 'error';
      rec.error = String(e.message || e).slice(0, 300);
    }
    await page.close();
    console.log(`[${rec.status}] ${p.competitorId} ${p.label}: ${rec.changed ? 'CHANGED' : rec.baseline ? 'baseline' : 'same'} offers=${(rec.offers || []).length} tech=${(rec.tech || []).length}`);
    results.push(rec);
    await new Promise((r) => setTimeout(r, 1500)); // polite gap between pages
  }
  await browser.close();
  fs.writeFileSync(path.join(ROOT, 'out', 'pagewatch.json'), JSON.stringify({ runAt, pages: results }, null, 1));
  console.log(`\n${results.length} pages, ${results.filter((r) => r.changed).length} changed -> out/pagewatch.json`);
})();
