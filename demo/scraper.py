"""A typical naive news scraper: fetch each page, take the <h1> and the paragraph text.

This is what many pipelines hand to the LLM. Run it while the demo server is up:
    python demo/scraper.py
"""
import requests
from bs4 import BeautifulSoup

BASE_URL = "http://localhost:8765/"
PAGES = [
    "clean_tesla.html",
    "clean_alphabet.html",
    "clean_nvidia.html",
    "poison_hidden_headline.html",
    "poison_homoglyph.html",
    "poison_offscreen_body.html",
    "poison_external_css.html",
    "poison_script.html",
]


def scrape(url):
    """Download the page and extract headline and body the usual way. Returns (html, headline, body)."""
    response = requests.get(url, timeout=10)
    response.encoding = response.apparent_encoding  # the demo server sends no charset
    html = response.text
    soup = BeautifulSoup(html, "html.parser")
    headline = soup.find("h1").get_text()
    body = "\n".join(paragraph.get_text() for paragraph in soup.select("article p:not(.byline)"))
    return html, headline, body


if __name__ == "__main__":
    for name in PAGES:
        html, headline, body = scrape(BASE_URL + name)
        print(f"=== {name}")
        print(f"HEADLINE: {headline}")
        print(f"BODY:     {body}\n")
