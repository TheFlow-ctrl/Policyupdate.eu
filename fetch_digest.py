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

# feedparser's default request has no real browser User-Agent, which some
# WAFs (observed on FSR Climate's WordPress install) silently block --
# serving an empty body instead of an error, which looks like "feed has no
# entries" rather than "request was blocked". A normal browser UA header
# avoids this without changing behaviour for feeds that never cared.
FEED_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

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

# Stricter subset of GREEN_DEAL_KEYWORDS used ONLY for cross-tagging content
# from non-green-deal sources (see the cross-tagging block in main()).
# Primary green-deal sources are dedicated climate/energy feeds, so a fairly
# broad keyword list is safe there. Cross-tagging instead runs against
# arbitrary foreign-policy/security/general-topic content, where generic
# terms cause real false positives -- e.g. an ECFR podcast about the
# Israeli election ("Can a ceasefire survive Israel's election?") matched
# on "energy security", a phrase that means something completely different
# in a Middle East geopolitics context than in an EU decarbonisation one.
# This list drops bare/overloaded terms (energy policy, energy security,
# sustainability, sustainable, emissions, carbon, ecosystem(s), recycling,
# Article 6) that are too generic to safely apply outside a feed that's
# already climate-dedicated, keeping only phrases specific enough to be
# unambiguous wherever they appear.
CROSS_TAG_KEYWORDS = [
    "climate change", "climate crisis", "climate policy", "climate diplomacy",
    "climate action", "climate finance", "climate adaptation", "climate mitigation",
    "world climate conference", "un climate conference",
    "green deal", "fit for 55", "cbam", "carbon border adjustment",
    "emissions trading", "eu ets", "ets2", "ets 2",
    "nature restoration law", "nature restoration", "circular economy",
    "biodiversity", "biodiversity loss",
    "renewable energy", "renewables", "energy transition",
    "decarbonisation", "decarbonization", "methane", "fossil fuel", "fossil fuels",
    "net zero", "net-zero", "clean energy", "energy efficiency",
    "solar power", "wind power", "wind energy", "coal phase-out", "coal phase out",
    "just transition", "green transition",
    "environmental policy", "environmental regulation", "pollution", "deforestation",
    "air quality", "water quality", "plastic pollution", "single-use plastics",
    "waste management", "greenhouse gas", "greenhouse gases",
    "carbon tax", "carbon price", "carbon pricing",
    "CCUS", "CCU", "CCS", "biogenic",
    "Clean Industrial Deal", "Paris Agreement", "Kyoto", "UNFCCC",
    "UNEP", "EPR", "Extended Producer Responsibility",
]

_CROSS_TAG_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in CROSS_TAG_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Additional, academic-register vocabulary used ONLY to widen the topic
# check for actor_type == "academic" sources (see is_relevant()). Journal
# abstracts describe the same substance as think-tank/NGO output in more
# technical, less news-style language (e.g. "carbon leakage" rather than
# "CBAM", "Europeanization" rather than "EU policy") -- GREEN_DEAL_KEYWORDS
# alone, tuned against RSS-feed news writing, misses a lot of this.
ACADEMIC_TOPIC_KEYWORDS = [
    "carbon leakage", "policy diffusion", "climate governance",
    "multi-level governance", "multilevel governance", "regulatory stringency",
    "environmental federalism", "policy integration",
    "europeanization", "europeanisation", "climate law", "environmental law",
    "energy governance", "low-carbon transition", "low carbon transition",
    "decarbonisation pathway", "decarbonization pathway", "climate neutrality",
    "greenwashing", "carbon lock-in", "energy poverty", "just transition fund",
    "climate litigation", "environmental justice", "polycentric governance",
    "regulatory competition", "eco-innovation", "green innovation",
    "industrial decarbonisation", "industrial decarbonization",
    "sustainable finance", "esg disclosure", "climate risk disclosure",
    "climate policy integration", "climate ambition", "carbon budget",
    "stranded assets", "just transition mechanism",
]

_ACADEMIC_KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in GREEN_DEAL_KEYWORDS + ACADEMIC_TOPIC_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# EU-specificity gate applied ONLY to actor_type == "academic" sources, on
# top of (not instead of) the topic check above. Academic journals (Energy
# Policy, Nature Climate Change, Environmental Politics...) publish
# globally -- a paper on US carbon pricing or Chinese renewables policy
# matches GREEN_DEAL_KEYWORDS just as easily as an EU one, but has nothing
# to do with this site. Requiring an additional EU context marker (or a
# keyword that already names an EU law/institution directly) keeps only
# genuinely EU-relevant academic output. This mirrors the CROSS_TAG_KEYWORDS
# pattern above -- same idea (a stricter AND-gate for a noisier source
# category), different reason (global topical breadth, not off-topic field).
EU_CONTEXT_KEYWORDS = [
    "european union", "eu policy", "eu law", "eu regulation", "eu directive",
    "eu member state", "eu member states", "european commission",
    "european parliament", "european council",
    "council of the european union", "brussels", "eu27", "eu-27",
    "eu institutions", "eu climate policy", "eu energy policy",
    "eu environmental policy", "european green deal", "europe", "european",
]

