"""
backfill.py

One-off historical backfill for site/archive.json, going back to a given
start month (default 2020-01) instead of only accumulating from whenever
the regular weekly pipeline first ran.

WHY THIS EXISTS / WHAT IT CAN AND CAN'T DO
-------------------------------------------
The regular pipeline (fetch_digest.py) deliberately does NOT backfill --
see the docstring on update_archive(): RSS feeds only expose the most
recent handful of items, and most scraper-based sources are built to
parse a single "latest" listing page, not a historical archive.

This script's approach: many of our RSS-only sources (~107 of 156) are
WordPress sites, and WordPress exposes a *date archive* at
`{site-root}/{year}/{month:02d}/` for essentially every theme, regardless
of that site's individual post permalink structure. That URL is a genuine
historical listing, not a "latest" page, so it's the one generic lever
available for backfilling many sources at once without writing 100+
bespoke scrapers overnight.

This is inherently best-effort and UNEVEN across sources:
  - Sites that are still on "classic" WordPress (most NGO/think-tank
    sites) tend to work well (confirmed live on eeb.org going back to
    March 2020, with real dated articles).
  - Sites that have since moved to a headless/JS-rendered rebuild (e.g.
    Ember's 2024 relaunch) or a different CMS entirely will 404 or return
    nothing -- confirmed live for a few of these during design.
  - The 49 sources with a custom `scraper:` in sources.yaml are NOT
    attempted here -- each one is hand-built to parse a single "latest"
    page for a specific site, with no historical-pagination support (that
    would be its own project). Skipped, not silently dropped -- see the
    run summary this script prints.

Because of this unevenness, every source is cheaply PROBED first (one
request, for a recent month) before committing to a full 2020-present
crawl for it -- sources that don't support the date-archive pattern cost
one request, not ~70.

Entries that make it through the probe go through the EXACT SAME
relevance/EU-gate/cross-tagging pipeline as fetch_digest.main(), so
backfilled archive entries are held to the same quality bar as live ones
-- see run_backfill() below, which mirrors main()'s per-source block.

Run with:
    python3 backfill.py [--start-year 2020] [--start-month 1]
                        [--max-pages-per-month 3] [--delay 0.6]
                        [--only SOURCE_NAME [SOURCE_NAME ...]]

This needs real internet access (it fetches ~100+ external sites), so it
must run in CI (GitHub Actions), not in a sandboxed/offline environment.
It writes/updates site/archive.json incrementally -- after EVERY source,
not only at the end -- so if the run is stopped early (timeout, manual
cancel), everything processed so far is already saved.
"""

import argparse
import datetime as dt
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

import backend_scrapers
import fetch_digest as fd

HEADERS = backend_scrapers.HEADERS
REQUEST_TIMEOUT = backend_scrapers.REQUEST_TIMEOUT

# Politeness: delay between requests to any one external site.
DEFAULT_DELAY = 0.6

# Safety valves against a runaway crawl on a single source.
DEFAULT_MAX_PAGES_PER_MONTH = 3
MAX_ENTRIES_PER_SOURCE = 600

_FEED_SUFFIX_RE = re.compile(r"/(feed|rss(\.xml)?)/?$", re.IGNORECASE)

_BAD_URL_MARKERS = ("404", "not-found", "notfound", "page-not-found", "error")

# Broad, format-tolerant date patterns for text found in a card/article
# that has no machine-readable <time datetime="..."> attribute. Ordered
# roughly by how common each is across WordPress themes.
_DATE_FORMATS = [
    "%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d.%m.%Y", "%Y-%m-%d", "%m/%d/%Y",
]
_DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+\d{4}"
    r"|(?:January|February|March|April|May|June|July|August|September|"
    r"October|November|December)\s+\d{1,2},?\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\.\d{1,2}\.\d{4})\b"
)


def _base_url_from_feed(url):
    """Strip a trailing /feed/, /rss, or /rss.xml to get the site root that
    a WordPress date archive would hang off of."""
    base = _FEED_SUFFIX_RE.sub("", url)
    return base.rstrip("/") + "/"


def _looks_like_bad_page(final_url, soup):
    lowered = final_url.lower()
    if any(marker in lowered for marker in _BAD_URL_MARKERS):
        return True
    title = soup.title.get_text(" ", strip=True).lower() if soup.title else ""
    if "404" in title or "not found" in title or "page not found" in title:
        return True
    return False


