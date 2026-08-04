"""
Pulls the last 7 days of publications from the RSS feeds listed in
sources.yaml and writes them to digest.md (human-readable) and
site/digest.json (what the website reads to display entries).

Usage:
    pip install -r requirements.txt
    python fetch_digest.py
"""

import datetime as dt
import json
from pathlib import Path

import feedparser
import yaml

SOURCES_FILE = Path(__file__).parent / "sources.yaml"
OUTPUT_FILE = Path(__file__).parent / "digest.md"
JSON_OUTPUT_FILE = Path(__file__).parent / "site" / "digest.json"
DAYS_BACK = 7


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
    for entry in feed.entries:
        published = entry_date(entry)
        if published is None or published >= cutoff:
            recent.append(
                {
                    "org": name,
                    "field": field,
                    "title": entry.get("title", "(no title)"),
                    "link": entry.get("link", ""),
                    "date": published.strftime("%Y-%m-%d") if published else "unknown date",
                    "summary": entry.get("summary", "").strip(),
                }
            )
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
        print(f"  found {len(entries)} recent item(s)")
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
