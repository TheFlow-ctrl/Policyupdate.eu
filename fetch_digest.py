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
import json
import re
from pathlib import Path

import feedparser
import yaml

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_FILE = Path(__file__).parent / "digest.md"
JSON_OUTPUT_FILE = Path(__file__).parent / "site" / "digest.json"
DAYS_BACK = 7

# Keywords used to decide whether an entry is actually about EU Green Deal /
# environmental policy. Some tracked sources (e.g. ECFR, Corporate Europe
# Observatory) cover many unrelated topics (defense, trade, foreign policy,
# lobbying in general), so every entry is checked against this list before
# being included in the digest.
GREEN_DEAL_KEYWORDS = [
    # Core climate terms
    "climate change", "climate crisis", "climate policy", "climate diplomacy",
    "climate action", "climate finance", "climate adaptation", "climate mitigation",
    # EU Green Deal / regulatory terminology
    "green deal", "fit for 55", "cbam", "carbon border adjustment",
    "emissions trading", "eu ets", "ets", "nature restoration law",
    "nature restoration", "circular economy", "biodiversity",
    # Energy transition
    "renewable energy", "renewables", "energy transition", "decarbonisation",
    "decarbonization", "methane", "fossil fuel", "fossil fuels", "net zero",
    "net-zero", "clean energy", "energy efficiency", "solar power", "wind power",
    "wind energy", "coal phase-out", "coal phase out",
    # Adjacent environmental terms
    "sustainability", "sustainable", "emissions", "carbon", "environment",
    "environmental", "pollution", "deforestation", "ecosystem", "ecosystems",
    "biodiversity loss", "air quality", "water quality", "plastic pollution",
    "single-use plastics", "recycling", "waste management", "greenhouse gas",
    "greenhouse gases", "carbon tax", "carbon price", "carbon pricing",
    "green transition", "just transition",
]

_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in GREEN_DEAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def is_relevant(title, summary):
    """Return True if title+summary contains at least one Green-Deal /
    environmental-policy-relevant keyword (case-insensitive)."""
    text = f"{title or ''} {summary or ''}"
    return bool(_KEYWORD_PATTERN.search(text))


def load_sources():
    with open(SOURCES_FILE, "r") as f:
        data = yaml.safe_load(f)
    return data["sources"]


def entry_date(entry):
    """Return a datetime for an RSS entry, or None if it can't be parsed."""
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

        title = entry.get("title", "(no title)")
        summary = entry.get("summary", "").strip()

        if not is_relevant(title, summary):
            skipped_off_topic += 1
            continue

        recent.append(
            {
                "org": name,
                "field": field,
                "title": title,
                "link": entry.get("link", ""),
                "date": published.strftime("%Y-%m-%d") if published else "unknown date",
                "summary": summary,
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