_EU_CONTEXT_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in EU_CONTEXT_KEYWORDS) + r")\b",
    re.IGNORECASE,
)

# Keywords that already unambiguously name an EU law/institution on their
# own, so a match on one of these satisfies the EU-specificity gate without
# also needing a separate EU_CONTEXT_KEYWORDS match.
_INHERENTLY_EU_KEYWORDS = {
    "green deal", "fit for 55", "cbam", "carbon border adjustment mechanism",
    "carbon border adjustment", "eu ets", "ets2", "ets 2",
    "nature restoration law", "clean industrial deal",
}


def is_eu_relevant(title, excerpt):
    """True if the text carries an EU-specific context marker, for the
    academic-source EU-specificity gate (see EU_CONTEXT_KEYWORDS above)."""
    text = f"{title or ''} {excerpt or ''}"
    if _EU_CONTEXT_PATTERN.search(text):
        return True
    text_lower = text.lower()
    return any(k in text_lower for k in _INHERENTLY_EU_KEYWORDS)

# Filters out event listings and calls for abstracts/papers -- these are
# administrative notices, not policy publications, and were showing up
# in the digest (e.g. a Chatham House "Climate and energy 2027" conference
# listing, an EERA "Call for abstracts" page). Applied globally to every
# source, not just green-deal, since an event listing is equally
# out-of-place under any field.
_EVENT_TITLE_RE = re.compile(
    r"\b(call for (abstracts|papers|proposals|applications|contributions)|"
    r"save the date|registration (now )?open)\b",
    re.IGNORECASE,
)
_EVENT_LINK_RE = re.compile(r"/(events?|webinars?)/", re.IGNORECASE)


def is_event_or_cfa(title, link):
    """True if an entry looks like an event listing or a call for
    abstracts/papers rather than an actual publication."""
    if title and _EVENT_TITLE_RE.search(title):
        return True
    if link and _EVENT_LINK_RE.search(link):
        return True
    return False


def filter_out_events(entries):
    """Drop event/call-for-abstracts entries from a list, returning
    (kept_entries, number_skipped)."""
    kept = []
    skipped = 0
    for entry in entries:
        if is_event_or_cfa(entry.get("title", ""), entry.get("link", "")):
            skipped += 1
        else:
            kept.append(entry)
    return kept, skipped

# Sub-categories under the green-deal field: tags each entry with the
# specific EU laws/files it mentions, so the site can offer a secondary
# filter (see the frontend's TOPIC_LABELS, which must be kept in sync with
# the ids used here). An entry can carry multiple tags, or none -- lots of
# genuinely relevant Green Deal content won't name a specific law.
#
# (tag id, display label, keyword phrases to match)
LEGISLATION_TAGS = [
    ("ets1", "ETS I", [
        "eu ets", "emissions trading scheme", "emissions trading system",
    ]),
    ("ets2", "ETS II", [
        "ets2", "ets 2", "ets ii", "emissions trading for buildings",
        "emissions trading for road transport", "new emissions trading system",
        "second emissions trading system", "buildings and transport ets",
    ]),
    ("cbam", "CBAM", [
        "cbam", "carbon border adjustment mechanism", "carbon border adjustment",
    ]),
    ("red3", "RED III", [
        "red iii", "red 3", "renewable energy directive",
    ]),
    ("csddd", "CSDDD", [
        "csddd", "corporate sustainability due diligence directive",
        "due diligence directive",
    ]),
    ("crma", "Critical Raw Materials Act", [
        "critical raw materials act", "crma", "critical raw materials regulation",
    ]),
    ("nzia", "Net Zero Industry Act", [
        "net zero industry act", "nzia",
    ]),
    ("csrd", "CSRD", [
        "csrd", "corporate sustainability reporting directive",
    ]),
    ("taxonomy", "EU Taxonomy", [
        "eu taxonomy", "taxonomy regulation", "sustainable finance taxonomy",
    ]),
    ("sfdr", "SFDR", [
        "sfdr", "sustainable finance disclosure regulation",
    ]),
    ("eudr", "EUDR", [
        "eudr", "eu deforestation regulation", "deforestation regulation",
        "deforestation-free products",
    ]),
    ("nature-restoration", "Nature Restoration Law", [
        "nature restoration law", "nature restoration regulation",
    ]),
    ("lulucf", "LULUCF", [
        "lulucf", "land use, land-use change and forestry",
    ]),
    ("ccus", "CCUS", [
        "ccus", "carbon capture, utilisation and storage",
        "carbon capture and storage", "carbon capture utilization and storage",
    ]),
    ("eed", "EED", [
        "eed", "energy efficiency directive",
    ]),
]

