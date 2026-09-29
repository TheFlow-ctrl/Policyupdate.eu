"""
browser_scrapers.py

Headless-browser scrapers, for the handful of sources that
backend_scrapers.py's plain requests+BeautifulSoup approach genuinely
cannot reach -- either because a page requires JavaScript to render its
content at all, or because it sits behind a JS-executed bot-check (Azure
WAF, Cloudflare's non-interactive challenge, etc.) that a plain HTTP
request either hangs on or gets redirected away from into a stale
fallback.

This uses Playwright to drive a real (headless) Chromium: it actually
loads the page, runs its JavaScript, waits for the real content to
appear, then hands the resulting HTML to BeautifulSoup for parsing --
same downstream shape (_make_item dicts) as every scraper in
backend_scrapers.py, just a heavier, slower way of getting the raw HTML
in the first place. Kept in a separate module (rather than folded into
backend_scrapers.py) so that the plain-requests scrapers there have no
dependency on Playwright being installed -- only sources.yaml entries
that actually need this pay the cost of a browser download in CI.

Each scrape_* function has the same shape as backend_scrapers.py's:
takes a `cutoff` datetime, returns a list of _make_item()-shaped dicts.
Playwright is imported lazily inside each function (not at module level)
so that a missing/not-yet-installed Playwright browser binary produces a
clear per-source warning via fetch_digest.py's existing try/except
around each scraper call, rather than an ImportError that would crash
the whole pipeline at startup.
"""

from bs4 import BeautifulSoup

from backend_scrapers import _make_item, _parse_date, _passes_cutoff

# How long to wait for the real page content to appear after navigation,
# in milliseconds. ECHA's Azure WAF "checking you're not a bot" challenge
# resolved in ~6s in manual testing; this gives real headroom above that
# without letting a genuinely broken page hang the whole pipeline run.
CONTENT_TIMEOUT_MS = 20_000

# Playwright launches its own Chromium download under a fixed cache path;
# nothing here to configure beyond `playwright install chromium` having
# been run once (see requirements.txt / the CI workflow).