def _parse_entry_date(container, fallback_year, fallback_month):
    """Best-effort date extraction for one candidate post container.
    Falls back to the 1st of the queried month (still correct for
    month-bucketing, which is all update_archive() actually needs)."""
    time_tag = container.find("time")
    if time_tag and time_tag.get("datetime"):
        raw = time_tag["datetime"][:10]
        try:
            return dt.datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            pass
    text = container.get_text(" ", strip=True)
    match = _DATE_TEXT_RE.search(text)
    if match:
        raw = match.group(0).replace(",", "")
        for fmt in _DATE_FORMATS:
            try:
                return dt.datetime.strptime(raw, fmt.replace(",", ""))
            except ValueError:
                continue
    return dt.datetime(fallback_year, fallback_month, 1)


def _extract_entries(soup, org, year, month):
    """Structure-agnostic extraction: try progressively looser candidate-
    container selectors (most WordPress themes wrap each post in <article>
    or a class containing "post"/"entry"/"hentry"; a few don't, so we fall
    back to treating any h2/h3 with a single link as a post heading)."""
    containers = soup.select("article")
    if not containers:
        containers = soup.select(
            "[class*='post-'], .hentry, .entry, [class*='type-post']"
        )
    if not containers:
        containers = soup.select("h2, h3")

    entries = []
    seen_links = set()
    for container in containers:
        heading = container if container.name in ("h2", "h3") else container.find(
            ["h1", "h2", "h3", "h4"]
        )
        link_tag = heading.find("a", href=True) if heading else None
        if not link_tag:
            link_tag = container.find("a", href=True)
        if not link_tag:
            continue
        title = link_tag.get_text(" ", strip=True)
        if not title or len(title) < 8:
            continue
        link = link_tag["href"]
        if link in seen_links:
            continue
        seen_links.add(link)

        date = _parse_entry_date(container, year, month)

        summary = ""
        for p in container.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text and text != title and len(text) > 20:
                summary = text
                break

        entries.append(
            backend_scrapers._make_item(org, title, link, date, summary)
        )
    return entries


def _fetch_month_page(base_url, year, month, page=1):
    """Fetch one page of a WordPress date-archive month. Returns
    (soup, final_url) or (None, None) on any failure/bad page."""
    url = urljoin(base_url, f"{year}/{month:02d}/")
    if page > 1:
        url = urljoin(url, f"page/{page}/")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
    except requests.RequestException:
        return None, None
    if resp.status_code != 200:
        return None, None
    soup = BeautifulSoup(resp.text, "html.parser")
    if _looks_like_bad_page(resp.url, soup):
        return None, None
    return soup, resp.url


def probe_source(base_url, org):
    """Cheap single-request check: does this site support the WordPress
    date-archive pattern at all? Uses a recent, fully-elapsed month so a
    redesigned/JS-rendered site is detected as unsupported right now,
    rather than trusting old sources.yaml assumptions."""
    probe_date = dt.date.today().replace(day=1) - dt.timedelta(days=60)
    soup, final_url = _fetch_month_page(base_url, probe_date.year, probe_date.month)
    if soup is None:
        return False
    entries = _extract_entries(soup, org, probe_date.year, probe_date.month)
    return len(entries) > 0


def backfill_source(source, start_year, start_month, max_pages_per_month, delay):
    """Walk every month from (start_year, start_month) through last month,
    collecting raw entries in the exact shape fetch_source() produces, so
    they can go through fd.apply_relevance_filter() etc. unchanged."""
    name = source["name"]
    field = source.get("field", "green-deal")
    base_url = _base_url_from_feed(source["url"])

    today = dt.date.today()
    end_year, end_month = today.year, today.month
    if end_month == 1:
        end_year, end_month = end_year - 1, 12
    else:
        end_month -= 1

    raw_entries = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        page = 1
        while page <= max_pages_per_month:
            soup, final_url = _fetch_month_page(base_url, year, month, page)
            time.sleep(delay)
            if soup is None:
                break
            page_entries = _extract_entries(soup, name, year, month)
            if not page_entries:
                break
            raw_entries.extend(page_entries)
            has_next = bool(
                soup.select_one("a[rel='next'], link[rel='next'], .next, a.next")
            )
            if not has_next:
                break
            page += 1
        if len(raw_entries) >= MAX_ENTRIES_PER_SOURCE:
            print(f"  [{name}] hit MAX_ENTRIES_PER_SOURCE cap, stopping early")
            break
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1

    for entry in raw_entries:
        entry["field"] = field
    return raw_entries


