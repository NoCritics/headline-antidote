"""What regular scrapers hand the model from a page: the readers the benchmark compares with
headline-antidote. Headline readers take the page's first <h1> or the extractor's title; body
readers take the extractor's whole article text.
"""

import warnings

import lxml.html
import newspaper
import trafilatura
from bs4 import BeautifulSoup

from headline_antidote.browser_visibility import (BLOCKED_RESOURCE_TYPES, DEFAULT_SETTLE_MILLISECONDS,
                                                  DEFAULT_TIMEOUT_MILLISECONDS, MAXIMUM_DOCUMENT_SERVES, VIEWPORT)

warnings.filterwarnings("ignore", message="nltk is not installed")

HEADLINE_READERS = ["BeautifulSoup h1", "lxml h1 (Scrapy)", "trafilatura title", "newspaper4k title",
                    "Chrome h1 inner_text"]
BODY_READERS = ["trafilatura body", "newspaper4k body", "Chrome body inner_text"]
CHROME_READERS = ["Chrome h1 inner_text", "Chrome body inner_text"]
NEWSPAPER_URL = "https://example.com/news/article"
RESTART_READS = 25
READ_SCRIPT = "() => ({h1: document.querySelector('h1')?.innerText ?? '', body: document.body?.innerText ?? ''})"


def error_text(error):
    return f"<error: {type(error).__name__}: {error}>"


def is_error(text):
    return text.startswith("<error: ")


def _beautifulsoup_h1(html):
    heading = BeautifulSoup(html, "lxml").find("h1")
    return heading.get_text() if heading else ""


def _lxml_h1(html):
    # What Scrapy's selectors return for "h1 ::text", joined.
    headings = lxml.html.document_fromstring(html).xpath("//h1")
    return headings[0].text_content() if headings else ""


def _trafilatura(html):
    """(title, body text)."""
    extraction = trafilatura.bare_extraction(html, with_metadata=True)
    if extraction is None:
        return "", ""
    return extraction.title or "", extraction.text or ""


def _newspaper(html):
    """(title, body text)."""
    article = newspaper.Article(url=NEWSPAPER_URL)
    article.download(input_html=html)
    article.parse()
    return article.title or "", article.text or ""


def static_readings(html):
    """{reader: text} for every reader but Chrome's; a reader that raises gives error_text."""
    readings = {}
    for name, reader in (("BeautifulSoup h1", _beautifulsoup_h1), ("lxml h1 (Scrapy)", _lxml_h1)):
        try:
            readings[name] = reader(html)
        except Exception as error:  # a scraper failing on a page is a result, recorded as such
            readings[name] = error_text(error)
    for (title_name, body_name), reader in ((("trafilatura title", "trafilatura body"), _trafilatura),
                                            (("newspaper4k title", "newspaper4k body"), _newspaper)):
        try:
            title, body = reader(html)
        except Exception as error:  # as above
            title = body = error_text(error)
        readings[title_name] = title
        readings[body_name] = body
    return readings


class ChromeReader:
    """Headless Chrome reading a page's first <h1> and <body> with innerText, as a Playwright scraper
    does. The page is served from the given HTML at its real address; its scripts and stylesheets load
    from the live site and images, media and fonts are blocked, as in BrowserVerifier.render."""

    def __init__(self):
        self._playwright = None
        self._browser = None
        self._reads = 0
        self.version = None

    def start(self):
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(channel="chrome", headless=True)
        self.version = self._browser.version
        return self

    def close(self):
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # a crashed browser may already be gone
                pass
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def restart(self):
        self.close()
        self.start()

    def __enter__(self):
        return self.start()

    def __exit__(self, exception_type, exception, traceback):
        self.close()

    def read(self, url, html):
        """{"Chrome h1 inner_text": ..., "Chrome body inner_text": ...}; both are error_text when Chrome fails."""
        from playwright.sync_api import Error as PlaywrightError

        if self._reads and self._reads % RESTART_READS == 0:
            self.restart()
        self._reads += 1
        served = {"documents": 0}

        def handle(route):
            request = route.request
            if request.resource_type == "document" and request.frame == page.main_frame:
                served["documents"] += 1
                if served["documents"] > MAXIMUM_DOCUMENT_SERVES:
                    route.abort()
                    return
                route.fulfill(status=200, content_type="text/html; charset=utf-8", body=html)
            elif request.resource_type in BLOCKED_RESOURCE_TYPES:
                route.abort()
            else:
                route.continue_()

        try:
            context = self._browser.new_context(viewport=VIEWPORT, service_workers="block")
            try:
                page = context.new_page()
                page.route("**/*", handle)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MILLISECONDS)
                except PlaywrightError:
                    pass  # a page that never finishes loading is read as it stands, as a scraper would
                page.wait_for_timeout(DEFAULT_SETTLE_MILLISECONDS)
                texts = page.evaluate(READ_SCRIPT)
            finally:
                context.close()
        except PlaywrightError as error:
            self.restart()  # a crashed page can take the browser with it
            return {name: error_text(error) for name in CHROME_READERS}
        return {"Chrome h1 inner_text": texts["h1"], "Chrome body inner_text": texts["body"]}
