"""The demo pipeline with headline_guard between the download and the LLM.
Run it while the demo server is up:  python -X utf8 demo/pipeline.py
"""
import json

import requests
from headline_guard import HeadlineGuard
from headline_guard.browser_visibility import BrowserVerifier
from headline_guard.html_visibility import linked_stylesheet_urls

from scraper import BASE_URL, PAGES, scrape

# Built once: the companies you trade, and the names they go by.
WATCHLIST = {"TSLA": ["Tesla"], "GOOGL": ["Alphabet", "Google"], "NVDA": ["Nvidia"],
             "AAPL": ["Apple"], "MSFT": ["Microsoft"]}
guard = HeadlineGuard(WATCHLIST)


def fetch_stylesheets(html, url):
    """Download the CSS files the page links to, so hiding rules in them are seen."""
    return [requests.get(link, timeout=10).text for link in linked_stylesheet_urls(html, url)]


with BrowserVerifier() as verifier:            # one headless Chrome for the whole run, no window
    for name in PAGES:
        url = BASE_URL + name
        html, scraped_headline, scraped_body = scrape(url)
        article = guard.extract_article(html, stylesheets=fetch_stylesheets(html, url))
        if article.needs_browser_check:        # only the pages static reading can't settle
            article = guard.verify_article_in_browser(article, html, url, verifier)

        print(f"=== {name}")
        print(f"SCRAPER HEADLINE: {scraped_headline}")
        print(f"SCRAPER BODY:     {scraped_body}")
        print(json.dumps(article.to_dict(), indent=2, ensure_ascii=False))   # the guard's report
        print()

        if article.verdict == "quarantine":
            continue                           # don't send it to the LLM; alert instead
        # your_llm(article.headline, article.body)   <- the LLM gets the guard's text, not the scraper's
