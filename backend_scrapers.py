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
SCRAPERS = {
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
}