_LEGISLATION_PATTERNS = {
    tag_id: re.compile(
        r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b",
        re.IGNORECASE,
    )
    for tag_id, _label, keywords in LEGISLATION_TAGS
}


def tag_legislation(title, excerpt):
    """Return the list of legislation-tag ids whose keywords appear in
    title+excerpt. An entry can match zero, one, or several tags."""
    text = f"{title or ''} {excerpt or ''}"
    return [
        tag_id
        for tag_id, _label, _keywords in LEGISLATION_TAGS
        if _LEGISLATION_PATTERNS[tag_id].search(text)
    ]

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


def is_relevant(title, excerpt, actor_type=None):
    text = f"{title or ''} {excerpt or ''}"
    pattern = _ACADEMIC_KEYWORD_PATTERN if actor_type == "academic" else _KEYWORD_PATTERN
    return bool(pattern.search(text))


def apply_relevance_filter(entries, field, actor_type=None):
    """Keyword-filter entries, but ONLY for field == 'green-deal'.

    Other fields (security, tech, health) are source-segregated instead --
    every source tagged with one of those fields is already handpicked for
    that topic, so running them through GREEN_DEAL_KEYWORDS would wrongly
    reject nearly everything.

    For actor_type == "academic", two things differ from the default path:
    the topic check itself is widened (GREEN_DEAL_KEYWORDS + the more
    technical ACADEMIC_TOPIC_KEYWORDS, since journal abstracts don't use
    news-style phrasing), and a second, EU-specificity check is layered on
    top (see is_eu_relevant()), since these are global journals that
    publish plenty of non-EU climate/energy research a topic-only filter
    would happily let through.
    """
    if field != "green-deal":
        return entries

    kept = []
    skipped = 0
    eu_skipped = 0
    for entry in entries:
        if not is_relevant(entry["title"], entry["summary"], actor_type):
            skipped += 1
            continue
        if actor_type == "academic" and not is_eu_relevant(entry["title"], entry["summary"]):
            eu_skipped += 1
            continue
        kept.append(entry)

    if skipped:
        print(f"  filtered out {skipped} off-topic item(s)")
    if eu_skipped:
        print(f"  filtered out {eu_skipped} non-EU academic item(s)")

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
    feed = feedparser.parse(url, request_headers=FEED_REQUEST_HEADERS)
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
        actor_type = source.get("actor_type", "think-tank")
        print(f"Checking {name} ({field}, {actor_type})...")

        try:
            raw_entries = fetch_source(source, cutoff)
        except Exception as exc:
            # Belt-and-suspenders: fetch_source() already catches errors
            # from individual scrapers/feeds, but this outer guard makes
            # sure a bug anywhere in a single source's handling can never
            # take down the whole run -- with 30+ sources, one bad actor
            # shouldn't block every other source's content from being
            # published.
            print(f"  [warning] unexpected error processing {name}, skipping: {exc}")
            raw_entries = []

        raw_entries, event_skipped = filter_out_events(raw_entries)
        if event_skipped:
            print(f"  filtered out {event_skipped} event/call-for-abstracts item(s)")

        for entry in raw_entries:
            entry["actor_type"] = actor_type

        # Primary inclusion: filtered against GREEN_DEAL_KEYWORDS only if
        # this source's own field IS green-deal. actor_type is passed
        # through so academic sources get the widened topic check + EU
        # gate (see apply_relevance_filter()).
        try:
            primary_entries = apply_relevance_filter(raw_entries, field, actor_type)
        except Exception as exc:
            print(f"  [warning] unexpected error filtering {name}, skipping: {exc}")
            primary_entries = []

        for entry in primary_entries:
            entry["tags"] = (
                tag_legislation(entry["title"], entry["summary"])
                if field == "green-deal"
                else []
            )

        print(f"  found {len(primary_entries)} relevant recent item(s) under {field}")
        all_entries.extend(primary_entries)

        # Cross-tagging: for sources whose primary field ISN'T green-deal
        # (the broad security/foreign-policy think tanks), also check their
        # raw entries against the green-deal keyword filter. Anything that
        # matches gets an ADDITIONAL copy tagged field: green-deal, so e.g.
        # an ECFR piece specifically about EU climate diplomacy can surface
        # on the Green Deal tab without moving all of ECFR's content there.
        # The original entry (unfiltered) still appears under its primary
        # field for whenever that tab goes live.
        if field != "green-deal":
            cross_matches = [
                e for e in raw_entries
                if _CROSS_TAG_PATTERN.search(f"{e['title']} {e['summary']}")
            ]
            for match in cross_matches:
                cross_entry = dict(match)  # copy -- don't mutate the original
                cross_entry["field"] = "green-deal"
                cross_entry["tags"] = tag_legislation(
                    cross_entry["title"], cross_entry["summary"]
                )
                all_entries.append(cross_entry)
            if cross_matches:
                print(f"  +{len(cross_matches)} also surfaced under green-deal (cross-topic match)")

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
