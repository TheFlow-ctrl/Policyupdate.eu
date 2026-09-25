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


BROWSER_SCRAPERS = {
    "echa": scrape_echa,
    "eca": scrape_eca,
}
