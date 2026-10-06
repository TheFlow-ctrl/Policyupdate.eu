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
be confidently parsed, the item is EXCLUDED rather than included -- an
earlier "always include on unparseable date" behaviour let stale/irrelevant
items resurface every run regardless of actual age, so recency must be
confirmed, not assumed.
"""

import html
import re
from datetime import datetime
from urllib.parse import urljoin

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

# Same idea as CEPS_DETAIL_PAGE_CAP, for Orgalim's listing (also has no
# per-item date on the listing page itself -- see scrape_orgalim below).
ORGALIM_DETAIL_PAGE_CAP = 15

# Cap on CERRE publication detail-page fetches per run (see scrape_cerre
# below). Unlike CEPS/Orgalim, CERRE's REST API already gives a reliable
# per-item date, so the cutoff filter runs BEFORE this cap is applied --
# it only bounds the (usually much smaller) set of items already known to
# be within the current run's date window, not the full 20-item page.
CERRE_DETAIL_PAGE_CAP = 15

# WMO's news listing uses Tailwind utility classes rather than semantic
# ones for its date element, which are more likely to change/be
# regenerated than a real class name -- scrape_wmo() below parses the
# date out of the card's text via this regex instead of a brittle exact
# class-combination selector.
_WMO_DATE_RE = re.compile(
    r"\b\d{1,2} (?:January|February|March|April|May|June|July|August|"
    r"September|October|November|December) \d{4}\b"
)


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


def _make_item(org, title, link, dt, summary, image=None):
    return {
        "org": org,
        "field": FIELD,
        "title": _clean_text(title, max_len=300),
        "link": link,
        "date": dt.strftime("%Y-%m-%d") if dt else "unknown date",
        "summary": _clean_text(summary),
        # Optional -- for the Instagram-style "picture over caption" card
        # layout (see entry_image()/render_entry_html() in fetch_digest.py).
        # None for the large majority of scrapers in this file, which
        # were written before that feature existed and don't extract an
        # image URL from their listing page's DOM; only pass a real
        # value from a scraper that's been specifically checked to have
        # one in its confirmed-live markup, not guessed.
        "image": image,
    }


def _passes_cutoff(dt, cutoff):
    """An unparsed date (dt is None) does NOT pass - excluded rather than
    included. This is a "last N days" digest, so an item we can't confirm
    the recency of shouldn't be assumed recent; the earlier "always
    include" behaviour let stale/irrelevant items (e.g. an old outreach
    article with no clean date on the page) resurface in every run
    indefinitely."""
    if dt is None:
        return False
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
# Eurelectric
# ---------------------------------------------------------------------------
def scrape_eurelectric(cutoff):
    """
    https://www.eurelectric.org/news/

    Elementor "loop items". Each news card:
        <div class="e-loop-item ... type-news ...">
          <span class="elementor-heading-title">17 July 2026</span>
          <h3 class="elementor-heading-title"><a href="...">Title</a></h3>
          <div class="elementor-heading-title">Optional summary text</div>
        </div>
    (team-member cards on the same page use "type-team-member" instead of
    "type-news", so filtering on ".type-news" excludes them.)
    """
    org = "Eurelectric"
    items = []
    try:
        soup = _get_soup("https://www.eurelectric.org/news/")
        for card in soup.select("div.e-loop-item.type-news"):
            headings = card.select(".elementor-heading-title")
            if not headings:
                continue

            dt = _parse_date(headings[0].get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title_a = card.select_one(
                "h3.elementor-heading-title a, h2.elementor-heading-title a"
            )
            if not title_a or not title_a.get("href"):
                continue

            summary = ""
            for h in headings[1:]:
                if h.name == "div" and h.find("a") is None:
                    txt = h.get_text(strip=True)
                    if len(txt) > 40:
                        summary = txt
                        break

            items.append(_make_item(org, title_a.get_text(strip=True), title_a["href"], dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_eurelectric failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# European Climate Foundation
# ---------------------------------------------------------------------------
def scrape_european_climate_foundation(cutoff):
    """
    https://europeanclimate.org/news/ (the full archive -- /latest-updates/
    is only a 3-item teaser of the same feed).

        <div class="newsCard">
          <div class="text_box_head">28.07.2026 - News</div>
          <h3 class="h3"><a href="...">Title</a></h3>
          <p class="card_desc">Excerpt text...</p>
        </div>
    """
    org = "European Climate Foundation"
    items = []
    try:
        soup = _get_soup("https://europeanclimate.org/news/")
        for card in soup.select(".newsCard"):
            date_el = card.select_one(".text_box_head")
            title_a = card.select_one("h3 a, .h3 a")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            date_text = date_el.get_text(strip=True).split(" - ")[0].strip()
            dt = _parse_date(date_text, ["%d.%m.%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            desc_el = card.select_one(".card_desc, .news_desc")
            summary = desc_el.get_text(strip=True) if desc_el else ""

            items.append(_make_item(org, title_a.get_text(strip=True), title_a["href"], dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_european_climate_foundation failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# ClientEarth
# ---------------------------------------------------------------------------
def scrape_clientearth(cutoff):
    """
    https://www.clientearth.org/latest/ (combines "latest legal actions"
    and "latest news"; /news/ 404s).

        <a href="/latest/news/..." class="item newsitem">
          <p class="date">28 August 2026</p>
          <h5 class="title">Title</h5>
        </a>

    No excerpt text on the cards, so summary falls back to the title.
    """
    org = "ClientEarth"
    base = "https://www.clientearth.org"
    items = []
    try:
        soup = _get_soup("https://www.clientearth.org/latest/")
        for card in soup.select("a.newsitem"):
            date_el = card.select_one(".date")
            title_el = card.select_one(".title")
            href = card.get("href")
            if not date_el or not title_el or not href:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            items.append(_make_item(org, title, urljoin(base, href), dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_clientearth failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Agora Energiewende
# ---------------------------------------------------------------------------
def scrape_agora_energiewende(cutoff):
    """
    English listing at https://www.agora-energiewende.org/news-events
    (the German .de/aktuelles page links here for English content).

        <div class="teaser__body">
          <p class="teaser__date"><time>1 August 2026</time></p>
          <h3 class="teaser__title"><a href="/news-events/...">Title</a></h3>
          <dl class="teaser__meta-container"><dd class="teaser__format">News</dd></dl>
        </div>

    No excerpt text; summary falls back to "Format: Title". Some items
    link out to the sister site agora-industry.org -- urljoin handles
    both relative and absolute hrefs.
    """
    org = "Agora Energiewende"
    base = "https://www.agora-energiewende.org"
    items = []
    try:
        soup = _get_soup("https://www.agora-energiewende.org/news-events")
        for card in soup.select(".teaser__body"):
            date_el = card.select_one(".teaser__date time")
            title_a = card.select_one(".teaser__title a")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            format_el = card.select_one(".teaser__format")
            fmt = format_el.get_text(strip=True) if format_el else ""
            summary = f"{fmt}: {title}" if fmt else title

            items.append(_make_item(org, title, urljoin(base, title_a["href"]), dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_agora_energiewende failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# EPC (European Policy Centre)
# ---------------------------------------------------------------------------
def scrape_epc(cutoff):
    """
    https://www.epc.eu/publications/ (NOT /en/publications -- that 404s).

        <div class="publication-item">
          <div class="publication-item-title"><a href="/publication/...">Title</a></div>
          <div class="publication-item-date"><i class="fa fa-calendar-alt"></i> Aug 26, 2026</div>
          <div class="publication-item-topic"><span><a>TOPIC</a></span></div>
        </div>

    CAVEAT: a plain (non-browser) fetch was sometimes served a decoy
    "Error 404!" page (HTTP 200) instead of the real listing during
    development, possibly bot/WAF fingerprint filtering -- not confirmed
    JS-rendering. Defensive check below: if no .publication-item nodes are
    found, log a warning and return [] rather than emit garbage.
    """
    org = "EPC"
    base = "https://www.epc.eu"
    items = []
    try:
        soup = _get_soup("https://www.epc.eu/publications/")
        cards = soup.select(".publication-item")
        if not cards:
            print("[backend_scrapers] scrape_epc: no .publication-item nodes found "
                  "(possible bot/WAF block) -- returning no items this run")
            return []

        for card in cards:
            title_a = card.select_one(".publication-item-title a")
            date_el = card.select_one(".publication-item-date")
            if not title_a or not title_a.get("href") or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%b %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            topic_el = card.select_one(".publication-item-topic")
            topics = topic_el.get_text(" ", strip=True) if topic_el else ""
            summary = f"{title}. Topics: {topics}" if topics else title

            items.append(_make_item(org, title, urljoin(base, title_a["href"]), dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_epc failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# BC3 (Basque Centre for Climate Change)
# ---------------------------------------------------------------------------
def scrape_bc3(cutoff):
    """
    https://www.bc3research.org/en/newsroom/news/ (WPBakery grid, first
    page's items are present in the raw HTML, no JS needed).

        <div class="vc_grid-item">
          <div class="bc3postdate">August 5, 2026</div>
          <div class="bc3posttitle"><a href="...">Title</a></div>
          <div class="bc3postexcerpt"><p>Excerpt...</p></div>
        </div>

    Dates are consistently in English even though some titles/excerpts
    are in Spanish (BC3 publishes bilingually) -- that's expected.
    """
    org = "BC3"
    items = []
    try:
        soup = _get_soup("https://www.bc3research.org/en/newsroom/news/")
        for card in soup.select(".vc_grid-item"):
            date_el = card.select_one(".bc3postdate")
            title_a = card.select_one(".bc3posttitle a")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%B %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            excerpt_el = card.select_one(".bc3postexcerpt")
            summary = excerpt_el.get_text(strip=True) if excerpt_el else ""

            items.append(_make_item(org, title_a.get_text(strip=True), title_a["href"], dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_bc3 failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# EERA (European Energy Research Alliance)
# ---------------------------------------------------------------------------
def scrape_eera(cutoff):
    """
    https://www.eera-set.eu/news-resources.html (Joomla list; masonry
    repositioning is client-side JS but all content ships in raw HTML).

        <li class="element">
          <span class="badge">News</span>
          <span class="bl-desc">
            <h5>25 August 2026</h5>
            <p><a href="...">Title</a></p>
          </span>
        </li>

    Mixes News / Policy developments / Speakers corner / Videos &
    Interviews / Newsletters under one badge label -- kept all, badge
    recorded as part of the summary.
    """
    org = "EERA"
    items = []
    try:
        soup = _get_soup("https://www.eera-set.eu/news-resources.html")
        for card in soup.select("li.element"):
            date_el = card.select_one(".bl-desc h5")
            title_a = card.select_one(".bl-desc p a")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            badge_el = card.select_one(".badge")
            badge = badge_el.get_text(strip=True) if badge_el else ""
            summary = f"{badge}: {title}" if badge else title

            items.append(_make_item(org, title, title_a["href"], dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_eera failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Cefic (European chemical industry association)
# ---------------------------------------------------------------------------
CEFIC_DETAIL_PAGE_CAP = 15


def scrape_cefic(cutoff):
    """
    https://cefic.org/news/ (WordPress; block wp-block-cefic-generic-card).

        <article class="news-card ... wp-block-cefic-generic-card">
          <a class="card__title" href="https://cefic.org/news/<slug>/">Title</a>
          <div class="wp-block-cefic-post-terms">
            <div class="cefic-term"><span class="cefic-term__term">Topic</span></div>
          </div>
          <div class="card__date">17 July 2026</div>
        </article>

    No excerpt on the listing -- for each item (capped at
    CEFIC_DETAIL_PAGE_CAP) we visit the article page and pull
    <meta name="description">/<meta property="og:description"> for the
    summary; on failure, falls back to the topic-tag list.
    """
    org = "Cefic"
    items = []
    try:
        soup = _get_soup("https://cefic.org/news/")
        cards = soup.select("article.news-card")
        detail_fetches = 0

        for card in cards:
            title_a = card.select_one("a.card__title")
            date_el = card.select_one("div.card__date")
            if not title_a or not title_a.get("href") or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            tags = [t.get_text(strip=True) for t in card.select("span.cefic-term__term")]

            summary = ""
            if detail_fetches < CEFIC_DETAIL_PAGE_CAP:
                detail_fetches += 1
                try:
                    detail_soup = _get_soup(link)
                    meta = detail_soup.select_one(
                        'meta[name="description"], meta[property="og:description"]'
                    )
                    if meta and meta.get("content"):
                        summary = meta["content"]
                except requests.RequestException as exc:
                    print(f"[backend_scrapers] Cefic detail fetch failed for {link}: {exc}")

            if not summary:
                summary = ", ".join(tags) if tags else title

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_cefic failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Eurofer (European steel industry association)
# ---------------------------------------------------------------------------
_MONTH_RE = (
    r"January|February|March|April|May|June|July|August|"
    r"September|October|November|December"
)
_DATE_IN_TEXT_RE = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_RE})\s+(\d{{4}})\b")
_EUROFER_TITLE_PREFIX_RE = re.compile(r"^(press\s+release|press\s+statement)\s*:\s*", re.IGNORECASE)


def scrape_eurofer(cutoff):
    """
    https://www.eurofer.eu/press-room/press-releases (Mobirise static
    site; plain crawlable HTML).

        <div class="card p-3 col-12 col-md-6">
          <a class="btn btn-primary" href="/press-releases/<slug>">Learn More</a>
          <h4 class="card-title"><strong>Press release: Title</strong></h4>
          <p class="mbr-text">Brussels, 16 July 2026 - Lead paragraph...</p>
        </div>

    No dedicated date field -- the date is the leading "Brussels, D Month
    YYYY" clause of the lead paragraph, which also doubles as the summary
    once that dateline is stripped off. The same cards repeat across
    several hidden tag-filter sections, so results are deduped by link.
    """
    org = "Eurofer"
    base = "https://www.eurofer.eu"
    items = []
    seen_links = set()
    try:
        soup = _get_soup("https://www.eurofer.eu/press-room/press-releases")
        for card in soup.select("div.card.p-3.col-12.col-md-6"):
            link_a = card.select_one("a.btn.btn-primary")
            title_el = card.select_one("h4.card-title")
            text_el = card.select_one("p.mbr-text")
            if not link_a or not title_el or not text_el:
                continue

            href = link_a.get("href", "").strip()
            if not href:
                continue
            link = urljoin(base, href)
            if link in seen_links:
                continue
            seen_links.add(link)

            raw_text = text_el.get_text(" ", strip=True)
            match = _DATE_IN_TEXT_RE.search(raw_text)
            if not match:
                continue
            day, month, year = match.groups()
            dt = _parse_date(f"{day} {month} {year}", ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = _EUROFER_TITLE_PREFIX_RE.sub(
                "", title_el.get_text(strip=True)
            ).strip()
            summary = raw_text[match.end():].lstrip(" -–—:") or raw_text

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_eurofer failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Zenodo (EU Open Research Repository)
# ---------------------------------------------------------------------------
# Zenodo has a JSON REST API but no RSS/Atom feed, so it can't go through
# feedparser like the other academic sources -- confirmed by a research
# agent inspecting the site's DOM for feed links (none found). This scraper
# queries https://zenodo.org/api/records directly instead.
#
# ZENODO_QUERY_TERMS is a flat OR of quoted phrases -- deliberately simple
# Elasticsearch query syntax (no field prefixes, no nested AND/OR grouping)
# to avoid a malformed query silently returning zero results. It's a mix of
# EU Green Deal law names (which are unambiguous on their own) and a few
# generic "EU + climate/energy policy" phrase combos. This is Zenodo's own
# relevance search, separate from (and in addition to) the site's own
# is_relevant()/is_eu_relevant() keyword filter that later runs on whatever
# this returns (actor_type: academic triggers both).
ZENODO_QUERY_TERMS = [
    "European Green Deal", "EU Green Deal", "Fit for 55", "CBAM",
    "carbon border adjustment", "EU Emissions Trading System", "EU ETS",
    "Nature Restoration Law", "Corporate Sustainability Due Diligence Directive",
    "Net Zero Industry Act", "Critical Raw Materials Act", "EU Taxonomy Regulation",
    "Sustainable Finance Disclosure Regulation", "EU Deforestation Regulation",
    "Energy Efficiency Directive", "EU climate policy", "EU energy policy",
    "European Union climate policy", "European Union energy policy",
]
ZENODO_QUERY = " OR ".join(f'"{t}"' for t in ZENODO_QUERY_TERMS)
ZENODO_PAGE_SIZE = 30

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def scrape_zenodo(cutoff):
    """
    https://zenodo.org/api/records?q=...&sort=mostrecent&size=30

    Response shape (Zenodo REST API v1):
        {"hits": {"hits": [
            {"id": 1234567,
             "metadata": {"title": "...", "description": "<p>...</p>",
                          "publication_date": "2026-08-28", ...},
             ...},
            ...
        ]}}

    The record's public URL is built from its numeric id
    (zenodo.org/records/<id>) rather than trusted from a links.* field --
    Zenodo's exact links.* key naming wasn't independently confirmed, while
    the id-based URL pattern is documented and stable.
    """
    org = "Zenodo"
    items = []
    try:
        resp = requests.get(
            "https://zenodo.org/api/records",
            headers=HEADERS,
            params={"q": ZENODO_QUERY, "sort": "mostrecent", "size": ZENODO_PAGE_SIZE},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])

        for record in hits:
            record_id = record.get("id")
            metadata = record.get("metadata", {})
            title = metadata.get("title")
            if not record_id or not title:
                continue

            dt = _parse_date(metadata.get("publication_date", ""), ["%Y-%m-%d"])
            if not _passes_cutoff(dt, cutoff):
                continue

            link = f"https://zenodo.org/records/{record_id}"
            raw_description = metadata.get("description", "")
            summary = html.unescape(_HTML_TAG_RE.sub(" ", raw_description))

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_zenodo failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# industriAll Europe (trade union -- industry & manufacturing workers)
# ---------------------------------------------------------------------------
def scrape_industriall_europe(cutoff):
    """
    https://news.industriall-europe.eu/News (custom ASP.NET-style CMS, no
    RSS feed anywhere on the site -- confirmed via browser DOM inspection).

    Server-rendered cards (confirmed against the live page, not guessed):

        <div class="light-article">
          <a class="light-article-image" href="/Article/1597">
            <img ... alt="Title" src="...">
          </a>
          <div class="light-article-text">
            <a href="/Article/1597">
              <div>
                <h4>Title</h4>
                <p>
                  <span class="date">Wednesday 23 September 2026</span> - Summary...<br>
                </p>
              </div>
            </a>
            <a class="tag-item" href="/Tag/179"><span id="179">TAG</span></a>
            ...
          </div>
        </div>

    Date format is "%A %d %B %Y" (full weekday name included). Summary is
    the <p> text with the leading "<date> - " clause stripped off; falls
    back to the title if there's no " - " separator (a few items, e.g.
    short wire-service republishes, have no lead-in text before the ellipsis).
    """
    org = "industriAll Europe"
    base = "https://news.industriall-europe.eu"
    items = []
    try:
        soup = _get_soup("https://news.industriall-europe.eu/News")
        for card in soup.select("div.light-article"):
            text_a = card.select_one("div.light-article-text > a")
            title_el = card.select_one("h4")
            date_el = card.select_one("span.date")
            p_el = card.select_one("p")
            if not text_a or not text_a.get("href") or not title_el or not date_el or not p_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%A %d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, text_a["href"])
            full_text = p_el.get_text(" ", strip=True)
            summary = full_text.split(" - ", 1)[1].strip() if " - " in full_text else title

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_industriall_europe failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Fern (forests -- EUDR-relevant NGO)
# ---------------------------------------------------------------------------
def scrape_fern(cutoff):
    """
    https://www.fern.org/publications-insight/news/ (TYPO3 CMS, ll_catalog
    extension). Confirmed structure via live DOM inspection:

        <div class="record">
          <a href="/publications-insight/article/<slug>/">
            <div class="photo">...</div>
            <div class="details">
              <h4 class="variant">News</h4>
              <h2>Title</h2>
              <p>Teaser paragraph one...</p>
              <p>Teaser paragraph two...</p>
              <p class="date">18/09/2026</p>
            </div>
          </a>
        </div>

    Date is day-first (%d/%m/%Y). Summary is every <p> inside .details
    except the date paragraph, joined together (there are usually two
    short teaser paragraphs, no single one is reliably "the" excerpt).
    """
    org = "Fern"
    base = "https://www.fern.org"
    items = []
    try:
        soup = _get_soup("https://www.fern.org/publications-insight/news/")
        for card in soup.select("div.record"):
            a = card.select_one("a")
            title_el = card.select_one("h2")
            date_el = card.select_one("p.date")
            if not a or not a.get("href") or not title_el or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d/%m/%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, a["href"])
            teaser_ps = [
                p.get_text(strip=True)
                for p in card.select("div.details > p")
                if p is not date_el
            ]
            summary = " ".join(teaser_ps).strip() or title

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_fern failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Cement Europe (formerly CEMBUREAU -- cement industry, a CBAM sector)
# ---------------------------------------------------------------------------
def scrape_cembureau(cutoff):
    """
    https://www.cementeurope.eu/resources/press-releases/ -- CEMBUREAU
    rebranded to "Cement Europe" in October 2025 (see the "From CEMBUREAU
    to Cement Europe" press release in their own archive); cembureau.eu
    redirects here. Confirmed structure via live DOM inspection:

        <div class="... resource_grid_col" data-title="Title text"
             data-type="Press Release" data-topics="Climate &amp; CO2 Strategy">
          <div class="resource_grid_tile">
            <div class="resource_grid_details">
              <div class="resource_grid_date ...">
                <span class="resource_grid_type"></span>
                <span class="resource_grid_date">17 July 2026</span>
              </div>
              <div class="resource_grid_title"><span>Title text</span></div>
              <div class="resource_grid_action">
                <a href="/media/.../press-release.pdf" target="_blank">Download</a>
              </div>
            </div>
          </div>
        </div>

    Each press release IS a PDF -- there's no separate HTML landing page,
    so the entry links straight to the PDF (same pattern as other
    PDF-only press outlets elsewhere in this pipeline). No excerpt text on
    the listing; falls back to the data-topics tag (e.g. "Climate & CO2
    Strategy"), or the title if that's also empty.
    """
    org = "Cement Europe (CEMBUREAU)"
    base = "https://www.cementeurope.eu"
    items = []
    try:
        soup = _get_soup("https://www.cementeurope.eu/resources/press-releases/")
        for card in soup.select("div[data-title]"):
            title = (card.get("data-title") or "").strip()
            date_el = card.select_one("span.resource_grid_date")
            link_el = card.select_one("div.resource_grid_action a")
            if not title or not date_el or not link_el or not link_el.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            link = urljoin(base, link_el["href"])
            topics = (card.get("data-topics") or "").strip()
            summary = topics or title

            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_cembureau failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# IETA (International Emissions Trading Association -- carbon markets/ETS)
# ---------------------------------------------------------------------------
def scrape_ieta(cutoff):
    """
    https://www.ieta.org/news (server-rendered, though the page also
    carries a lot of client-side chrome). Confirmed structure via live DOM
    inspection:

        <div class="col-border-inner card-news">
          <figure><img ...></figure>
          <div class="card-body pt-0 pb-0">
            <h3 class="news-title mt-0">Title</h3>
            <div class="resource-date mb-1">Sep 21, 2026</div>
          </div>
          <a href="https://www.ieta.org/news/<slug>" class="link-cover"></a>
        </div>

    No excerpt text on the listing; summary falls back to the title (same
    as ClientEarth's scraper above -- IETA's cards don't carry one either).
    """
    org = "IETA"
    items = []
    try:
        soup = _get_soup("https://www.ieta.org/news")
        for card in soup.select("div.card-news"):
            title_el = card.select_one("h3.news-title")
            date_el = card.select_one("div.resource-date")
            link_el = card.select_one("a.link-cover")
            if not title_el or not date_el or not link_el or not link_el.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%b %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            items.append(_make_item(org, title, link_el["href"], dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_ieta failed: {exc}")
        return []
    return items


def scrape_euromines(cutoff):
    """
    https://euromines.org/news/ (WordPress + Elementor + a "Unite Loop"-style
    filterable-list shortcode plugin, no RSS feed anywhere on the site --
    confirmed via browser DOM inspection). Server-rendered cards:

        <article class="ul-card ul-card--blue-split">
          <div class="ul-card--blue-split__content">
            <div class="ul-card--blue-split__date">22 September 2026</div>
            <h3 class="ul-card--blue-split__title">
              <a href="https://euromines.org/member-spotlight-.../">Title</a>
            </h3>
            <div class="ul-card--blue-split__excerpt">Summary...</div>
          </div>
          <div class="ul-card--blue-split__cta">
            <a class="ul-btn--view" href="...">More Details</a>
          </div>
        </article>

    Date format is "%d %B %Y" (no leading zero, confirmed against both
    "22 September 2026" and "8 September 2026"). Mining/raw-materials trade
    body -- CRMA and permitting reform are the main EU-policy angle.
    """
    org = "Euromines"
    items = []
    try:
        soup = _get_soup("https://euromines.org/news/")
        for card in soup.select("article.ul-card--blue-split"):
            date_el = card.select_one(".ul-card--blue-split__date")
            title_a = card.select_one(".ul-card--blue-split__title a")
            excerpt_el = card.select_one(".ul-card--blue-split__excerpt")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            summary = excerpt_el.get_text(strip=True) if excerpt_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_euromines failed: {exc}")
        return []
    return items


def scrape_eurogas(cutoff):
    """
    https://www.eurogas.org/resources/news-press-releases/ (WordPress with a
    custom "search-filter" plugin; the site's own /feed/ endpoint exists but
    reliably returns zero <item> entries -- confirmed on two separate
    checks -- so this scrapes the actual listing page instead). Server-
    rendered cards:

        <div class="list-item news">           <!-- or "list-item press-release" -->
          <div class="list-item-wrapper has-image">
            <a class="list-thumbnail" href="...">...</a>
            <div class="list-content-wrapper">
              <div class="list-content-header">
                <span class="list-tag">News</span>   <!-- or "Press Release" -->
              </div>
              <div class="list-content-body">
                <h4 class="list-title"><a href="...">Title</a></h4>
              </div>
              <div class="list-content-footer">
                <a class="list-read-more">Read more</a>
                <span class="list-date">27/07/2026</span>
              </div>
            </div>
          </div>
        </div>

    Date format is "%d/%m/%Y". No excerpt text on the listing; summary
    falls back to the title (same as IETA/ClientEarth above). Mix of actual
    policy press releases and routine internal news (hiring, new members)
    -- left as-is since the pipeline's own keyword filter screens for
    relevance, same approach as every other broad-feed source in this file.
    """
    org = "Eurogas"
    items = []
    try:
        soup = _get_soup("https://www.eurogas.org/resources/news-press-releases/")
        for card in soup.select("div.list-item"):
            title_a = card.select_one(".list-title a")
            date_el = card.select_one(".list-date")
            if not title_a or not title_a.get("href") or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d/%m/%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_eurogas failed: {exc}")
        return []
    return items


def scrape_influencemap(cutoff):
    """
    https://influencemap.org/reports (custom CMS, no RSS feed). Server-
    rendered cards -- confirmed via live DOM inspection:

        <div class="imcard imcard-briefing imcard-lobbymap ...">
          <div class="row"><div class="col-sm-12">
            <a href="/briefing/EU-Emissions-Trading-System-...-39984">
              <div class="imcard-image"><img ...></div>
            </a>
          </div></div>
          <div class="row"><div class="col-sm-12"><div class="imcard-inner">
            <a href="/briefing/...-39984"><h3>Title</h3></a>
            <h4 class="timestamp">September 2026</h4>
            <p>Summary...</p>
            <div class="macro-tag-list tag-list">...</div>
          </div></div></div>
        </div>

    Date format is "%B %Y" -- month + year only, no day (defaults to the
    1st via strptime, which is fine for a "last N days" cutoff check at
    this granularity). Report links are relative (/briefing/...), joined
    against the site root. InfluenceMap's own corporate-lobbying research
    is squarely this tracker's beat -- covers EU ETS, CBAM-adjacent heavy
    industry, and sector-specific climate-policy engagement analysis.
    """
    org = "InfluenceMap"
    base = "https://influencemap.org"
    items = []
    try:
        soup = _get_soup("https://influencemap.org/reports")
        for card in soup.select("div.imcard"):
            title_el = card.select_one("h3")
            date_el = card.select_one("h4.timestamp")
            link_el = card.select_one("a[href]")
            summary_el = card.select_one("p")
            if not title_el or not date_el or not link_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, link_el["href"])
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_influencemap failed: {exc}")
        return []
    return items


def scrape_copa_cogeca(cutoff):
    """
    https://www.copa-cogeca.eu/press-releases -- the listing itself is a
    DevExtreme JS data grid with no server-rendered rows (a plain fetch
    only returns the empty grid shell), but it turned out to be backed by
    a plain, unauthenticated JSON API, found via live network-request
    inspection while the grid loaded:

        GET /pluriworks/v1/Publications?action=Get&skip=0&take=<n>
            &requireTotalCount=true&sort=[{"selector":"Date","desc":true}]
            &category=&prefilter=Custom.WebsiteSection=1

    Response shape (confirmed against a live pull):
        {"data": [
            {"ThreadID": 13656212,
             "Name": "Press Release - ...",
             "Date": "2026-09-15T14:39:38.787",   # local time, no tz suffix
             "Files": [
                {"ID": 13656227, "Language": "en", "Extension": ".docx",
                 "Title": "..."},
                {"ID": 13657110, "Language": "de", ...}, ...
             ]},
            ...
        ]}

    No plain-language excerpt in the payload -- summary falls back to the
    title, same as several RSS-less industry sources above. No HTML
    landing page either: every item is a multi-language document bundle,
    so the link goes straight to the English .docx via
    /Flexpage/DownloadFile/?id=<file id> (falls back to whichever language
    comes first if no English file is listed) -- same "link straight to a
    document, not a webpage" pattern as Cement Europe's press releases.
    This is an internal API, not a documented public interface, so it
    could change or start requiring auth without notice -- unlike the
    other scrapers in this file it isn't HTML-selector-fragile, but it is
    endpoint-fragile in its own way.
    """
    org = "Copa-Cogeca"
    base = "https://www.copa-cogeca.eu"
    items = []
    try:
        resp = requests.get(
            f"{base}/pluriworks/v1/Publications",
            headers=HEADERS,
            params={
                "action": "Get",
                "skip": 0,
                "take": 40,
                "requireTotalCount": "true",
                "sort": '[{"selector":"Date","desc":true}]',
                "category": "",
                "prefilter": "Custom.WebsiteSection=1",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        for entry in resp.json().get("data", []):
            title = entry.get("Name")
            if not title:
                continue
            dt = _parse_date(entry.get("Date", ""), ["%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"])
            if not _passes_cutoff(dt, cutoff):
                continue

            files = entry.get("Files") or []
            file_ = next((f for f in files if f.get("Language") == "en"), None) or (files[0] if files else None)
            if not file_ or not file_.get("ID"):
                continue

            link = f"{base}/Flexpage/DownloadFile/?id={file_['ID']}"
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_copa_cogeca failed: {exc}")
        return []
    return items


def scrape_council_eu(cutoff):
    """
    https://www.consilium.europa.eu/en/press/press-releases/ (Council of
    the EU + European Council joint press listing, "GSC" CMS). Server-
    rendered cards -- confirmed via live DOM inspection:

        <li class="gsc-excerpt-item" data-theme="ceu">
          <a class="gsc-excerpt-item__link" href="/en/press/press-releases/2026/09/25/...">
            <div class="gsc-excerpt-item__header">
              <span class="gsc-excerpt-item__title ...">Title</span>
              <time datetime="9/25/2026 1:10:00 PM" class="gsc-date__date gsc-time-badge">13:10</time>
            </div>
            <div id="excerpt-text"><p>Summary...</p></div>
            <footer class="gsc-excerpt-item__footer">
              <span class="gsc-tag">Council of the EU</span>  <!-- or "European Council" -->
            </footer>
          </a>
        </li>

    Uses the <time datetime="..."> attribute rather than the human "13:10"
    text -- it carries the full date, format "%m/%d/%Y %I:%M:%S %p".
    Covers both the Council of the EU and the European Council (the
    gsc-tag footer distinguishes them, not split into separate feeds here
    since both bodies' press releases matter for this tracker and the
    volume doesn't warrant it). Caution: this domain sits behind
    Cloudflare, and one browser session hit an interactive "verify you're
    human" challenge on this exact URL while a separate plain HTTP fetch
    on the same URL, and a later browser reload, both got real content
    straight through -- the challenge appears intermittent/session-based
    rather than a hard block, but a run could still occasionally return
    zero items if it's re-triggered. _get_soup's normal try/except means
    that shows up as an empty result for this source that run, not a
    crash of the whole pipeline.
    """
    org_ceu = "Council of the EU"
    org_euco = "European Council"
    base = "https://www.consilium.europa.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/en/press/press-releases/")
        for card in soup.select("li.gsc-excerpt-item"):
            link_el = card.select_one("a.gsc-excerpt-item__link")
            title_el = card.select_one(".gsc-excerpt-item__title")
            time_el = card.select_one("time")
            text_el = card.select_one("#excerpt-text p")
            tag_el = card.select_one(".gsc-tag")
            if not link_el or not link_el.get("href") or not title_el or not time_el:
                continue

            dt = _parse_date(time_el.get("datetime", ""), ["%m/%d/%Y %I:%M:%S %p"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, link_el["href"])
            summary = text_el.get_text(strip=True) if text_el else title
            tag = tag_el.get_text(strip=True) if tag_el else ""
            org = org_euco if "european council" in tag.lower() else org_ceu
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_council_eu failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
def scrape_acer(cutoff):
    """
    https://acer.europa.eu/news-and-events/news (Drupal "Views" listing --
    note the canonical/working host is the bare acer.europa.eu, not
    www.acer.europa.eu; the www host intermittently failed to load in
    testing while the bare host worked reliably both via a plain HTTP
    fetch and a real browser). No RSS feed found anywhere on the site.
    Server-rendered cards, confirmed via live DOM inspection:

        <div class="views-row row col-12">
          <div class="related-news-wrapper ...">
            <div class="related-new-date">22nd September 2026</div>
            <div class="title-wrapper">
              <a href="/news/acer-amends-...">Title</a>
            </div>
            <div class="intro-wrapper">Summary...</div>
            <a class="btn-related ..." href="/news/acer-amends-...">Read More</a>
          </div>
          <div class="news-list-img ...">...</div>
        </div>

    Date includes an ordinal suffix ("22nd", "1st", "3rd") which is
    stripped before parsing (same technique as IDDRI's scraper). EU energy
    regulator -- grid/electricity market rules, cross-border capacity,
    REMIT, hydrogen market monitoring: directly Green Deal/energy-
    transition relevant, if a bit technical/niche in tone.
    """
    org = "ACER"
    base = "https://acer.europa.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/news-and-events/news")
        for card in soup.select("div.views-row"):
            date_el = card.select_one(".related-new-date")
            title_a = card.select_one(".title-wrapper a")
            summary_el = card.select_one(".intro-wrapper")
            if not date_el or not title_a or not title_a.get("href"):
                continue

            date_text = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", date_el.get_text(strip=True))
            dt = _parse_date(date_text, ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = urljoin(base, title_a["href"])
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_acer failed: {exc}")
        return []
    return items


def scrape_orgalim(cutoff):
    """
    https://orgalim.eu/en/news/ (WordPress + a custom "lazyblock" news
    listing widget). No RSS feed. Server-rendered cards, but with NO
    per-item date anywhere in the listing markup -- not even hidden:

        <div class="row pb-4 news-item-wrapper clickable-row">
          <div class="d-flex align-items-center">
            <div class="news-menu-item-image col-md-6 me-3">...</div>
            <div class="col-md-6">
              <div class="news-menu-item-title mb-2">
                <h4><a href="https://orgalim.eu/en/<slug>/">Title</a></h4>
              </div>
              <div class="news-menu-item-cta mt-auto">
                <a href="...">Learn more ...</a>
              </div>
            </div>
          </div>
        </div>

    So, same approach as scrape_ceps() above: visits each article's own
    page to resolve the date/summary from its OpenGraph meta tags
    (confirmed live -- article:published_time and og:description are
    both present), capped at ORGALIM_DETAIL_PAGE_CAP to stay polite and
    fast. Represents Europe's technology industries (engineering,
    machinery, electronics) -- Ecodesign, circular economy, industrial
    strategy relevant.
    """
    org = "Orgalim"
    items = []
    try:
        soup = _get_soup("https://orgalim.eu/en/news/")
        cards = soup.select("div.news-item-wrapper")
        for card in cards[:ORGALIM_DETAIL_PAGE_CAP]:
            title_a = card.select_one("h4 a")
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
                desc_meta = detail_soup.find("meta", attrs={"property": "og:description"})
                if desc_meta and desc_meta.get("content"):
                    summary = desc_meta["content"]
            except requests.RequestException as exc:
                print(f"[backend_scrapers] Orgalim detail fetch failed for {link}: {exc}")

            if not _passes_cutoff(dt, cutoff):
                continue
            items.append(_make_item(org, title, link, dt, summary or title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_orgalim failed: {exc}")
        return []
    return items


def scrape_iea(cutoff):
    """
    https://www.iea.org/news. No RSS feed found. Server-rendered cards,
    confirmed via live DOM inspection:

        <div class="m-news-detailed-listing">
          <a href="/news/<slug>" class="m-news-detailed-listing__link">
            <div class="m-news-detailed-listing__content">
              <span class="a-tag-small">electrification</span>
              <h5 class="m-news-detailed-listing__title">
                <span class="m-news-detailed-listing__hover">Title</span>
              </h5>
            </div>
            <div class="m-news-detailed-listing__img">
              <div class="m-news-detailed-listing__date">22 September 2026</div>
              ...
            </div>
          </a>
        </div>

    Date format "%d %B %Y". No excerpt on the listing; summary falls back
    to the title. Global energy authority (World Energy Outlook etc.) --
    not an EU institution, so this is one of the "international-org"
    actor_type sources this project runs through a stricter relevance
    gate (see is_io_relevant() in fetch_digest.py): EU-specific energy-
    security coverage (e.g. "EU phase-out of Russian gas...") is common
    enough on this feed to be worth including, but a lot of the firehose
    is generically global (India, China, US energy news) and gets
    filtered back out by that gate.
    """
    org = "IEA"
    base = "https://www.iea.org"
    items = []
    try:
        soup = _get_soup(f"{base}/news")
        for card in soup.select("div.m-news-detailed-listing"):
            link_el = card.select_one("a.m-news-detailed-listing__link")
            title_el = card.select_one(".m-news-detailed-listing__title")
            date_el = card.select_one(".m-news-detailed-listing__date")
            if not link_el or not link_el.get("href") or not title_el or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, link_el["href"])
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_iea failed: {exc}")
        return []
    return items


def scrape_unep(cutoff):
    """
    https://www.unep.org/news-and-stories. No RSS feed found. Server-
    rendered cards, confirmed via live DOM inspection:

        <div class="news_whitearea_additional_item">
          <img ...>
          <div class="news_whitearea_item_text">
            <div class="news_whitearea_item_text_meta">
              02 Sep 2026
              | Story
            </div>
            <a href="/news-and-stories/story/<slug>">Title</a>
          </div>
        </div>

    Date format "%d %b %Y" -- the meta div mixes the date and content
    type together separated by "|", so the date is everything before
    that separator. Only the ~6 most-recent items are on this block (no
    pagination scraped) -- UNEP publishes often enough that this is fine
    for a weekly digest. Global remit, not an EU institution -- see
    is_io_relevant() in fetch_digest.py for the stricter gate this
    actor_type goes through; this is exactly the source the "1.5C /
    global warming" half of that gate was built for (e.g. the live
    "World set to cross 1.5C global warming" item seen at check time).
    """
    org = "UNEP"
    base = "https://www.unep.org"
    items = []
    try:
        soup = _get_soup(f"{base}/news-and-stories")
        for card in soup.select("div.news_whitearea_additional_item"):
            title_a = card.select_one(".news_whitearea_item_text a")
            meta_el = card.select_one(".news_whitearea_item_text_meta")
            if not title_a or not title_a.get("href") or not meta_el:
                continue

            meta_text = meta_el.get_text(" ", strip=True)
            date_text = meta_text.split("|")[0].strip()
            dt = _parse_date(date_text, ["%d %b %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = urljoin(base, title_a["href"])
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_unep failed: {exc}")
        return []
    return items


def scrape_wmo(cutoff):
    """
    https://wmo.int/news. No RSS feed found. Server-rendered cards
    (Drupal, but styled with Tailwind utility classes rather than
    semantic ones -- the date is parsed out of the card's text via
    _WMO_DATE_RE rather than chasing a specific utility-class combination
    that's more likely to be regenerated/changed than a real class name):

        <div class="views-row">
          <a href="/media/news/<slug>" class="...">
            <article class="...">
              <figure>...</figure>
              <div class="...">
                <div class="...">News</div>
                <span class="...">25 September 2026</span>
              </div>
              <h2 class="...">Title</h2>
            </article>
          </a>
        </div>

    Global remit, not an EU institution -- see is_io_relevant() in
    fetch_digest.py for the stricter gate this actor_type goes through.
    This is the definitive "state of the global climate" voice (record-
    heat / temperature-goal reporting), exactly the kind of content that
    gate's global-benchmark half exists to keep even without an EU angle.
    """
    org = "WMO"
    base = "https://wmo.int"
    items = []
    try:
        soup = _get_soup(f"{base}/news")
        for card in soup.select("div.views-row"):
            link_el = card.select_one("a[href]")
            title_el = card.select_one("h2")
            if not link_el or not link_el.get("href") or not title_el:
                continue

            card_text = card.get_text(" ", strip=True)
            date_match = _WMO_DATE_RE.search(card_text)
            dt = _parse_date(date_match.group(0), ["%d %B %Y"]) if date_match else None
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, link_el["href"])
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_wmo failed: {exc}")
        return []
    return items


def scrape_insurance_europe(cutoff):
    """
    https://www.insuranceeurope.eu/news. No RSS feed found. Server-
    rendered cards (Umbraco-based CMS), confirmed via a plain fetch --
    no JS rendering needed, unlike ECHA/ECA:

        <div class="inner">
          <div class="tag property">Climate change</div>
          <h3 class="property title">
            <a href="/news/3589/insurance-europe-comments-...">Title</a>
          </h3>
          <div class="date bottom property">23-6-2026</div>
        </div>

    Selecting on `h3.property.title a` rather than the containing
    `.el-objectnews` wrapper: the page nests a second, near-duplicate
    `.el-objectnews` div directly inside the first one for the same
    article (confirmed via live DOM inspection), so selecting the
    wrapper class would double-count every item -- the title link is the
    one element that appears exactly once per article. Mix of genuine
    EU climate/sustainable-finance content (EU Taxonomy, EIOPA natural-
    catastrophe risk, Solvency II) and routine insurance-sector news
    (Solvency II filings, DEI, PRIIPs) -- relies on the standard
    keyword filter to surface the Green Deal-relevant items, same as
    other broad industry-association sources in this file.
    """
    org = "Insurance Europe"
    base = "https://www.insuranceeurope.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/news")
        for title_a in soup.select("h3.property.title a[href]"):
            inner = title_a.find_parent("div", class_="inner")
            date_el = inner.select_one(".date.bottom.property") if inner else None
            if not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d-%m-%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = urljoin(base, title_a["href"])
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_insurance_europe failed: {exc}")
        return []
    return items


def scrape_climate_bonds(cutoff):
    """
    https://www.climatebonds.net/resources/press-releases (redirects to
    /news-events/press-room/press-releases). No RSS feed found. Server-
    rendered cards, confirmed via a plain fetch:

        <div class="card w-full h-fit ...">
          <a href="https://www.climatebonds.net/news-events/.../slug"
             class="stretched-link ...">Title</a>
          <div class="text-azure ..."><p>25 September 2026</p></div>
        </div>

    Selecting on the semantic "card" class only (not the full Tailwind
    utility-class combination, which is more likely to be regenerated --
    same reasoning as WMO's card selector above). Genuinely global (this
    is a UK-registered charity setting green/sustainable-bond standards
    worldwide -- live examples seen at check time: press releases about
    Japan, Guatemala, Trinidad & Tobago, Australia, China), so this
    source is marked eu_gate: true in sources.yaml -- see
    apply_relevance_filter()'s eu_gate handling in fetch_digest.py. Some
    press releases are duplicated in a local language (e.g. a Japanese-
    and English-language version of the same story); harmless since the
    EU-specificity gate rejects both unless the underlying story is
    actually EU-relevant.
    """
    org = "Climate Bonds Initiative"
    items = []
    try:
        soup = _get_soup("https://www.climatebonds.net/resources/press-releases")
        for card in soup.select("div.card"):
            link_el = card.select_one("a.stretched-link[href]")
            date_el = card.select_one(".text-azure p")
            if not link_el or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = link_el.get_text(strip=True)
            link = link_el["href"]
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_climate_bonds failed: {exc}")
        return []
    return items


def scrape_covenant_of_mayors(cutoff):
    """
    https://eu-mayors.ec.europa.eu/en/news. No RSS feed found. Server-
    rendered cards, built on the European Commission's own ECL (Europa
    Component Library) design system, confirmed via a plain fetch:

        <article class="ecl-content-item">
          <ul class="ecl-content-block__primary-meta-container">
            <li><time datetime="2026-09-15T12:00:00Z">15 September 2026</time></li>
            <li>New Resource</li>
          </ul>
          <div class="ecl-content-block__title">
            <a href="/en/news/unlock-potential-energy-communities">Title</a>
          </div>
          <div class="ecl-content-block__description">Summary...</div>
        </article>

    The Covenant of Mayors is a European Commission-run initiative (DG
    ENER/JRC), not an independent NGO, so classified eu-institution like
    ECHA/ECA above rather than ngo -- and, being an EU Commission
    programme by definition, gets no eu_gate. The `time[datetime]`
    attribute is a clean ISO-8601 timestamp (ending in "Z"), parsed
    directly rather than the human-readable text alongside it.
    """
    org = "EU Covenant of Mayors"
    base = "https://eu-mayors.ec.europa.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/en/news")
        for card in soup.select("article.ecl-content-item"):
            time_el = card.select_one("time[datetime]")
            title_a = card.select_one(".ecl-content-block__title a[href]")
            summary_el = card.select_one(".ecl-content-block__description")
            if not time_el or not title_a:
                continue

            dt = None
            raw_dt = time_el["datetime"]
            try:
                dt = datetime.fromisoformat(raw_dt.replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
            except ValueError:
                dt = None
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = urljoin(base, title_a["href"])
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_covenant_of_mayors failed: {exc}")
        return []
    return items


def scrape_committee_of_regions(cutoff):
    """
    https://www.cor.europa.eu/en/news. No RSS feed found. Server-rendered
    cards (Drupal 11), confirmed via a plain fetch -- no JS rendering
    needed:

        <article class="c-card ...">
          <h3 class="c-card__title">
            <a href="/en/news/slug" class="overlay-link">Title</a>
          </h3>
          <div class="c-card__content"><p class="c-card__text">Summary…</p></div>
          <div class="c-card__footer">
            <div class="c-card__date"><time datetime="2026-09-22T12:00:00Z">22 September 2026</time></div>
          </div>
        </article>

    Same card markup for both the "Press releases" and "News" sections on
    this page. Member states' and regions' own voice at EU level -- Green
    Deal-relevant items include cohesion-fund energy renovation projects,
    Zero Pollution Forum, Water Resilience Stakeholder Platform, and
    individual cities' climate-adaptation stories. Broad (covers all CoR
    activity, not just environment), relies on the standard keyword filter
    like other broad EU-institution sources in this file. `time[datetime]`
    is a clean ISO-8601 timestamp, parsed the same way as Covenant of
    Mayors above.
    """
    org = "Committee of the Regions"
    base = "https://www.cor.europa.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/en/news")
        for card in soup.select("article.c-card"):
            title_a = card.select_one(".c-card__title a[href]")
            time_el = card.select_one("time[datetime]")
            summary_el = card.select_one(".c-card__text")
            if not title_a or not time_el:
                continue

            dt = None
            try:
                dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00"))
                if dt.tzinfo is not None:
                    dt = dt.replace(tzinfo=None)
            except ValueError:
                dt = None
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = urljoin(base, title_a["href"])
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_committee_of_regions failed: {exc}")
        return []
    return items


def scrape_cen_cenelec(cutoff):
    """
    https://www.cencenelec.eu/news-events/news/. No RSS feed (the /rss and
    /news/rss paths both 404). Server-rendered cards, confirmed via a plain
    fetch -- no JS rendering needed:

        <div class="card-content">
          <div class="card-tag">Research &amp; Innovation</div>
          <div class="card-date">2026-09-24</div>
          <div class="card-title">Title</div>
          <div><p>Summary...</p></div>
          <a href="/news-events/news/2026/brief-news/...">READ MORE</a>
        </div>

    CEN and CENELEC are the EU-recognised European standardisation bodies
    (harmonised standards under EU law, e.g. Ecodesign) -- classified
    eu-institution despite being formally private nonprofit associations,
    since their standardisation mandates come directly from the European
    Commission. Very broad multi-topic output (medical devices, AI, sport,
    quality management as well as circular economy/Ecodesign/energy
    standards) -- relies on the standard keyword filter to surface the
    Green Deal-relevant items, same as CEPS/EPC/CEN-CENELEC-style broad
    sources elsewhere in this file. Date is a clean ISO YYYY-MM-DD string.
    """
    org = "CEN-CENELEC"
    base = "https://www.cencenelec.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/news-events/news/")
        for card in soup.select("div.card-content"):
            title_el = card.select_one(".card-title")
            date_el = card.select_one(".card-date")
            link_el = card.select_one("a[href]")
            summary_el = card.select_one("div > p")
            if not title_el or not date_el or not link_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%Y-%m-%d"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, link_el["href"])
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_cen_cenelec failed: {exc}")
        return []
    return items


def scrape_ebf(cutoff):
    """
    https://www.ebf.eu/category/ebf-media-centre/updates/. No RSS feed
    (/feed and /newsroom/ both empty/404). Server-rendered cards (Enfold
    WordPress theme), confirmed via a plain fetch:

        <article class="post-entry ...">
          <h2 class="post-title entry-title">
            <a href="https://www.ebf.eu/.../slug/">Title</a>
          </h2>
          <span class="post-meta-infos">
            <time class="date-container minor-meta updated">14 September 2026</time>
          </span>
        </article>

    European Banking Federation -- inherently EU-focused (banking
    regulation, CRR/CRD, sustainable finance/taxonomy, ESG disclosure), so
    no eu_gate needed. No excerpt in the listing itself (entry-content is
    empty besides a "Read more" link) -- title used as summary, same
    fallback as ACER/Euromines elsewhere in this file. A good number of
    items are genuinely Green Deal-relevant (EU Circular Economy financing,
    energy-renovation recommendations, Clean Industrial Deal bankability),
    mixed with routine banking-regulation news -- relies on the standard
    keyword filter.
    """
    org = "European Banking Federation"
    base = "https://www.ebf.eu"
    items = []
    try:
        soup = _get_soup(f"{base}/category/ebf-media-centre/updates/")
        for card in soup.select("article.post-entry"):
            title_a = card.select_one("h2.post-title a[href]")
            date_el = card.select_one("time.date-container")
            if not title_a or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_ebf failed: {exc}")
        return []
    return items


def scrape_bioenergy_europe(cutoff):
    """
    https://bioenergyeurope.org/news/. No RSS feed found. Server-rendered
    cards (Elementor "Posts" widget on WordPress), confirmed via a plain
    fetch:

        <article class="elementor-post ...">
          <h3 class="elementor-post__title">
            <a href="https://bioenergyeurope.org/slug/">Title</a>
          </h3>
          <div class="elementor-post__excerpt"><p>Summary...</p></div>
          <div class="elementor-post__meta-data">
            <span class="elementor-post-date">September 23, 2026</span>
          </div>
        </article>

    Bioenergy industry association -- Ecodesign/RED III/biomass
    sustainability-criteria relevant. Only the first page of the widget is
    scraped (no pagination followed) -- fine for a weekly-cutoff digest,
    same shallow-depth approach as several other lean sources in this file.
    """
    org = "Bioenergy Europe"
    base = "https://bioenergyeurope.org"
    items = []
    try:
        soup = _get_soup(f"{base}/news/")
        for card in soup.select("article.elementor-post"):
            title_a = card.select_one(".elementor-post__title a[href]")
            date_el = card.select_one(".elementor-post-date")
            summary_el = card.select_one(".elementor-post__excerpt")
            if not title_a or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%B %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_bioenergy_europe failed: {exc}")
        return []
    return items


def _extract_cerre_body(url):
    """Fetch a CERRE publication detail page and pull the real article body
    text out of the rendered HTML.

    Why this exists: CERRE's REST API leaves both excerpt.rendered AND
    content.rendered empty for every item (confirmed directly against the
    live API -- see scrape_cerre's docstring), so title-only matching missed
    real hits. Concrete case that motivated this: "​​Airbus of…
    ​Lessons for European Industrial Collaboration" never says
    "industrial policy" in its title -- only in the body ("a recurring
    feature of European industrial policy debates") -- so it was silently
    dropped even though it's squarely on-topic.

    Confirmed (via a direct fetch of the live publication page) that the
    rendered HTML is plain server-side WordPress/Elementor markup, not
    client-side-JS-injected, and that cerre.eu itself has no Cloudflare-style
    bot gate (unlike delorscentre.eu) -- so a second plain GET per item is a
    reliable way to reach text the REST API doesn't expose, at the cost of
    one extra request per candidate item.

    Extraction is landmark-based rather than CSS-class-based: collect <p>
    AND <li> text following the page's <h1> title, stopping at the
    "Document(s)" / "Author(s)" / "More publications" section headings that
    mark the end of the actual article (author bios and the "more on this
    sector" sidebar are noise for keyword matching, not signal). <li> is
    included alongside <p> because CERRE publication pages regularly
    summarise their actual findings as a bulleted list (confirmed live on
    this exact example -- the paper's four key takeaways are <li> elements,
    not <p> text), so a <p>-only extraction would miss real substance.
    Elementor's own class names are long, auto-generated, and far more
    likely to change on a redesign than the fact that the page has an <h1>
    and heading elements.

    Best-effort: any failure (network error, no <h1> found, structure
    changed) returns "", and the caller falls back to the title alone --
    same degraded behaviour as before this existed, never worse.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        print(f"[backend_scrapers] CERRE detail fetch failed for {url}: {exc}")
        return ""

    h1 = soup.find("h1")
    if h1 is None:
        return ""

    stop_headings = {"document(s)", "author(s)", "more publications"}
    paragraphs = []
    for el in h1.find_all_next():
        if el.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            if el.get_text(strip=True).lower() in stop_headings:
                break
        elif el.name in ("p", "li"):
            text = el.get_text(" ", strip=True)
            if text:
                paragraphs.append(text)

    return " ".join(paragraphs).strip()


def scrape_cerre(cutoff):
    """
    https://cerre.eu/publications/. CERRE's real output (reports, not blog
    posts) lives in a custom "publications" post type -- the site's default
    /feed/ RSS only covers ordinary WordPress "posts", which CERRE doesn't
    seem to use for its actual output (confirmed: /feed/ returns a
    well-formed but completely empty <channel>, zero <item> elements, even
    though the Publications page itself shows real, current entries dated
    as recently as this week).

    Rather than scrape the publications listing page's HTML, this hits
    CERRE's public WordPress REST API directly -- confirmed available and
    unauthenticated via /wp-json/wp/v2/types, which lists a "publications"
    custom post type with rest_base "publications":

        GET https://cerre.eu/wp-json/wp/v2/publications?per_page=20&orderby=date&order=desc

        [{
          "date": "2026-09-08T05:00:00", "date_gmt": "2026-09-08T03:00:00",
          "link": "https://cerre.eu/publications/airbus-of-lessons-for-european-industrial-collaboration/",
          "title": {"rendered": "​​Airbus of… ​Lessons for European Industrial Collaboration"},
          "excerpt": {"rendered": ""},
          ...
        }, ...]

    Using date_gmt (explicit UTC) rather than date (ambiguous local/site
    timezone) for cutoff comparison. excerpt.rendered is consistently empty
    in practice, so summary falls back to the title, same as several other
    lean sources in this file. Titles carry leading zero-width spaces
    (U+200B) and HTML entities (e.g. an ellipsis as "&#8230;") that
    _clean_text() alone won't strip -- html.unescape() first, then strip
    zero-width characters explicitly.

    CERRE is a broad regulatory-economics think tank (energy, mobility,
    tech/media/telecom sectors, not just competition law), so this relies
    on COMPETITION_KEYWORDS in fetch_digest.py to surface only the
    genuinely competition/industrial-policy-relevant output and drop the
    rest (e.g. a piece on AVMSD media-regulation reform). No eu_gate --
    CERRE is Brussels-based and EU-regulation-focused, not a globally-
    reporting outlet the way Ember/Carbon Brief are.

    Previously-known limitation, now fixed: both excerpt.rendered and
    content.rendered are consistently empty across every item sampled from
    this endpoint (CERRE apparently doesn't populate WordPress's usual
    excerpt field for this post type), so summary used to fall back to the
    title alone -- the keyword filter only ever saw the title text, not the
    piece's actual content. Confirmed real-world consequence: "​​Airbus
    of… ​Lessons for European Industrial Collaboration" (a paper squarely
    about the "European champions" industrial-policy debate, presented at
    CERRE's own "EU Competitiveness Summit") got filtered OUT, because
    neither "competitiveness compass" nor "european champions" nor any
    other COMPETITION_KEYWORDS phrase happens to appear in the title itself
    -- the connection was only clear from the body text.

    Fixed by fetching each in-cutoff item's own detail page and extracting
    the real body text via _extract_cerre_body() above -- capped at
    CERRE_DETAIL_PAGE_CAP items per run (cutoff is applied first, so the cap
    only bounds an already-small, already-relevant-by-date set, not the
    full 20-item API page). Re-verified against the live "Airbus of..."
    page: the extracted body contains "a recurring feature of European
    industrial policy debates", which does match COMPETITION_KEYWORDS'
    bare "industrial policy" -- this item now survives the topic filter.
    If a detail-page fetch fails for a given item, summary falls back to
    the title alone (the old behaviour) rather than dropping the item.
    """
    org = "CERRE"
    items = []
    try:
        resp = requests.get(
            "https://cerre.eu/wp-json/wp/v2/publications",
            headers=HEADERS,
            params={"per_page": 20, "orderby": "date", "order": "desc"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        candidates = []
        for post in resp.json():
            date_gmt = post.get("date_gmt")
            if not date_gmt:
                continue
            try:
                dt = datetime.fromisoformat(date_gmt)
            except ValueError:
                continue
            if not _passes_cutoff(dt, cutoff):
                continue

            raw_title = post.get("title", {}).get("rendered", "")
            title = html.unescape(raw_title).replace("​", "").strip()
            link = post.get("link", "")
            if not title or not link:
                continue

            candidates.append((title, link, dt))

        for i, (title, link, dt) in enumerate(candidates):
            summary = title
            if i < CERRE_DETAIL_PAGE_CAP:
                body = _extract_cerre_body(link)
                if body:
                    summary = body
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_cerre failed: {exc}")
        return []
    return items


def scrape_world_bank_climate(cutoff):
    """
    https://blogs.worldbank.org/en/climatechange ("Development and a
    Changing Climate" blog series). Server-rendered (AEM/CQ) -- a plain
    fetch returns the full card list directly, no browser needed.

    No RSS/Atom feed exists (checked /rss.xml, /rss, /feed and variants,
    all empty/404; no <link rel="alternate" type="application/rss+xml">
    in the page head either).

    Cards, confirmed via live DOM inspection:

        <div class="blog_teaser">
          <div class="blog_teaser__content">
            <h3 class="blog_teaser__title">
              <a href="/en/climatechange/slug">Title</a>
            </h3>
            <div class="blog_teaser__link_container">
              <span><time>June 18, 2026</time></span>
              <ul><li><a href="/en/team/...">Author Name</a></li></ul>
            </div>
          </div>
        </div>

    Only ~8 cards on the page (no pagination scraped) -- fine for a "last N
    days" digest, and this blog posts roughly monthly, so 8 already covers
    well over a typical cutoff window. No excerpt/description text in the
    card itself, so summary falls back to the title, same as several other
    lean sources in this file. Links are relative, need the base URL.

    World Bank's climate output is mostly global/developing-country framed
    (Africa, Latin America, South Asia project case studies) rather than
    EU-policy-specific, with only occasional Europe & Central Asia regional
    pieces -- relies on actor_type: international-org's is_io_relevant()
    OR-gate (EU-relevant OR global-climate-benchmark) in fetch_digest.py,
    same as IEA/UNEP/WMO, so genuinely global "state of climate finance"
    -type content is kept even without an EU angle.
    """
    org = "World Bank Group"
    base = "https://blogs.worldbank.org"
    items = []
    try:
        soup = _get_soup(f"{base}/en/climatechange")
        for card in soup.select("div.blog_teaser"):
            title_a = card.select_one("h3.blog_teaser__title a[href]")
            time_el = card.select_one("time")
            if not title_a or not time_el:
                continue

            dt = _parse_date(time_el.get_text(strip=True), ["%B %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            href = title_a["href"]
            link = href if href.startswith("http") else base + href
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_world_bank_climate failed: {exc}")
        return []
    return items


def scrape_imf_blog(cutoff):
    """
    https://www.imf.org/en/blogs (IMFBlog). Server-rendered -- a plain
    fetch returns the full card list directly, no browser needed. No RSS
    feed found (imf.org/en/news/rss and similar guesses all redirect to an
    HTML page, not real RSS XML; IMF's actual news search is a client-
    side-rendered SPA that would need Playwright -- IMFBlog is the much
    cheaper, plain-HTML alternative and covers the same kind of analytical
    content).

    Cards, confirmed via live DOM inspection:

        <div class="card">
          <div class="card-body p-0">
            <div class="topic-type"><a href="...">Prices</a></div>
            <h2 class="card-subtitle">
              <a href="/en/blogs/articles/2026/09/17/slug" class="belt-link">Title</a>
            </h2>
            <div class="card-date mb-2">
              <time datetime="9/17/2026, 3:00 PM">September 17, 2026</time>
            </div>
            <div class="card-author">...</div>
            <p class="card-text"><a href="..."><span>Summary...</span></a></p>
          </div>
        </div>

    The same article appears inside multiple promotional widgets on this
    one landing page (a "Latest Blogs" grid, a topic-highlight belt, a
    "Read More" carousel, ...) -- confirmed live (one title matched 4
    separate <a class="belt-link"> elements). Rather than trying to scope
    to exactly one of those widgets (fragile -- the page's own layout
    changes which widgets appear), this selects every h2.card-subtitle on
    the page and dedupes by link, keeping the first (topmost) copy of each.

    IMF's general blog is overwhelmingly macro/fiscal/financial-stability/
    AI content, NOT climate- or competition-law-focused -- IMF's genuine
    climate-fiscal-policy output (carbon pricing, green subsidies) lives in
    Working Papers/Selected Issues Papers this landing page doesn't surface
    cleanly. Expect this source to contribute rarely; kept anyway (same
    "confirmed live, just infrequent/low-yield" category as several other
    sources in this file) since an occasional genuinely on-topic IMF blog
    post (EU fiscal/carbon-pricing analysis) is worth catching when it
    happens. actor_type: international-org, so is_io_relevant()'s EU-
    relevant-OR-global-climate-benchmark gate applies same as IEA/UNEP/WMO.
    """
    org = "IMF"
    base = "https://www.imf.org"
    items = []
    seen_links = set()
    try:
        soup = _get_soup(f"{base}/en/blogs")
        for heading in soup.select("h2.card-subtitle"):
            title_a = heading.select_one("a[href]")
            if not title_a:
                continue
            href = title_a["href"]
            link = href if href.startswith("http") else base + href
            if link in seen_links:
                continue

            card = heading.find_parent("div", class_="card-body") or heading.parent
            time_el = card.select_one(".card-date time") if card else None
            if not time_el:
                continue
            datetime_attr = time_el.get("datetime", "")
            dt = None
            if datetime_attr:
                # e.g. "9/17/2026, 3:00 PM" -- date part only, time doesn't matter
                date_part = datetime_attr.split(",")[0].strip()
                dt = _parse_date(date_part, ["%m/%d/%Y"])
            if dt is None:
                dt = _parse_date(time_el.get_text(strip=True), ["%B %d, %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            seen_links.add(link)
            title = title_a.get_text(strip=True)
            summary_el = card.select_one(".card-text") if card else None
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_imf_blog failed: {exc}")
        return []
    return items


def scrape_gold_standard(cutoff):
    """
    https://www.goldstandard.org/newsroom -- Gold Standard's voluntary
    carbon-credit certification body. Server-rendered (Nuxt/Vue SSR,
    confirmed via a plain fetch returning real titles/dates directly, no
    browser needed) despite the data-v-* Vue scoped-style attributes.

    No RSS/Atom feed exists (/feed, /feed/, /rss.xml, /feed.xml all
    empty).

    Cards, confirmed via live DOM inspection:

        <li>
          <article>
            <header>...<a href="/news/slug">...</a>...</header>
            <main>
              <a href="/newsroom?type=opinion">opinion</a>
              <a href="/news/slug"><h4 class="title bold w-full">Title</h4></a>
            </main>
            <footer>
              <div class="card-news__info-text">
                <span class="text-mini"> <time datetime="2026-09-29T07:00:00+0000"> Sep 29, 2026 </time> ...
              </div>
            </footer>
          </article>
        </li>

    Uses the time element's machine-readable datetime attribute rather than
    its display text, avoiding a date-format guess entirely. No excerpt
    text in the card -- summary falls back to the title, same as several
    other lean sources in this file.

    Global voluntary-carbon-market standard-setter (Switzerland-based), not
    EU-specific -- eu_gate: true in sources.yaml, same treatment as Climate
    Bonds Initiative (another global standard-setting NGO).
    """
    org = "Gold Standard Foundation"
    base = "https://www.goldstandard.org"
    items = []
    try:
        soup = _get_soup(f"{base}/newsroom")
        for article in soup.select("article"):
            title_el = article.select_one("h4.title")
            time_el = article.select_one("time[datetime]")
            if not title_el or not time_el:
                continue
            title_a = title_el.find_parent("a")
            if not title_a or not title_a.get("href"):
                continue

            datetime_attr = time_el["datetime"]
            try:
                dt = datetime.fromisoformat(datetime_attr)
                dt = dt.replace(tzinfo=None)
            except ValueError:
                continue
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            href = title_a["href"]
            link = href if href.startswith("http") else base + href
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_gold_standard failed: {exc}")
        return []
    return items


_CARBON_GAP_DATE_RE = re.compile(
    r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)[a-z]*\s+\d{4})\b"
)


def scrape_carbon_gap(cutoff):
    """
    https://carbongap.org/insights/ (note: the real domain is carbongap.org
    -- the hyphenated carbon-gap.org does not resolve). Brussels-based
    carbon-dioxide-removal (CDR) EU-policy advocacy org. Server-rendered
    Next.js -- confirmed via a plain fetch, no browser needed.

    No RSS/Atom feed exists.

    Cards use Tailwind utility classes only (no stable semantic class
    names) and, confirmed via live DOM inspection, at least two different
    card layouts on the same listing page with the date/title <p> elements
    in a DIFFERENT order between them -- positional extraction (first <p>
    is always the date, say) is not reliable here. Two structural anchors
    ARE reliable across every card layout observed, though:

      - the card's <img alt="..."> attribute always exactly matches the
        article title (confirmed against every card checked, including
        the swapped-order one)
      - a date substring (e.g. "22 Sept 2026") always appears somewhere in
        the card's flattened text, found here via regex rather than by
        assuming which element holds it

    The same href can also appear twice on the page (a "featured" card
    plus its regular grid copy) -- deduped here the same way the IMF/World
    Bank scrapers handle their own repeated-card situations.

    "Sept" (4-letter) alongside standard 3-letter abbreviations elsewhere
    on the page -- same normalisation ShareAction's scraper needed for the
    same reason (a %b-format strptime won't match a 4-letter month).

    No excerpt in the reliable-anchor set above -- summary falls back to
    the title. Thoroughly EU-specific content by nature (EU ETS, LULUCF,
    CRCF, Commission consultations) -- no eu_gate needed, same as CERRE/
    ECIPE/other Brussels-based single-issue advocates in this file.
    """
    org = "Carbon Gap"
    base = "https://carbongap.org"
    items = []
    seen_links = set()
    try:
        soup = _get_soup(f"{base}/insights")
        for card in soup.select('a[href^="/insights/"]'):
            href = card["href"]
            link = base + href
            if link in seen_links:
                continue

            img = card.select_one("img[alt]")
            if not img or not img.get("alt"):
                continue
            title = img["alt"].strip()

            card_text = card.get_text(" ", strip=True)
            date_match = _CARBON_GAP_DATE_RE.search(card_text)
            if not date_match:
                continue
            date_text = date_match.group(1).replace("Sept", "Sep")
            dt = _parse_date(date_text, ["%d %b %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            seen_links.add(link)
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_carbon_gap failed: {exc}")
        return []
    return items


def scrape_sei(cutoff):
    """
    https://www.sei.org/publications/?sort-by=ndate (Stockholm Environment
    Institute). Server-rendered -- confirmed via a plain fetch, no browser
    needed. The ?sort-by=ndate query param is required: the page's DEFAULT
    sort is "Last Updated" (a metadata-edit timestamp, not the actual
    publish date -- confirmed live: a July 2025 publication that had been
    recently edited sorted ABOVE genuinely new September 2026 items under
    the default sort). "ndate" is the site's own "Latest" sort option
    (found via the page's sort-by <select> element's option values),
    sorting by actual publish date instead.

    No RSS/Atom feed exists.

    Cards, confirmed via live DOM inspection:

        <article class="c-card">
          <div class="c-card__link-wrapper">
            <div class="c-card__text-wrapper">
              <a class="c-card__link" href="https://www.sei.org/publications/slug/">
                <span class="c-card__title">Title</span>
              </a>
              <p class="c-card__description">...</p>
              <div class="c-card__bottom-meta">
                <p class="c-card__bottom-meta-text">
                  <span class="c-card__date">21 July 2025 /</span>
                  ...
                </p>
              </div>
            </div>
          </div>
        </article>

    The page ALSO includes a handful of "related content" nav cards
    (class "c-card c-card--in-menu") reusing the exact same c-card
    structure but with no c-card__date element at all -- filtering to only
    cards that HAVE a .c-card__date cleanly excludes those without needing
    a separate class-based exclusion rule.

    SEI is a huge (3,900+ publication), genuinely globally-focused research
    institute -- recent output observed live skews heavily non-EU (Bolivia,
    Kenya, African critical minerals, humanitarian energy/refugee finance)
    -- eu_gate: true in sources.yaml is essential here, same strict
    treatment as Ember/Carbon Brief/Climate Bonds Initiative, or this
    single source would dominate the digest with non-EU content.
    """
    org = "Stockholm Environment Institute"
    base = "https://www.sei.org"
    items = []
    try:
        soup = _get_soup(f"{base}/publications/", params={"sort-by": "ndate"})
        for card in soup.select("article.c-card"):
            date_el = card.select_one(".c-card__date")
            if not date_el:
                continue
            title_el = card.select_one(".c-card__title")
            link_a = card.select_one("a.c-card__link")
            if not title_el or not link_a or not link_a.get("href"):
                continue

            date_text = date_el.get_text(strip=True).rstrip("/").strip()
            dt = _parse_date(date_text, ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = link_a["href"]
            desc_el = card.select_one(".c-card__description")
            summary = desc_el.get_text(" ", strip=True) if desc_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_sei failed: {exc}")
        return []
    return items


def scrape_newclimate(cutoff):
    """NewClimate Institute's /news listing (Drupal, server-rendered, no
    feed found at /feed/, /rss.xml). Confirmed live DOM:

        <div class="teaser">
          <div class="teaser__content">
            <a href="/news/slug" class="h3 teaser__title"><span>Title</span></a>
            <div class="event-details">
              <div class="event-details__item">
                <span class="event-details__name ...">Publication date</span>
                <span class="event-details__value">17 Sep 2026</span>
              </div>
            </div>
            <div class="teaser__description"><p>Summary...</p></div>
          </div>
        </div>
    """
    org = "NewClimate Institute"
    base = "https://newclimate.org"
    items = []
    try:
        soup = _get_soup(f"{base}/news")
        for teaser in soup.select("div.teaser"):
            link_a = teaser.select_one("a.teaser__title")
            date_el = teaser.select_one(".event-details__value")
            if not link_a or not link_a.get("href") or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %b %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = link_a.get_text(strip=True)
            link = urljoin(base, link_a["href"])
            desc_el = teaser.select_one(".teaser__description p")
            summary = desc_el.get_text(" ", strip=True) if desc_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_newclimate failed: {exc}")
        return []
    return items


def scrape_climate_analytics(cutoff):
    """Climate Analytics' /news-and-events/press-releases listing (server-
    rendered, no feed found). Confirmed live DOM:

        <article aria-labelledby="card-heading-...">
          ...
          <date class="text-grey-darker uppercase text-sm">1 October 2026</date>
          <div ...><h2 ...><a href="https://.../press-releases/slug">Title</a></h2></div>
          <div class="prose ..."><p>Summary...</p></div>
        </article>

    The page also has a handful of non-press-release <article> cards (e.g.
    an "About us" nav card) that reuse the generic article tag but have no
    <date> child -- filtering to articles that HAVE a <date> element
    cleanly excludes those, same pattern as SEI's c-card filtering above.

    Genuinely global institute (recent live output: Australian coal mines,
    UNEP overshoot report, sea-level rise, alongside real EU content like a
    European heatwave-economics study) -- eu_gate: true in sources.yaml,
    same treatment as SEI/Ember/Carbon Brief.
    """
    org = "Climate Analytics"
    base = "https://climateanalytics.org"
    items = []
    try:
        soup = _get_soup(f"{base}/news-and-events/press-releases")
        for article in soup.select("article"):
            date_el = article.find("date")
            title_a = article.select_one("h2 a[href]")
            if not date_el or not title_a:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            desc_el = article.select_one(".prose p")
            summary = desc_el.get_text(" ", strip=True) if desc_el else title
            img_el = article.select_one("img[src]")
            image = img_el["src"] if img_el else None
            items.append(_make_item(org, title, link, dt, summary, image=image))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_climate_analytics failed: {exc}")
        return []
    return items


def scrape_unfccc(cutoff):
    """UNFCCC's /news listing (Drupal, server-rendered; /news/feed is
    empty and /rss.xml is a valid-but-unpopulated feed shell with zero
    <item> elements -- confirmed, not just assumed dead). Confirmed live
    DOM:

        <article class="... node--type-news ...">
          <div class="node__content ...">
            <a href="/news/slug" class="news-teaser" data-title="Full title text">
              ...
              <div class="info-container">
                <div class="date">29 Sep 2026</div>
                <span>Title text (shorter/truncated in some cases)</span>
                <div class="field ...field-page-type-of-news...">Article</div>
              </div>
            </a>
          </div>
        </article>

    data-title is used for the title (not the inner <span>, which can be
    visually truncated) -- cleaner and more reliable. No excerpt on the
    listing page, so summary falls back to the title, same as several
    other listing-only scrapers in this file.

    Near-entirely global/multilateral-process content (COP logistics, NDC
    submissions, Article 6 governance) with only occasional EU-specific
    items -- eu_gate: true in sources.yaml is essential here, same
    treatment as the other international-org sources with eu_gate.
    """
    org = "UNFCCC"
    base = "https://unfccc.int"
    items = []
    try:
        soup = _get_soup(f"{base}/news")
        for article in soup.select("article.node--type-news"):
            link_a = article.select_one("a.news-teaser[href]")
            date_el = article.select_one(".date")
            if not link_a or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %b %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = link_a.get("data-title") or link_a.get_text(strip=True)
            link = urljoin(base, link_a["href"])
            img_el = article.select_one("img[src]")
            image = urljoin(base, img_el["src"]) if img_el else None
            items.append(_make_item(org, title, link, dt, title, image=image))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_unfccc failed: {exc}")
        return []
    return items


def scrape_perspectives_climate(cutoff):
    """Perspectives Climate Group's /insights/ listing (Astro, statically
    pre-rendered -- confirmed server-rendered via plain fetch, no JS
    needed). Confirmed live DOM:

        <div class="ingroup" id="cat-news" data-archive-group="">
          <h2 class="shn">News</h2>
          <div class="feed">
            <a class="feeditem reveal" href="/insights/slug">
              <span class="fdate"><time datetime="2025-12-22"> 22 Dec 2025 </time></span>
              ...
              <span class="fkind">News</span>
              <h2>Title text</h2>
            </a>
          </div>
        </div>

    Items are grouped into News/Events/Publications sections, each as a
    separate .feed container, but a.feeditem selects every item across
    all three groups regardless. The <time datetime="..."> attribute is
    an exact ISO date, so no text-format date parsing is needed. No
    excerpt on the listing page, summary falls back to the title.

    Perspectives Climate Research (the non-profit research arm) and
    Perspectives Climate Group (the paid advisory arm) are deliberately
    run as one site/feed -- content mixes genuine EU/international
    climate-policy analysis (Article 6, PACM funding, EU Power-to-X
    policy) with consultancy-adjacent noise (management transitions,
    newsletters, workshop write-ups). Included as a judgment call given
    the real policy content present; the existing filter_out_events/
    filter_out_low_value passes plus the topic-keyword relevance filter
    should catch a fair amount of the noise automatically.
    """
    org = "Perspectives Climate Group"
    base = "https://perspectives.cc"
    items = []
    try:
        soup = _get_soup(f"{base}/insights/")
        for item in soup.select("a.feeditem[href]"):
            time_el = item.select_one("time[datetime]")
            title_el = item.find("h2")
            if not time_el or not title_el:
                continue

            try:
                dt = datetime.strptime(time_el["datetime"][:10], "%Y-%m-%d")
            except (KeyError, ValueError):
                continue
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = urljoin(base, item["href"])
            img_el = item.select_one("img[src]")
            image = urljoin(base, img_el["src"]) if img_el else None
            items.append(_make_item(org, title, link, dt, title, image=image))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_perspectives_climate failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# BMUKN -- German Federal Environment Ministry
# ---------------------------------------------------------------------------
BMUKN_DETAIL_PAGE_CAP = 12
_BMUKN_PRESS_LIST_URL = "https://www.bundesumweltministerium.de/en/press/current-press-releases"
_BMUKN_PRESS_HREF_RE = re.compile(r"/(?:PM\d+-1|en/pressrelease/[^/?#]+)/?$")
_BMUKN_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")


def scrape_bmukn(cutoff):
    """
    https://www.bundesumweltministerium.de/en/press/current-press-releases
    -- English press releases of Germany's Federal Ministry for the
    Environment, Climate Action, Nature Conservation and Nuclear Safety
    (BMUKN, formerly BMUV). TYPO3 site, no RSS feed (/rss.xml returns
    nothing). Added after the ministry's "Roadmap for Transitioning Away
    from Fossil Fuels" (press release 121/26, 23 Sep 2026) was missed
    because no German federal ministry was being tracked at all.

    The listing is server-rendered (confirmed via a plain fetch: ~20
    releases per page, newest first, each an <h3> link to a short URL such
    as /PM11920-1 that redirects to /en/pressrelease/<slug>). Only the
    link targets are relied on here -- the listing's own wrapper markup
    wasn't inspected at HTML level, so rather than guessing class names
    this takes every anchor whose href looks like a press-release URL, and
    resolves date/title/summary from each release's own page, the same
    detail-page approach scrape_orgalim()/scrape_ceps() use. Confirmed live
    on a detail page: <meta property="article:published"
    content="2026-09-23T14:33:00+02:00">, <meta name="twitter:title">
    (clean title, without the " - BMUKN - Press release" suffix of
    og:title) and <meta property="og:description">; the visible
    "dd.mm.yyyy" date under the <h1> is used as a fallback.

    Only the English-language listing is read, so titles are English and
    the non-English filter is unaffected. The ministry publishes on many
    topics (nuclear safety, species protection...); off-topic ones are
    removed downstream by the usual green-deal keyword filter.
    """
    org = "German Federal Environment Ministry (BMUKN)"
    base = "https://www.bundesumweltministerium.de"
    items = []
    try:
        soup = _get_soup(_BMUKN_PRESS_LIST_URL)
        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base, a["href"])
            if not href.startswith(base):
                continue
            if not _BMUKN_PRESS_HREF_RE.search(href.split("?")[0]):
                continue
            if href not in links:
                links.append(href)

        seen_canonical = set()
        for link in links[:BMUKN_DETAIL_PAGE_CAP]:
            try:
                detail = _get_soup(link)
            except requests.RequestException as exc:
                print(f"[backend_scrapers] BMUKN detail fetch failed for {link}: {exc}")
                continue

            canon_el = detail.find("link", attrs={"rel": "canonical"})
            canonical = canon_el["href"] if canon_el and canon_el.get("href") else link
            if canonical in seen_canonical:
                continue
            seen_canonical.add(canonical)

            dt = None
            for prop in ("article:published", "article:published_time"):
                meta = detail.find("meta", attrs={"property": prop})
                if meta and meta.get("content"):
                    try:
                        dt = datetime.fromisoformat(meta["content"])
                        if dt.tzinfo is not None:
                            dt = dt.replace(tzinfo=None)
                    except ValueError:
                        dt = None
                    if dt:
                        break
            if dt is None:
                m = _BMUKN_DATE_RE.search(detail.get_text(" ", strip=True))
                if m:
                    dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if not _passes_cutoff(dt, cutoff):
                continue

            title = ""
            tw = detail.find("meta", attrs={"name": "twitter:title"})
            if tw and tw.get("content"):
                title = tw["content"]
            if not title:
                h1 = detail.find("h1")
                title = h1.get_text(strip=True) if h1 else ""
            if not title:
                continue

            summary = ""
            desc = detail.find("meta", attrs={"property": "og:description"}) or detail.find(
                "meta", attrs={"name": "description"}
            )
            if desc and desc.get("content"):
                summary = desc["content"]

            items.append(_make_item(org, title, canonical, dt, summary or title))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_bmukn failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Poland -- Ministry of Climate and Environment (gov.pl)
# ---------------------------------------------------------------------------
_POLAND_CLIMATE_NEWS_URL = "https://www.gov.pl/web/climate/news"
_POLAND_DATE_RE = re.compile(r"\b(\d{2})\.(\d{2})\.(\d{4})\b")
# gov.pl site sections that live under /web/climate/ but are navigation, not
# news articles (seen in the menu of the fetched page).
_POLAND_NAV_SLUGS = {
    "ministry", "ministry1", "management", "departments", "what-we-do",
    "what-we-do1", "news", "contact", "contact-details", "press",
    "programmes-and-projects", "national-energy-and-climate-plan",
    "national-raw-materials-policy",
}


def scrape_poland_climate_ministry(cutoff):
    """
    https://www.gov.pl/web/climate/news -- English news of Poland's Ministry
    of Climate and Environment (MKiŚ). No RSS feed (/web/climate/rss just
    redirects to the gov.pl home page). The listing is server-rendered:
    confirmed via a plain fetch that every item shows an image, a
    "dd.mm.yyyy" date, a title link to /web/climate/<slug> and a summary
    paragraph, newest first, 10 per page.

    The wrapper markup wasn't inspected at HTML level, so rather than
    guessing class names this walks up from every /web/climate/<slug> link
    to the closest <li> that also contains a dd.mm.yyyy date, and takes the
    longest anchor text in it as the title. Menu links are excluded by slug.
    First page only (the 10 newest items) -- enough for a daily run.
    """
    org = "Polish Ministry of Climate and Environment"
    base = "https://www.gov.pl"
    items = []
    try:
        soup = _get_soup(_POLAND_CLIMATE_NEWS_URL)
        seen = set()
        for li in soup.find_all("li"):
            text = li.get_text(" ", strip=True)
            m = _POLAND_DATE_RE.search(text)
            if not m:
                continue
            best = None
            for a in li.find_all("a", href=True):
                href = urljoin(base, a["href"]).split("?")[0].split("#")[0]
                if not href.startswith(base + "/web/climate/"):
                    continue
                slug = href[len(base + "/web/climate/"):].strip("/")
                if not slug or "/" in slug or slug in _POLAND_NAV_SLUGS:
                    continue
                label = a.get_text(" ", strip=True)
                if best is None or len(label) > len(best[1]):
                    best = (href, label)
            if not best or len(best[1]) < 10:
                continue
            link, title = best
            if link in seen:
                continue
            seen.add(link)
            dt = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if not _passes_cutoff(dt, cutoff):
                continue
            summary = text.replace(m.group(0), "", 1).replace(title, "", 1).strip()
            img_el = li.select_one("img[src]")
            image = urljoin(base, img_el["src"]) if img_el else None
            items.append(_make_item(org, title, link, dt, summary or title, image=image))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_poland_climate_ministry failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Bulgaria -- Ministry of Environment and Water (MOEW)
# ---------------------------------------------------------------------------
_BG_NEWS_URL = "https://www.moew.government.bg/en/press-center/national-news/"
_BG_DATE_RE = re.compile(r"\b(\d{1,2})\s+([A-Z][a-z]{2}),\s+(\d{4})\b")


def scrape_bulgaria_moew(cutoff):
    """
    https://www.moew.government.bg/en/press-center/national-news/ -- English
    national news of Bulgaria's Ministry of Environment and Water. No RSS
    found. Listing confirmed server-rendered via a plain fetch: each item is
    an <h3> link (article URL directly under /en/<slug>/) followed by a
    "10 Aug, 2026 | 14:31" stamp and a short teaser, newest first.

    Wrapper markup wasn't inspected at HTML level, so this takes every <h3>
    that contains a link into /en/ outside the press-center/ section, and
    reads the date and teaser from the nearest enclosing container.
    """
    org = "Bulgarian Ministry of Environment and Water"
    base = "https://www.moew.government.bg"
    items = []
    try:
        soup = _get_soup(_BG_NEWS_URL)
        seen = set()
        for h3 in soup.find_all("h3"):
            a = h3.find("a", href=True)
            if not a:
                continue
            link = urljoin(base, a["href"]).split("#")[0]
            if not link.startswith(base + "/en/") or "/press-center/" in link:
                continue
            if link in seen:
                continue
            title = a.get_text(" ", strip=True)
            if len(title) < 10:
                continue
            container = h3.parent
            text = container.get_text(" ", strip=True) if container else ""
            m = _BG_DATE_RE.search(h3.get_text(" ", strip=True)) or _BG_DATE_RE.search(text)
            if not m:
                continue
            try:
                dt = datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %b %Y")
            except ValueError:
                continue
            seen.add(link)
            if not _passes_cutoff(dt, cutoff):
                continue
            summary = text.replace(title, "", 1)
            summary = re.sub(r"\d{1,2}\s+[A-Z][a-z]{2},\s+\d{4}\s*\|\s*\d{2}:\d{2}", "", summary)
            summary = summary.replace("see more", "").strip()
            img_el = container.select_one("img[src]") if container else None
            image = urljoin(base, img_el["src"]) if img_el else None
            items.append(_make_item(org, title, link, dt, summary or title, image=image))
    except Exception as exc:
        print(f"[backend_scrapers] scrape_bulgaria_moew failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Sweden -- Government Offices press releases (government.se)
# ---------------------------------------------------------------------------
SWEDEN_LISTING_PAGES = 3
_SE_PRESS_URL = "https://www.government.se/press-releases/"
_SE_DATE_RE = re.compile(r"Published\s+(\d{1,2}\s+[A-Z][a-z]+\s+\d{4})")
_SE_HREF_RE = re.compile(r"/press-releases/\d{4}/\d{2}/[^/?#]+/?$")


def scrape_sweden_government(cutoff):
    """
    https://www.government.se/press-releases/ -- English press releases of
    the Swedish Government Offices, ALL ministries (the RSS endpoints tried
    returned nothing; the subscribe page only offers an e-mail form). The
    ministry filter on the site is JS-driven, so instead of guessing its
    query parameters this reads the first SWEDEN_LISTING_PAGES unfiltered
    pages (?p=1..3, 10 items each, newest first) and leaves the topic
    selection to the usual green-deal keyword filter -- most items are
    defence / foreign affairs and get dropped there. Climate, energy and
    nuclear releases come from the Ministries of Climate and Enterprise and
    of Finance.

    Confirmed via a plain fetch: each item is a link to
    /press-releases/YYYY/MM/<slug>/ followed by "Published 30 September 2026
    · Press release from <ministers / ministries>". Wrapper markup not
    inspected at HTML level: the date is read from the enclosing <li>.
    """
    org = "Swedish Government Offices"
    base = "https://www.government.se"
    items = []
    seen = set()
    try:
        for page in range(1, SWEDEN_LISTING_PAGES + 1):
            url = _SE_PRESS_URL if page == 1 else f"{_SE_PRESS_URL}?p={page}"
            try:
                soup = _get_soup(url)
            except requests.RequestException as exc:
                print(f"[backend_scrapers] Sweden page {page} failed: {exc}")
                break
            page_old = False
            for a in soup.find_all("a", href=True):
                href = urljoin(base, a["href"]).split("?")[0].split("#")[0]
                if not _SE_HREF_RE.search(href) or href in seen:
                    continue
                title = a.get_text(" ", strip=True)
                if len(title) < 10:
                    continue
                li = a.find_parent("li") or a.parent
                text = li.get_text(" ", strip=True) if li else ""
                m = _SE_DATE_RE.search(text)
                if not m:
                    continue
                try:
                    dt = datetime.strptime(m.group(1), "%d %B %Y")
                except ValueError:
                    continue
                seen.add(href)
                if not _passes_cutoff(dt, cutoff):
                    page_old = True
                    continue
                from_part = text.split("from", 1)[1].strip() if " from " in text else ""
                summary = f"Press release from {from_part}" if from_part else title
                items.append(_make_item(org, title, href, dt, summary))
            if page_old:
                break
    except Exception as exc:
        print(f"[backend_scrapers] scrape_sweden_government failed: {exc}")
        return []
    return items


# ---------------------------------------------------------------------------
# Generic link-list parser + native-language ministry scrapers (Oct 2026).
# Used by the static scrapers below AND by the config-driven Playwright
# scrapers in browser_scrapers.py (they only differ in how the HTML is got).
# ---------------------------------------------------------------------------
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./](\d{4})\b")

_MONTHS_EN = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], 1)}
# Month names of the languages with text-dated listings (English plus
# Portuguese / Spanish / Danish for the native-language ministry sources).
_MONTHS_EN.update({
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "mayo": 5, "junio": 6, "julio": 7,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
    "januar": 1, "februar": 2, "marts": 3, "maj": 5, "juni": 6, "juli": 7,
    "oktober": 10,
})
_TEXT_DATE_EN_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th|\.)?\s+(?:de\s+)?("
    + "|".join(sorted(_MONTHS_EN, key=len, reverse=True))
    + r")\s+(?:de\s+)?(\d{4})\b",
    re.I)


def _find_date_in_text(text):
    """dd.mm.yyyy / dd/mm/yyyy or '5 October 2026' -> datetime, else None."""
    m = _NUMERIC_DATE_RE.search(text or "")
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            pass
    m = _TEXT_DATE_EN_RE.search(text or "")
    if m:
        try:
            return datetime(int(m.group(3)), _MONTHS_EN[m.group(2).lower()],
                            int(m.group(1)))
        except ValueError:
            pass
    return None


def parse_link_listing(html_text, base_url, org, href_re, cutoff,
                       ancestor_levels=3, min_title_len=15):
    """Generic news-listing parser. For every <a> whose absolute href matches
    `href_re`, the title is the link text (or the nearest heading in the
    enclosing block), and the date is the first numeric/English date found
    in the link text or in up to `ancestor_levels` enclosing blocks. Items
    without a parseable date are skipped (see _passes_cutoff). Returns
    _make_item dicts, newest-agnostic, de-duplicated by link."""
    soup = BeautifulSoup(html_text, "html.parser")
    href_re = re.compile(href_re) if isinstance(href_re, str) else href_re
    items, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"]).split("#")[0]
        if href in seen or not href_re.search(href):
            continue
        link_text = a.get_text(" ", strip=True)
        block, dt, block_text = a, _find_date_in_text(link_text), link_text
        node = a
        for _ in range(ancestor_levels):
            if dt:
                break
            node = node.parent
            if node is None or node.name in ("body", "html", "main"):
                break
            # Stop climbing once the block contains several listing links:
            # the date would belong to a different item.
            if len([x for x in node.find_all("a", href=True)
                    if href_re.search(urljoin(base_url, x["href"]))]) > 1:
                break
            block_text = node.get_text(" ", strip=True)
            block = node
            dt = _find_date_in_text(block_text)
        if not dt:
            continue
        title = link_text
        if len(title) < min_title_len or _find_date_in_text(title) and len(title) < 25:
            h = block.find(["h1", "h2", "h3", "h4"]) if block is not a else None
            title = h.get_text(" ", strip=True) if h else title
        # Drop a leading/trailing date stamp from the title text.
        title = _NUMERIC_DATE_RE.sub("", title).strip(" -–|·:")
        if len(title) < min_title_len:
            continue
        seen.add(href)
        if not _passes_cutoff(dt, cutoff):
            continue
        summary = ""
        if block is not a:
            summary = block_text.replace(link_text, "", 1)
            summary = _NUMERIC_DATE_RE.sub("", summary)
            summary = _TEXT_DATE_EN_RE.sub("", summary)
            summary = re.sub(r"\b(Published|Publicado|Publicada)( on| em| el)?\b",
                             "", summary, flags=re.I)
            summary = re.sub(r"\s+", " ", summary).strip(" -–|·:")
        items.append(_make_item(org, title, href, dt, summary))
    return items


def scrape_spain_miteco(cutoff):
    """
    https://www.miteco.gob.es/es/prensa/ultimas-noticias.html -- Spanish
    Ministry for the Ecological Transition, press releases (Spanish; the
    `translate_from: es` flag in sources.yaml machine-translates them).
    Item links look like /es/prensa/ultimas-noticias/YYYY/<month>/<slug>.html
    with the dd/mm/yyyy date in the link text. Not verified against live
    HTML.
    """
    try:
        soup_html = requests.get(
            "https://www.miteco.gob.es/es/prensa/ultimas-noticias.html",
            headers=HEADERS, timeout=REQUEST_TIMEOUT)
        soup_html.raise_for_status()
        return parse_link_listing(
            soup_html.text, "https://www.miteco.gob.es", "Spanish MITECO",
            r"/es/prensa/ultimas-noticias/\d{4}/[^/]+/[^/]+\.html", cutoff)
    except Exception as exc:
        print(f"[backend_scrapers] scrape_spain_miteco failed: {exc}")
        return []


def scrape_latvia_kem(cutoff):
    """
    https://www.kem.gov.lv/lv/jaunumi -- Latvian Ministry of Climate and
    Energy news (Latvian; machine-translated via `translate_from: lv`).
    Item links /lv/jaunums/<slug>, date dd.mm.yyyy. Not verified against
    live HTML.
    """
    try:
        resp = requests.get("https://www.kem.gov.lv/lv/jaunumi",
                            headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        return parse_link_listing(
            resp.text, "https://www.kem.gov.lv", "Latvian Ministry of Climate and Energy",
            r"/lv/jaunums/[^/?#]+", cutoff)
    except Exception as exc:
        print(f"[backend_scrapers] scrape_latvia_kem failed: {exc}")
        return []


# ---------------------------------------------------------------------------
SCRAPERS = {
    "spain_miteco": scrape_spain_miteco,
    "latvia_kem": scrape_latvia_kem,
    "bulgaria_moew": scrape_bulgaria_moew,
    "sweden_government": scrape_sweden_government,
    "poland_climate_ministry": scrape_poland_climate_ministry,
    "bmukn": scrape_bmukn,
    "ceps": scrape_ceps,
    "transport_environment": scrape_transport_environment,
    "pik_potsdam": scrape_pik_potsdam,
    "iddri": scrape_iddri,
    "eurelectric": scrape_eurelectric,
    "european_climate_foundation": scrape_european_climate_foundation,
    "clientearth": scrape_clientearth,
    "agora_energiewende": scrape_agora_energiewende,
    "epc": scrape_epc,
    "bc3": scrape_bc3,
    "eera": scrape_eera,
    "cefic": scrape_cefic,
    "eurofer": scrape_eurofer,
    "zenodo": scrape_zenodo,
    "industriall_europe": scrape_industriall_europe,
    "fern": scrape_fern,
    "cembureau": scrape_cembureau,
    "ieta": scrape_ieta,
    "euromines": scrape_euromines,
    "eurogas": scrape_eurogas,
    "influencemap": scrape_influencemap,
    "copa_cogeca": scrape_copa_cogeca,
    "council_eu": scrape_council_eu,
    "acer": scrape_acer,
    "orgalim": scrape_orgalim,
    "iea": scrape_iea,
    "unep": scrape_unep,
    "wmo": scrape_wmo,
    "insurance_europe": scrape_insurance_europe,
    "climate_bonds": scrape_climate_bonds,
    "covenant_of_mayors": scrape_covenant_of_mayors,
    "cen_cenelec": scrape_cen_cenelec,
    "ebf": scrape_ebf,
    "bioenergy_europe": scrape_bioenergy_europe,
    "committee_of_regions": scrape_committee_of_regions,
    "cerre": scrape_cerre,
    "world_bank_climate": scrape_world_bank_climate,
    "imf_blog": scrape_imf_blog,
    "gold_standard": scrape_gold_standard,
    "carbon_gap": scrape_carbon_gap,
    "sei": scrape_sei,
    "newclimate": scrape_newclimate,
    "climate_analytics": scrape_climate_analytics,
    "unfccc": scrape_unfccc,
    "perspectives_climate": scrape_perspectives_climate,
}

# Headless-browser scrapers (browser_scrapers.py) live in a separate module
# so that Playwright is only imported -- and its browser binary only
# needed -- for the handful of sources.yaml entries that actually require
# it (see that module's docstring). Merged into the same SCRAPERS dict so
# fetch_digest.py's dispatch logic (backend_scrapers.SCRAPERS.get(...))
# doesn't need to know or care which underlying mechanism a given source
# uses. This import happens after backend_scrapers' own functions are
# defined above -- browser_scrapers.py imports several of them back
# (_make_item, _parse_date, _passes_cutoff), which only resolves cleanly
# at this point in the file.
try:
    from browser_scrapers import BROWSER_SCRAPERS

    SCRAPERS.update(BROWSER_SCRAPERS)
except ImportError as exc:
    print(
        f"[backend_scrapers] browser_scrapers.py not importable ({exc}); "
        f"sources using a headless-browser scraper will be skipped"
    )
