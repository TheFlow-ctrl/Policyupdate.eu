"""
Pulls the last 7 days of publications from the RSS feeds and scrapers listed
in sources.yaml, filters them to EU Green Deal / environmental-policy-relevant
content (green-deal sources only -- other fields are not topic-filtered), and
writes them to digest.md (human-readable) and site/digest.json (what the
website reads to display entries).

Usage:
    pip install -r requirements.txt
    python fetch_digest.py
"""

import datetime as dt
import html
import json
import re
from pathlib import Path

import feedparser
import yaml

import backend_scrapers

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_FILE = Path(__file__).parent / "digest.md"
JSON_OUTPUT_FILE = Path(__file__).parent / "site" / "digest.json"
ARCHIVE_FILE = Path(__file__).parent / "site" / "archive.json"
DAYS_BACK = 7

MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Bound applied to article text before keyword matching / display (see
# bounded_excerpt() below). Chosen to comfortably cover a real lead
# paragraph while still excluding keyword mentions buried deep in
# long-form bodies.
EXCERPT_CHARS = 600

# NOTE: this keyword list is only applied to sources tagged field: green-deal
# (see apply_relevance_filter()). Sources tagged security/tech/health are
# NOT run through this filter -- it would incorrectly reject almost
# everything from a general-topic source, since e.g. a defense/foreign-policy
# article has no reason to mention "climate" or "carbon".
GREEN_DEAL_KEYWORDS = [
    "climate change", "climate crisis", "climate policy", "climate diplomacy",
    "climate action", "climate finance", "climate adaptation", "climate mitigation",
    "world climate conference", "un climate conference",
    "green deal", "fit for 55", "cbam", "carbon border adjustment",
    "emissions trading", "eu ets", "ets", "ets2", "ets 2",
    "nature restoration law",
    "nature restoration", "circular economy", "biodiversity",
    "renewable energy", "renewables", "energy transition", "energy policy",
    "energy security", "decarbonisation",
    "decarbonization", "methane", "fossil fuel", "fossil fuels", "net zero",
    "net-zero", "clean energy", "energy efficiency", "solar power", "wind power",
    "wind energy", "coal phase-out", "coal phase out", "just transition",
    "green transition",
    "sustainability", "sustainable", "emissions", "carbon", "environmental policy",
    "environmental regulation", "pollution", "deforestation", "ecosystem", "ecosystems",
    "biodiversity loss", "air quality", "water quality", "plastic pollution",
    "single-use plastics", "recycling", "waste management", "greenhouse gas",
    "greenhouse gases", "carbon tax", "carbon price", "carbon pricing",
    "CCUS", "CCU", "CCS", "biogenic",
    "Clean Industrial Deal", "Article 6", "Paris Agreement", "Kyoto", "UNFCCC",
    "UNEP", "EPR", "Extended Producer Responsibility",
]
# Removed as too broad after real false positives: bare "climate", "energy",
# "transition", "solar", "environment", "wind mills". Each matched
# incidental mentions in off-topic content (e.g. a schools-outreach article
# titled "...to the World Climate Conference" matched on bare "climate";
# VTT -- a large multi-domain applied-research institute -- produced mostly
# noise because "energy" appears constantly in purely technical contexts).
# Kept the same ideas but as more specific multi-word phrases instead.

_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in GREEN_DEAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def clean_text(raw_html):
    """Strip HTML tags/entities from a feed field and collapse whitespace.

    Some feeds embed markup-heavy content directly in the fields
    feedparser exposes (e.g. Corporate Europe Observatory's Drupal feed
    puts the entire article body, including nested <div>/<iframe> markup,
    straight into <description>). Stripping tags first means any
    character-based truncation downstream is measured against actual
    visible text, not markup soup.
    """
    if not raw_html:
        return ""
    text = _TAG_RE.sub(" ", raw_html)
    text = html.unescape(text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def bounded_excerpt(text, limit=EXCERPT_CHARS):
    """Return the first `limit` characters of text, cut at a word boundary.

    This bound is the key fix for a real false positive: Corporate Europe
    Observatory's RSS <description> field contains the ENTIRE long-form
    article body (no separate short excerpt), so unbounded keyword
    matching against it can trigger on a single stray, incidental mention
    deep in an otherwise off-topic piece. Bounding matching (and the
    stored/displayed summary) to a lead-paragraph-length excerpt avoids
    this without narrowing the filter so much that genuinely relevant
    articles (whose real topic is normally stated in their opening lines)
    get missed.
    """
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut + "…"


def entry_text_fields(entry):
    """Return (title, excerpt) for keyword matching and display.

    Prefers <content:encoded> (the full article body, when a feed
    provides it separately from <description>) over the raw summary,
    since some feeds' <description> is a very short, low-signal teaser.
    Whichever field is used, it is HTML-stripped and bounded to
    EXCERPT_CHARS -- so matching never sees unbounded full-article text,
    and the digest never shows raw markup.
    """
    title = entry.get("title", "(no title)")
    content_list = entry.get("content")
    if content_list:
        raw = content_list[0].get("value", "")
    else:
        raw = entry.get("summary", "")
    cleaned = clean_text(raw)
    excerpt = bounded_excerpt(cleaned)
    return title, excerpt


def is_relevant(title, excerpt):
    text = f"{title or ''} {excerpt or ''}"
    return bool(_KEYWORD_PATTERN.search(text))


def apply_relevance_filter(entries, field):
    """Keyword-filter entries, but ONLY for field == 'green-deal'.

    Other fields (security, tech, health) are source-segregated instead --
    every source tagged with one of those fields is already handpicked for
    that topic, so running them through GREEN_DEAL_KEYWORDS would wrongly
    reject nearly everything.
    """
    if field != "green-deal":
        return entries

    kept = []
    skipped = 0
    for entry in entries:
        if is_relevant(entry["title"], entry["summary"]):
            kept.append(entry)
        else:
            skipped += 1

    if skipped:
        print(f"  filtered out {skipped} off-topic item(s)")

    return kept


def load_sources():
    with open(SOURCES_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data["sources"]


def entry_date(entry):
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            return dt.datetime(*value[:6])
    return None


def fetch_recent_entries(name, url, field, cutoff):
    """Fetch and date-filter (but NOT relevance-filter) entries from an RSS
    feed. Relevance filtering happens afterwards in apply_relevance_filter()
    so it can be applied identically to both feed-based and scraper-based
    sources."""
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        print(f"  [warning] could not parse feed for {name}: {url}")
        return []

    recent = []
    for entry in feed.entries:
        published = entry_date(entry)
        # An entry with no parseable date is EXCLUDED rather than included:
        # this is a "last N days" digest, so we can't confirm recency for
        # an undated item, and defaulting to "include" let stale/irrelevant
        # items resurface indefinitely (this was a real bug -- see
        # backend_scrapers.py's matching fix for the same issue).
        if published is None or published < cutoff:
            continue

        title, excerpt = entry_text_fields(entry)

        recent.append(
            {
                "org": name,
                "field": field,
                "title": title,
                "link": entry.get("link", ""),
                "date": published.strftime("%Y-%m-%d") if published else "unknown date",
                "summary": excerpt,
            }
        )

    return recent


def fetch_source(source, cutoff):
    """Dispatch a single sources.yaml entry to either the scraper path or
    the RSS-feed path, depending on whether it has a "scraper" or "url" key."""
    name = source["name"]
    field = source.get("field", "green-deal")

    if "scraper" in source:
        scraper_fn = backend_scrapers.SCRAPERS.get(source["scraper"])
        if scraper_fn is None:
            print(f"  [warning] unknown scraper key '{source['scraper']}' for {name}")
            return []
        try:
            return scraper_fn(cutoff)
        except Exception as exc:
            print(f"  [warning] scraper for {name} failed: {exc}")
            return []

    try:
        return fetch_recent_entries(name, source["url"], field, cutoff)
    except Exception as exc:
        print(f"  [warning] feed for {name} failed: {exc}")
        return []


def update_archive(new_entries):
    """Merge this run's entries into a cumulative, month-grouped archive at
    site/archive.json, deduplicated by link.

    This is how the archive builds up over time: there is no historical
    backfill (RSS feeds don't expose months of history, and most sources
    have no scraper), so the archive simply starts accumulating from
    whenever this code first runs and grows by one week's worth of entries
    each time. Only entries with a real, parsed date are archived --
    "unknown date" entries can't be placed in a month bucket.
    """
    existing_entries = []
    if ARCHIVE_FILE.exists():
        try:
            existing_data = json.loads(ARCHIVE_FILE.read_text())
            for month in existing_data.get("months", []):
                existing_entries.extend(month.get("entries", []))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [warning] could not read existing archive, starting fresh: {exc}")

    # Dedupe by link, preferring the newest-seen copy of any given entry
    # (a source occasionally revises a title/summary after first publish).
    by_link = {}
    for entry in existing_entries + new_entries:
        link = entry.get("link")
        if not link:
            continue
        if entry.get("date") == "unknown date":
            continue
        by_link[link] = entry

    months = {}
    for entry in by_link.values():
        date_str = entry.get("date", "")
        try:
            year, month_num, _ = date_str.split("-")
            month_num = int(month_num)
        except (ValueError, AttributeError):
            continue
        key = f"{year}-{month_num:02d}"
        months.setdefault(key, {
            "key": key,
            "label": f"{MONTH_NAMES[month_num - 1]} {year}",
            "entries": [],
        })["entries"].append(entry)

    for month in months.values():
        month["entries"].sort(key=lambda e: e["date"], reverse=True)

    ordered_months = sorted(months.values(), key=lambda m: m["key"], reverse=True)

    ARCHIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ARCHIVE_FILE.write_text(
        json.dumps(
            {"generated": dt.date.today().isoformat(), "months": ordered_months},
            indent=2,
        )
    )
    total = sum(len(m["entries"]) for m in ordered_months)
    print(f"Archive now has {total} entries across {len(ordered_months)} month(s)")


def main():
    sources = load_sources()
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=DAYS_BACK)

    all_entries = []
    for source in sources:
        name = source["name"]
        field = source.get("field", "green-deal")
        print(f"Checking {name} ({field})...")

        try:
            entries = fetch_source(source, cutoff)
            entries = apply_relevance_filter(entries, field)
        except Exception as exc:
            # Belt-and-suspenders: fetch_source() already catches errors
            # from individual scrapers/feeds, but this outer guard makes
            # sure a bug anywhere in a single source's handling (or in
            # apply_relevance_filter itself) can never take down the whole
            # run -- with 30+ sources, one bad actor shouldn't block every
            # other source's content from being published.
            print(f"  [warning] unexpected error processing {name}, skipping: {exc}")
            entries = []

        print(f"  found {len(entries)} relevant recent item(s)")
        all_entries.extend(entries)

    all_entries.sort(key=lambda e: e["date"], reverse=True)

    lines = [f"# Weekly Green Deal Digest — {dt.date.today().isoformat()}", ""]
    if not all_entries:
        lines.append("No new publications found this week.")
    else:
        for e in all_entries:
            lines.append(f"### {e['title']}")
            lines.append(f"*{e['org']} — {e['date']}*")
            if e["summary"]:
                lines.append("")
                lines.append(e["summary"])
            lines.append("")
            lines.append(f"[Read more]({e['link']})")
            lines.append("")
            lines.append("---")
            lines.append("")

    OUTPUT_FILE.write_text("\n".join(lines))
    print(f"\nWrote {len(all_entries)} entries to {OUTPUT_FILE}")

    JSON_OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT_FILE.write_text(
        json.dumps(
            {"generated": dt.date.today().isoformat(), "entries": all_entries},
            indent=2,
        )
    )
    print(f"Wrote {len(all_entries)} entries to {JSON_OUTPUT_FILE}")

    update_archive(all_entries)


if __name__ == "__main__":
    main()