def _fetch_rendered_html(url, wait_selector, timeout=CONTENT_TIMEOUT_MS):
    """Load `url` in a real (headless) Chromium, wait for `wait_selector`
    to appear (i.e. the real content, not just a bot-check interstitial's
    own DOM), and return the fully-rendered page HTML. Shared by every
    scrape_* function below so each one only has to say what page and
    what selector, not how to drive the browser."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, timeout=timeout)
            page.wait_for_selector(wait_selector, timeout=timeout)
            return page.content()
        finally:
            browser.close()


def scrape_echa(cutoff):
    """
    https://echa.europa.eu/news (Liferay portal). No RSS/Atom feed exists
    anywhere on the site. The page is gated behind an Azure WAF
    "checking you're not a bot" interstitial that requires JavaScript to
    clear -- a plain requests.get() doesn't hang on it, it gets served a
    stale legacy snapshot of the page instead (confirmed: years-old
    2019/2020 items), so this has to go through a real browser.

    Server-rendered cards once the real page loads (confirmed via live
    DOM inspection, same structure Liferay uses site-wide):

        <div class="TRow HomeNews">
          <div class="NewsLevelA">
            <div class="TCol-5"><a href="/-/slug"><img ...></a></div>
            <div class="TCol-7">
              <dl>
                <dt><a href="/-/slug">Title</a></dt>
                <dd class="NewsDate">24/09/2026</dd>
                <dd><p>Summary...</p></dd>
              </dl>
            </div>
          </div>
        </div>

    Only the most recent handful of items are on this page (no
    pagination/load-more scraped here) -- fine for a "last N days" digest,
    and matches the shallow depth of several other lean sources in this
    project. Covers REACH, CLP, PFAS restrictions, and other chemicals
    regulation directly relevant to Green Deal industrial policy.
    """
    org = "ECHA"
    base = "https://echa.europa.eu"
    items = []
    try:
        html = _fetch_rendered_html(f"{base}/news", ".TRow.HomeNews")
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("div.TRow.HomeNews"):
            title_a = card.select_one("dt a")
            date_el = card.select_one("dd.NewsDate")
            summary_el = card.select_one("dd:not(.NewsDate)")
            if not title_a or not title_a.get("href") or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d/%m/%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = base + title_a["href"] if title_a["href"].startswith("/") else title_a["href"]
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[browser_scrapers] scrape_echa failed: {exc}")
        return []
    return items


def scrape_eca(cutoff):
    """
    https://www.eca.europa.eu/en/all-news (SharePoint-based, React-rendered
    news list -- a plain fetch returns an essentially empty <main>, the
    cards only exist after client-side JS runs). No RSS/Atom feed exists
    on the site (confirmed previously by a research agent that found the
    listing is backed by an internal, undocumented SharePoint WCF POST
    endpoint -- not a public interface worth depending on directly, so
    this drives the real page instead).

    Server-rendered-by-JS cards, confirmed via live DOM inspection:

        <li class="col-6 col-lg-4 col-xl-3">
          <div class="card card-news">
            <img ... class="card-img-top">
            <div class="card-body">
              <time class="card-date">21/09/2026</time>
              <a href="https://www.eca.europa.eu/en/news/NEWS-SR-2026-19" class="stretched-link">
                <h3 class="card-title">Title</h3>
              </a>
              <p>Summary...</p>
            </div>
          </div>
        </li>

    Link is already absolute. ECA publishes audit special reports directly
    relevant to Green Deal spending -- REPowerEU governance, home-
    renovation energy savings, critical infrastructure resilience are all
    real examples seen live -- so this was a genuine, named gap before now.
    """
    org = "European Court of Auditors"
    items = []
    try:
        html = _fetch_rendered_html(
            "https://www.eca.europa.eu/en/all-news", "li.col-6.col-lg-4.col-xl-3"
        )
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("li.col-6.col-lg-4.col-xl-3"):
            link_el = card.select_one("a.stretched-link")
            title_el = card.select_one(".card-title")
            date_el = card.select_one(".card-date")
            summary_el = card.select_one(".card-body p")
            if not link_el or not link_el.get("href") or not title_el or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d/%m/%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = link_el["href"]
            summary = summary_el.get_text(strip=True) if summary_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[browser_scrapers] scrape_eca failed: {exc}")
        return []
    return items


def scrape_shareaction(cutoff):
    """
    https://shareaction.org/news (Next.js). No RSS/Atom feed exists
    (the /feed.xml link some pages advertise 404s). A plain fetch
    returns only the page shell with no article list -- the news grid
    is populated client-side -- so, like ECHA/ECA above, this goes
    through a real headless browser instead of a plain HTTP request.

    Rendered cards, confirmed via live DOM inspection:

        <a href="https://shareaction.org/news/defending-your-right-to-attend-agms-in-person"
           class="block w-1/2 pl-10 mb-10 md:w-1/4">
          <time class="block py-2 text-xs ...">23 Sept 2026</time>
          <div class="..."><img ...></div>
          <h6>Defending your right to attend AGMs in person</h6>
        </a>

    ShareAction is a UK-based responsible-investment NGO, not an EU
    body -- most of its campaign content is UK-specific (Living Wage,
    UK retailers' AGMs) with only occasional EU-policy pieces (SFDR,
    EU ETS lobbying, EU competitiveness/sustainability-rules debates).
    Marked eu_gate: true in sources.yaml so only the EU-relevant items
    surface -- see apply_relevance_filter()'s eu_gate handling in
    fetch_digest.py. The site's date format is inconsistent -- every
    month EXCEPT September is a standard 3-letter abbreviation ("Jul",
    "Aug"), but September itself is spelled "Sept" (4 letters), which
    Python's %b directive won't match -- normalised to "Sep" before
    parsing.
    """
    org = "ShareAction"
    items = []
    try:
        html = _fetch_rendered_html(
            "https://shareaction.org/news", 'a[href*="/news/"] time'
        )
        soup = BeautifulSoup(html, "html.parser")
        for link_el in soup.select('a[href*="/news/"]'):
            time_el = link_el.select_one("time")
            title_el = link_el.select_one("h6")
            if not time_el or not title_el:
                continue

            date_text = time_el.get_text(strip=True).replace("Sept", "Sep")
            dt = _parse_date(date_text, ["%d %b %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_el.get_text(strip=True)
            link = link_el["href"]
            items.append(_make_item(org, title, link, dt, title))
    except Exception as exc:
        print(f"[browser_scrapers] scrape_shareaction failed: {exc}")
        return []
    return items


def scrape_eurocities(cutoff):
    """
    https://eurocities.eu/topics/climate-environment/. No RSS feed. The
    site pre-scopes its own "Latest" feed to this Climate & Environment
    topic (same idea as CORDIS's pre-scoped query elsewhere in this
    project) -- no keyword filter needed at all, every item on this page
    is already about climate/environment by the site's own tagging.
    A plain fetch returns only the topic's static description text (the
    news list itself is populated client-side), so this goes through a
    real headless browser instead, like ECHA/ECA/ShareAction above.

    Rendered cards, confirmed via live DOM inspection:

        <li>
          <span class="meta-cat">Press release</span>
          <span class="date">25 June 2026</span>
          <h3 class="h4">
            <a href="https://eurocities.eu/latest/slug/">Title</a>
          </h3>
          <p><a href="https://eurocities.eu/latest/slug/">Summary...</a></p>
        </li>

    Eurocities is a network of 200+ European cities -- classified ngo
    (advocacy/network association) rather than eu-institution, same
    "closest fit" judgment call as Netzero Cities elsewhere in this file.
    """
    org = "Eurocities"
    items = []
    try:
        html = _fetch_rendered_html(
            "https://eurocities.eu/topics/climate-environment/", "ul.other-story-list li"
        )
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("ul.other-story-list li"):
            title_a = card.select_one("h3 a[href]")
            date_el = card.select_one(".date")
            summary_a = card.select_one("p a[href]")
            if not title_a or not date_el:
                continue

            dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            summary = summary_a.get_text(strip=True) if summary_a else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[browser_scrapers] scrape_eurocities failed: {exc}")
        return []
    return items


def _parse_oecd_cards(html, base, cutoff):
    """Shared parsing logic for OECD topic pages (see scrape_oecd_climate/
    scrape_oecd_competition below) -- both pages use the same site-wide
    "Related publications" card component, so this is the same extraction
    for either, just called with different fetched HTML.

    Cards, confirmed via live DOM inspection on both the Climate change and
    Competition topic pages:

        <div class="card report-summary-page card--silent-theme">
          <div class="card__content">
            <div class="card__tags"><div class="tag tag--small">Working paper</div></div>
            <div class="card__title">
              <a class="card__title-link" href="/en/publications/slug_id-en.html">Title</a>
            </div>
          </div>
          <div class="card__metadata">
            <div class="card__date">30 September 2026</div>
            <div class="card__pages">51 Pages</div>
          </div>
        </div>

    This card class is specific to the "Related publications" widget --
    confirmed the page's other widgets (Latest insights' videos, Roundtable
    notes, Related events) use different card classes entirely, so
    selecting div.card.report-summary-page site-wide, with no further
    section-scoping, cleanly picks up only the publications and nothing
    else -- verified live: exactly 5 matches on the Competition page, all
    Working paper/Report/Policy paper, zero Video/Roundtable/event items.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.select("div.card.report-summary-page"):
        title_a = card.select_one(".card__title-link")
        date_el = card.select_one(".card__date")
        if not title_a or not title_a.get("href") or not date_el:
            continue

        dt = _parse_date(date_el.get_text(strip=True), ["%d %B %Y"])
        if not _passes_cutoff(dt, cutoff):
            continue

        title = title_a.get_text(strip=True)
        href = title_a["href"]
        link = href if href.startswith("http") else base + href
        items.append(_make_item("OECD", title, link, dt, title))
    return items


