"""
Pulls the last 7 days of publications from the RSS feeds listed in
sources.yaml, filters them to EU Green Deal / environmental-policy-relevant
content, and writes them to digest.md (human-readable) and
site/digest.json (what the website reads to display entries).

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

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_FILE = Path(__file__).parent / "digest.md"
JSON_OUTPUT_FILE = Path(__file__).parent / "site" / "digest.json"
DAYS_BACK = 7

# Bound applied to article text before keyword matching / display (see
# bounded_excerpt() below). Chosen to comfortably cover a real lead
# paragraph while still excluding keyword mentions buried deep in
# long-form bodies.
EXCERPT_CHARS = 600

GREEN_DEAL_KEYWORDS = [
    "climate change", "climate", "climate crisis", "climate policy", "climate diplomacy",
    "climate action", "climate finance", "climate adaptation", "climate mitigation",
    "green deal", "fit for 55", "cbam", "carbon border adjustment",
    "emissions trading", "eu ets", "ets", "ets2", "ets 2",
    "nature restoration law",
    "nature restoration", "circular economy", "biodiversity",
    "renewable energy", "renewables", "energy transition", "decarbonisation",
    "decarbonization", "methane", "fossil fuel", "fossil fuels", "net zero",
    "net-zero", "clean energy", "energy efficiency", "solar", "solar power", "wind power", "wind mills",
    "wind energy", "coal phase-out", "coal phase out", "energy"
    "sustainability", "sustainable", "emissions", "carbon", "environment", "transition",
    "environmental", "pollution", "deforestation", "ecosystem", "ecosystems",
    "biodiversity loss", "air quality", "water quality", "plastic pollution",
    "single-use plastics", "recycling", "waste management", "greenhouse gas",
    "greenhouse gases", "carbon tax", "carbon price", "carbon pricing",
    "green transition", "just transition", "CCUS", "CCU", "CCS", "biogenic", "Clean Industrial Deal", "Article 6", "Paris Agreement", "Kyoto", "UNFCCC", "UNEP", "EPR", "Extended Producer Responsibility"
]

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
    deep in an otherwise off-topic piece. E.g. "Indemnifying Bayer" (a
    podcast episode about Bayer lobbying for legal indemnification over
    glyphosate lawsuits, and disinformation tactics) matched only because
    paragraph 2 of 4 draws an analogy to "the climate change debate" as a
    parallel to tobacco-industry disinformation -- not because the piece
    is actually about climate policy. Bounding matching (and the stored/
    displayed summary) to a lead-paragraph-length excerpt avoids this
    without narrowing the filter so much that genuinely relevant articles
    (whose real topic is normally stated in their opening lines) get
    missed.
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
    feed = feedparser.parse(url)
    if feed.bozo and not feed.entries:
        print(f"  [warning] could not parse feed for {name}: {url}")
        return []

    recent = []
    skipped_off_topic = 0
    for entry in feed.entries:
        published = entry_date(entry)
        if published is not None and published < cutoff:
            continue

        title, excerpt = entry_text_fields(entry)

        if not is_relevant(title, excerpt):
            skipped_off_topic += 1
            continue

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

    if skipped_off_topic:
        print(f"  filtered out {skipped_off_topic} off-topic item(s)")

    return recent


def main():
    sources = load_sources()
    cutoff = dt.datetime.utcnow() - dt.timedelta(days=DAYS_BACK)

    all_entries = []
    for source in sources:
        name, url = source["name"], source["url"]
        field = source.get("field", "green-deal")
        print(f"Checking {name} ({field})...")
        entries = fetch_recent_entries(name, url, field, cutoff)
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


if __name__ == "__main__":
    main()