def _process_source_like_main(source, raw_entries):
    """Mirrors fetch_digest.main()'s per-source processing block exactly
    (minus fetch_source() itself, since raw_entries is already supplied),
    so backfilled entries get identical filtering/tagging/cross-tagging to
    a live pipeline run."""
    field = source.get("field", "green-deal")
    actor_type = source.get("actor_type", "think-tank")
    eu_gate = source.get("eu_gate", False)

    raw_entries, _ = fd.filter_out_events(raw_entries)
    raw_entries, _ = fd.filter_out_low_value(raw_entries)
    raw_entries, _ = fd.filter_out_non_english(raw_entries)

    for entry in raw_entries:
        entry["actor_type"] = actor_type
        entry["content_type"] = fd.classify_content_type(
            entry["title"], entry["link"], entry.get("summary", "")
        )

    try:
        primary_entries = fd.apply_relevance_filter(raw_entries, field, actor_type, eu_gate)
    except Exception as exc:
        print(f"  [warning] relevance filter failed: {exc}")
        primary_entries = []

    for entry in primary_entries:
        entry["tags"] = (
            fd.tag_legislation(entry["title"], entry["summary"], field)
            if field in ("green-deal", "competition")
            else []
        )

    all_entries = list(primary_entries)

    if field != "green-deal":
        for match in raw_entries:
            if fd._CROSS_TAG_PATTERN.search(f"{match['title']} {match['summary']}"):
                cross_entry = dict(match)
                cross_entry["field"] = "green-deal"
                cross_entry["tags"] = fd.tag_legislation(cross_entry["title"], cross_entry["summary"])
                all_entries.append(cross_entry)

    if field != "competition":
        for match in raw_entries:
            if fd._COMPETITION_CROSS_TAG_PATTERN.search(f"{match['title']} {match['summary']}"):
                cross_entry = dict(match)
                cross_entry["field"] = "competition"
                cross_entry["tags"] = fd.tag_legislation(cross_entry["title"], cross_entry["summary"], "competition")
                all_entries.append(cross_entry)

    return all_entries


def run_backfill(start_year=2020, start_month=1, max_pages_per_month=DEFAULT_MAX_PAGES_PER_MONTH,
                  delay=DEFAULT_DELAY, only=None):
    sources = fd.load_sources()
    candidates = [s for s in sources if "url" in s and "scraper" not in s]
    if only:
        candidates = [s for s in candidates if s["name"] in only]

    print(f"Probing {len(candidates)} RSS-based sources for WordPress date-archive support...")

    viable, skipped = [], []
    for source in candidates:
        base_url = _base_url_from_feed(source["url"])
        try:
            ok = probe_source(base_url, source["name"])
        except Exception as exc:
            print(f"  [{source['name']}] probe error, skipping: {exc}")
            ok = False
        time.sleep(delay)
        (viable if ok else skipped).append(source["name"])
        print(f"  {'OK  ' if ok else 'skip'} {source['name']}")

    print(f"\n{len(viable)} source(s) support backfill, {len(skipped)} do not (no date-archive pattern found).")

    total_added = 0
    for source in candidates:
        if source["name"] not in viable:
            continue
        name = source["name"]
        print(f"\nBackfilling {name} from {start_year}-{start_month:02d}...")
        try:
            raw_entries = backfill_source(source, start_year, start_month, max_pages_per_month, delay)
        except Exception as exc:
            print(f"  [warning] backfill failed for {name}: {exc}")
            continue
        processed = _process_source_like_main(source, raw_entries)
        print(f"  {len(raw_entries)} raw item(s) found -> {len(processed)} passed relevance filtering")
        if processed:
            fd.update_archive(processed)  # incremental checkpoint, saved immediately
            total_added += len(processed)

    print(f"\nDone. Backfill contributed {total_added} entries across {len(viable)} source(s).")
    print(f"Not attempted (custom scrapers, {len(sources) - len(candidates)} source(s)) or "
          f"no date-archive support ({len(skipped)} source(s)): see log above for names.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2020)
    parser.add_argument("--start-month", type=int, default=1)
    parser.add_argument("--max-pages-per-month", type=int, default=DEFAULT_MAX_PAGES_PER_MONTH)
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY)
    parser.add_argument("--only", nargs="+", default=None, help="Limit to these source names (for testing).")
    args = parser.parse_args()

    run_backfill(
        start_year=args.start_year,
        start_month=args.start_month,
        max_pages_per_month=args.max_pages_per_month,
        delay=args.delay,
        only=args.only,
    )
