"""
backend_scrapers.py

BeautifulSoup-based scrapers for think tanks / NGOs that do not publish an RSS
feed, for use alongside the feedparser-based sources in fetch_digest.py.

Each scrape_* function takes a single `cutoff` datetime and returns a list of
dicts shaped like:

    {
        "org": "CEPS",
        "field": "green-deal",
        "title": "...",
        "link": "https://...",
        "date": "2026-08-25",          # YYYY-MM-DD, or "unknown date"
        "summary": "...",
    }

Only items published on/after `cutoff` are returned. If an item's date can't
be parsed, it is included anyway with date="unknown date" rather than being
dropped.
"""

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

REQUEST_TIMEOUT = 10

FIELD = "green-deal"

# Max number of CEPS publication detail pages we will fetch to resolve a
# per-item date (the listing page itself does not expose a date - see
# scrape_ceps below). Keeps the scraper polite and fast.
CEPS_DETAIL_PAGE_CAP = 15


def _get_soup(url, params=None):
    """Fetch a URL and return a BeautifulSoup object, or None on failure."""
    resp = requests.get(url, headers=HEADERS, params=params, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _clean_text(text, max_len=600):
    """Collapse whitespace and truncate a plain-text string."""
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text


def _make_item(org, title, link, dt, summary):
    return {
        "org": org,
        "field": FIELD,
        "title": _clean_text(title, max_len=300),
        "link": link,
        "date": dt.strftime("%Y-%m-%d") if dt else "unknown date",
        "summary": _clean_text(summary),
    }


def _passes_cutoff(dt, cutoff):
    """An unparsed date (dt is None) always passes - we include it rather
    than silently drop it, per spec."""
    if dt is None:
        return True
    return dt >= cutoff


# ---------------------------------------------------------------------------
# CEPS
# ---------------------------------------------------------------------------
def scrape_ceps(cutoff):
    """
    https://www.ceps.eu/ceps-publications/

    The listing page is server-rendered with cards like:

        <div id="ut-post-card-58773" class="ut-post-card ...">
            <div class="ut-label ut-label-green"><a href="#...">Commissioned reports</a></div>
            <div class="ut-margin-top">
                <h3 class="ut-caption-title-xsmall"><a href="...">Title</a></h3>
            </div>
        </div>

    The listing cards carry no per-item date (only a
    data-publications-year="2026" attribute - year only). The date and a
    clean summary *are* available on each publication's own page:

        <meta property="article:published_time" content="2026-08-26T09:57:40+01:00">
        <meta property="og:description" content="...">

    So this scraper visits each publication's detail page to resolve the
    date/summary, capped at CEPS_DETAIL_PAGE_CAP (15) cards to stay polite
    and fast.
    """
    org = "CEPS"
    items = []
    try:
        soup = _get_soup("https://www.ceps.eu/ceps-publications/")
        cards = soup.select("div.ut-post-card")
        for card in cards[:CEPS_DETAIL_PAGE_CAP]:
            title_a = card.select_one("h3.ut-caption-title-xsmall a")
            if not title_a or not title_a.get("href"):
                continue
            title = title_a.get_text(strip=True)
            link = title_a["href"]

            dt = None
            summary = ""
            try:
                detail_soup = _get_soup(link)
                pub_meta = detail_soup.find(
                    "meta", attrs={"property": "article:published_time"}
                )
                if pub_meta and pub_meta.get("content"):
                    try:
                        dt = datetime.fromisoformat(pub_meta["content"])
                        if dt.tzinfo is not None:
                            dt = dt.replace(tzinfo=None)
                    except ValueError:
                        dt = None
                desc_meta = detail_soup.find(
                    "meta", attrs={"property": "og:description"}
                )
                if desc_meta and desc_meta.get("content"):
                    summary = desc_meta["content"]
            except requests.RequestException as exc:
                print(f"[backend_scrapers] CEPS detail fetch failed for {link}: {exc}")

            if not _passes_cutoff(dt, cutoff):
                continue
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_ceps failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Transport & Environment
# ---------------------------------------------------------------------------
def scrape_transport_environment(cutoff):
    """
    https://www.transportenvironment.org/articles

    Server-rendered cards (page 1 only - newest first, easily covers a
    7-10 day window):

        <a href="..." class="theme-white group block space-y-4">
            <span class="... text-theme-accent">Letter</span>
            <h3 class="t_h5 ...">Title</h3>
            <p class="t_body-s ...">Summary teaser...</p>
            <time ...>August 25, 2026</time>
        </a>
    """
    org = "Transport & Environment"
    items = []
    try:
        soup = _get_soup("https://www.transportenvironment.org/articles")
        cards = soup.select("a.group.block")
        for card in cards:
            link = card.get("href")
            title_el = card.select_one("h3")
            if not link or not title_el:
                continue
            title = title_el.get_text(strip=True)

            summary_el = card.select_one("p")
            summary = summary_el.get_text(strip=True) if summary_el else ""

            time_el = card.select_one("time")
            dt = None
            if time_el:
                date_text = time_el.get_text(strip=True)
                dt = _parse_date(date_text, ["%B %d, %Y"])

            if not _passes_cutoff(dt, cutoff):
                continue
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_transport_environment failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# PIK Potsdam
# ---------------------------------------------------------------------------
def scrape_pik_potsdam(cutoff):
    """
    https://www.pik-potsdam.de/en/news

    Server-rendered (Plone CMS) cards:

        <div class="summaryItem summaryItem--withImage">
            <div class="summaryItem__tags ...">Press Release</div>
            <div class="summaryItem__content">
                <h2 class="summaryItem__headline"><a href="...">Title</a></h2>
                <div class="summaryItem__description">
                    20.08.2026 - Summary text...
                </div>
            </div>
        </div>
    """
    org = "PIK Potsdam"
    items = []
    try:
        soup = _get_soup("https://www.pik-potsdam.de/en/news")
        cards = soup.select("div.summaryItem")
        for card in cards:
            headline_a = card.select_one("h2.summaryItem__headline a")
            if not headline_a or not headline_a.get("href"):
                continue
            title = headline_a.get_text(strip=True)
            link = headline_a["href"]

            desc_el = card.select_one("div.summaryItem__description")
            dt = None
            summary = ""
            if desc_el:
                desc_text = desc_el.get_text(strip=True)
                # Format observed: "20.08.2026 - Summary text..." (en-dash)
                if "–" in desc_text:
                    date_part, summary_part = desc_text.split("–", 1)
                elif "-" in desc_text[:12]:
                    date_part, summary_part = desc_text.split("-", 1)
                else:
                    date_part, summary_part = "", desc_text
                summary = summary_part.strip()
                dt = _parse_date(date_part.strip(), ["%d.%m.%Y"])

            if not _passes_cutoff(dt, cutoff):
                continue
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_pik_potsdam failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# IDDRI
# ---------------------------------------------------------------------------
def scrape_iddri(cutoff):
    """
    https://www.iddri.org/en/publications-and-events

    Server-rendered cards (the 3 "promoted" items at the top are also
    present in this same list, so we only need this one selector):

        <article class="line-teaser">
            <a href="/en/..." class="flex-content">
                <div class="publication__metas">
                    <span class="category category--publi">Issue Brief</span>
                    July 2026
                </div>
                <h3 class="line-teaser__title"><span>Title</span></h3>
                <ul class="teaser__authors ...">Author(s): ...</ul>
            </a>
        </article>

    IDDRI does not print an excerpt/teaser body in the listing HTML, only
    type/date/title/authors - so "summary" is built from the author byline
    (best available short text).

    Date granularity varies by publication type: Op-eds/Podcasts/Blog posts
    show a full date ("July 16th 2026"); Issue Briefs/Scientific
    publications often show only a month+year ("July 2026"). For the
    month-only case we approximate with the 1st of that month, which is
    good enough for a 7-10 day recency cutoff.
    """
    org = "IDDRI"
    items = []
    try:
        soup = _get_soup("https://www.iddri.org/en/publications-and-events")
        base_url = "https://www.iddri.org"
        articles = soup.select("article.line-teaser")
        for article in articles:
            a = article.select_one("a.flex-content")
            title_el = article.select_one("h3.line-teaser__title")
            if not a or not a.get("href") or not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = a["href"]
            if link.startswith("/"):
                link = base_url + link

            metas = article.select_one("div.publication__metas")
            dt = None
            if metas:
                metas_copy = BeautifulSoup(str(metas), "html.parser")
                type_span = metas_copy.select_one("span.category")
                if type_span:
                    type_span.decompose()
                date_text = metas_copy.get_text(strip=True)
                dt = _parse_iddri_date(date_text)

            authors_el = article.select_one("ul.teaser__authors")
            summary = authors_el.get_text(" ", strip=True) if authors_el else ""

            if not _passes_cutoff(dt, cutoff):
                continue
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_iddri failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------
def _parse_date(text, formats):
    text = (text or "").strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_iddri_date(text):
    """Handles: 'July 16th 2026', 'July 2026', '09 JUN 2026', 'July 2026 '."""
    text = (text or "").strip()
    if not text:
        return None
    # Strip ordinal suffixes: "16th" -> "16"
    text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", text)
    for fmt in ("%B %d %Y", "%d %b %Y", "%d %B %Y"):
        dt = _parse_date(text, [fmt])
        if dt:
            return dt
    # Month + year only (e.g. "July 2026") - approximate as the 1st.
    dt = _parse_date(text, ["%B %Y"])
    if dt:
        return dt
    return None


# ---------------------------------------------------------------------------
SCRAPERS = {
    "ceps": scrape_ceps,
    "transport_environment": scrape_transport_environment,
    "pik_potsdam": scrape_pik_potsdam,
    "iddri": scrape_iddri,
}