def scrape_oecd_climate(cutoff):
    """
    https://www.oecd.org/en/topics/climate-change.html -- see
    _parse_oecd_cards() above for the shared card structure. Confirmed JS-
    required: a plain fetch of this URL returns ~79,000 characters of pure
    navigation/mega-menu markup and zero dated content (grepped for years/
    "Report"/"Publication" -- no matches); a JS-executing browser on the
    identical URL shows the populated "Related publications" widget. No
    RSS feed exists anywhere on oecd.org (oecd.org/rss, oecd.org/rssfeeds/,
    and search.oecd.org/rssfeeds/ -- the URL commonly cited as OECD's own
    feed portal -- all return empty).

    No excerpt text available in the card (only a content-type tag,
    title, date, page count) -- summary falls back to the title, same as
    several other lean sources in this file.

    OECD's Environment/Climate output is genuinely mixed EU/global (US,
    Japan, and other non-EU members' reviews alongside EU-member-state
    ones -- e.g. "OECD Environmental Performance Reviews: Slovenia 2026"
    seen live) -- relies on actor_type: international-org's is_io_relevant()
    OR-gate, same reasoning as IEA/UNEP/WMO/World Bank.
    """
    base = "https://www.oecd.org"
    try:
        html = _fetch_rendered_html(
            f"{base}/en/topics/climate-change.html", "div.card.report-summary-page"
        )
        return _parse_oecd_cards(html, base, cutoff)
    except Exception as exc:
        print(f"[browser_scrapers] scrape_oecd_climate failed: {exc}")
        return []


def scrape_oecd_competition(cutoff):
    """
    https://www.oecd.org/en/topics/competition.html -- see
    _parse_oecd_cards() above for the shared card structure and
    scrape_oecd_climate() above for why this needs a real browser (same
    site, same JS-rendered widget, same absence of any RSS feed).

    OECD runs the closest thing to a genuine peer to DG COMP outside the
    EU itself -- a dedicated Competition Committee, "OECD Competition
    Trends" annual analysis, and frequent EU-member-state-specific
    enforcement studies (e.g. "Fighting Bid Rigging in Public Procurement
    in Austria, Bulgaria, Croatia, Cyprus, Greece and Romania" seen live).
    field: competition, actor_type: international-org -- is_io_relevant()'s
    OR-gate degrades gracefully here: its second branch (climate-benchmark
    keywords) will essentially never fire for competition-topic content, so
    this effectively requires EU-relevance, which is the right level of
    strictness for a globally-reporting competition body (there's no
    competition-policy equivalent of a "1.5C" global benchmark the way
    climate has one).
    """
    base = "https://www.oecd.org"
    try:
        html = _fetch_rendered_html(
            f"{base}/en/topics/competition.html", "div.card.report-summary-page"
        )
        return _parse_oecd_cards(html, base, cutoff)
    except Exception as exc:
        print(f"[browser_scrapers] scrape_oecd_competition failed: {exc}")
        return []


def scrape_kfw(cutoff):
    """
    KfW (German state development bank) English-language press releases --
    https://www.kfw.de/About-KfW/Newsroom/Latest-News/Press-Releases/
    index.jsp, with a query string (?facet.filter.language=en&...) that a
    research pass found the page's own search widget adds client-side on
    load. Confirmed JS-required: this is a client-side search-results
    widget (Coveo-style), not server-rendered HTML.

    No RSS feed exists -- the legacy feed URLs referenced in KfW's own
    "RSS-Feed" help page (kfw.de/.../RssPressDe.xml and similar) all 404;
    KfW's current "Newsdienste" page only offers email newsletter signup.

    Cards, confirmed via live DOM inspection:

        <div class="search-result-item-wrapper news_press">
          <div class="spitzmarke"><p class="smk-1">29.09.2026 | KfW Research</p></div>
          <div class="title">
            <a class="link type-headline hl-5" href="https://www.kfw.de/.../News-Details_908608.html"
               aria-label="KfW-ifo SME Barometer: September 2026">
              <span class="link-container"><span class="link-labeling">KfW-ifo SME Barometer: September 2026</span></span>
            </a>
          </div>
          <div class="description">Sentiment continues to rise</div>
        </div>

    The date/business-division line is one text node ("29.09.2026 | KfW
    Research") -- split on " | ", first part is the date.

    Confirmed English content updates in lockstep with German (same-day
    releases in both languages, not a lagging translation) -- viable as an
    English-only source under this project's language policy. That said,
    KfW's real-time output is overwhelmingly transactional/self-
    promotional (its own SME survey results, individual loan/bond deals,
    country financing announcements) rather than policy analysis -- expect
    the keyword filter to reject most of it and pass through only genuine
    green-finance/energy-transition items (green bond issuances, energy-
    efficiency financing programmes) when they occur. field: green-deal,
    NOT actor_type: international-org (KfW is a national promotional bank,
    not a multilateral body -- doesn't fit the IEA/UNEP/WMO/OECD/World Bank
    "reports on the whole world" category this actor_type exists for), so
    the plain GREEN_DEAL_KEYWORDS topic filter applies with no additional
    EU-relevance gate. No eu_gate either: unlike Ember/Carbon Brief/
    ShareAction (globally-reporting outlets needing a strict EU-specificity
    AND-gate), KfW's transactional press releases rarely say "Europe"/"EU"
    explicitly even when the underlying deal is EU-relevant (e.g. a German
    SME energy-efficiency loan programme) -- an EU-relevance AND-gate on
    top of the topic filter would likely zero out this source entirely;
    the topic filter alone is the right amount of gating here.
    """
    org = "KfW"
    url = (
        "https://www.kfw.de/About-KfW/Newsroom/Latest-News/Press-Releases/"
        "index.jsp?rows=10&facet.filter.language=en&query=*%3A*&page=1"
        "&sortBy=relevance_sort&sortOrder=desc&groups=1&dymFailover=true"
    )
    items = []
    try:
        html = _fetch_rendered_html(url, "div.search-result-item-wrapper.news_press")
        soup = BeautifulSoup(html, "html.parser")
        for card in soup.select("div.search-result-item-wrapper.news_press"):
            meta_el = card.select_one(".spitzmarke p")
            title_a = card.select_one(".title a[href]")
            desc_el = card.select_one(".description")
            if not meta_el or not title_a:
                continue

            date_text = meta_el.get_text(strip=True).split("|")[0].strip()
            dt = _parse_date(date_text, ["%d.%m.%Y"])
            if not _passes_cutoff(dt, cutoff):
                continue

            title = title_a.get_text(strip=True)
            link = title_a["href"]
            summary = desc_el.get_text(strip=True) if desc_el else title
            items.append(_make_item(org, title, link, dt, summary))
    except Exception as exc:
        print(f"[browser_scrapers] scrape_kfw failed: {exc}")
        return []
    return items


BROWSER_SCRAPERS = {
    "echa": scrape_echa,
    "eca": scrape_eca,
    "shareaction": scrape_shareaction,
    "eurocities": scrape_eurocities,
    "oecd_climate": scrape_oecd_climate,
    "oecd_competition": scrape_oecd_competition,
    "kfw": scrape_kfw,
}
