"""Runs each scraper on each test page and checks what the guard catches.

For every page and extractor it records:
  * what the scraper extracted as the headline;
  * whether the attack survived into that text, i.e. would reach the model;
  * the guard's verdict on the scraped text alone (guard placed after the scraper);
  * the guard's verdict on the raw HTML plus the scraped text (guard beside the scraper).

Run from the project root with the project virtual environment:
    .venv\\Scripts\\python -X utf8 -m scraper_comparison.run_comparison
Writes scraper_comparison/results.md.
"""

import datetime
import json
import os
import warnings

import lxml.html
import newspaper
import trafilatura
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST
from headline_antidote.browser_visibility import BrowserVerifier, rendered_visible_text

from .pages import TEST_PAGES

warnings.filterwarnings("ignore", message="nltk is not installed")

RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.md")
JSON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "benchmark", "results", "example_pages.json")
PAGE_URL = "https://example.com/news/article"
ANTIDOTE = "headline-antidote"


def first_line(text):
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


# Each extractor returns (scraped text, the document the guard should read).
# HTML parsers read the raw HTML. Browsers read the DOM after JavaScript has run, so the
# guard is given that rendered DOM (page.content()) to see the same document.

def _h1_or_empty(elements):
    return elements[0].text_content() if elements else ""


def extract_with_beautifulsoup(html, browser_page):
    heading = BeautifulSoup(html, "lxml").find("h1")
    return (heading.get_text() if heading else ""), html


def extract_with_lxml(html, browser_page):
    # What Scrapy's selectors return for "h1 ::text", joined.
    return _h1_or_empty(lxml.html.document_fromstring(html).xpath("//h1")), html


def extract_trafilatura_title(html, browser_page):
    return (trafilatura.bare_extraction(html, with_metadata=True).title or ""), html


def extract_trafilatura_body(html, browser_page):
    return first_line(trafilatura.bare_extraction(html, with_metadata=True).text), html


def _newspaper_article(html):
    article = newspaper.Article(url="https://example.com/news/article")
    article.download(input_html=html)
    article.parse()
    return article


def extract_newspaper_title(html, browser_page):
    return (_newspaper_article(html).title or ""), html


def extract_newspaper_body(html, browser_page):
    return first_line(_newspaper_article(html).text), html


def extract_playwright_inner_text(html, browser_page):
    browser_page.set_content(html)
    return browser_page.locator("h1").first.inner_text(), browser_page.content()


def extract_playwright_text_content(html, browser_page):
    browser_page.set_content(html)
    return browser_page.locator("h1").first.text_content(), browser_page.content()


def extract_playwright_visibility_walker(html, browser_page):
    browser_page.set_content(html)
    return rendered_visible_text(browser_page.locator("h1").first), browser_page.content()


# (name, function, reads the headline element). Body-text extractors do not read the
# headline element, so their output is not compared with it; the guard still checks the raw HTML.
EXTRACTORS = [
    ("BeautifulSoup `h1.get_text()`", extract_with_beautifulsoup, True),
    ("lxml `text_content()` (Scrapy-style)", extract_with_lxml, True),
    ("trafilatura title", extract_trafilatura_title, True),
    ("trafilatura body, first line", extract_trafilatura_body, False),
    ("newspaper4k title", extract_newspaper_title, True),
    ("newspaper4k body, first line", extract_newspaper_body, False),
    ("Playwright + Chrome `inner_text()`", extract_playwright_inner_text, True),
    ("Playwright + Chrome `text_content()`", extract_playwright_text_content, True),
    ("Playwright + Chrome visibility walker", extract_playwright_visibility_walker, True),
]


def printable(text, limit=70):
    shown = []
    for character in text:
        code_point = ord(character)
        if 0xE0000 <= code_point <= 0xE007F:
            shown.append("␠")  # stand-in for invisible tag characters
        elif character == "​":
            shown.append("[ZWSP]")
        elif character == "|":
            shown.append("\\|")
        elif character == "\n":
            shown.append(" ↵ ")  # line break inside the scraped text
        else:
            shown.append(character)
    joined = "".join(shown)
    if len(joined) > limit:
        joined = joined[:limit - 1] + "…"
    return joined


def outcome(page, survives, verdict):
    """Short label for one guard placement on one page/extractor."""
    if not page.is_attack:
        return "ok" if verdict == "pass" else f"**false alarm ({verdict})**"
    if verdict != "pass":
        return verdict
    if survives:
        return "**MISSED**"
    return "pass (attack did not reach model)"


def antidote_reading(page, guard, verifier):
    """headline-antidote used in place of the scraper's extraction: extract_article, then the browser
    check when it asks for one and a verifier is given. An attack gets through when it reaches the
    headline or body and the verdict is pass."""
    article = guard.extract_article(page.html)
    browser_checked = verifier is not None and article.needs_browser_check
    if browser_checked:
        article = guard.verify_article_in_browser(article, page.html, PAGE_URL, verifier)
    reached = page.is_attack and page.attack_survives(article.headline + " " + article.body)
    return {"headline": article.headline, "body": article.body, "verdict": article.verdict, "reached": reached,
            "got_through": reached and article.verdict == "pass", "browser_checked": browser_checked}


def write_json(pages_readings, antidote_readings, chrome_version):
    """benchmark/results/example_pages.json: every reading of every page, and the totals the chart uses."""
    readers = [reading["reader"] for reading in pages_readings[0][1]]
    summary = {reader: {"reached": 0, "got_through_beside": 0, "false_alarms_beside": 0} for reader in readers}
    summary[ANTIDOTE] = {"got_through": 0, "reached_flagged": 0, "false_alarms": 0}
    pages = []
    for (page, readings), antidote in zip(pages_readings, antidote_readings):
        for reading in readings:
            totals = summary[reading["reader"]]
            totals["reached"] += reading["got_through_alone"]
            totals["got_through_beside"] += reading["got_through_beside"]
            totals["false_alarms_beside"] += not page.is_attack and reading["verdict_beside"] != "pass"
        totals = summary[ANTIDOTE]
        totals["got_through"] += antidote["got_through"]
        totals["reached_flagged"] += antidote["reached"] and not antidote["got_through"]
        totals["false_alarms"] += not page.is_attack and antidote["verdict"] != "pass"
        pages.append({"name": page.name, "description": page.description, "is_attack": page.is_attack,
                      "html": page.html, "readings": readings, "antidote": antidote})
    attack_count = sum(page.is_attack for page in TEST_PAGES)
    document = {"generated": datetime.date.today().isoformat(), "chrome": chrome_version,
                "attack_count": attack_count, "clean_count": len(TEST_PAGES) - attack_count,
                "readers": readers, "pages": pages, "summary": summary}
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8", newline="") as file:
        json.dump(document, file, ensure_ascii=False, indent=1)
    return summary


def main():
    guard = HeadlineAntidote(PAPER_WATCHLIST)
    rows_by_page = []
    # Per extractor: attacks reaching its text, misses and false alarms per guard placement.
    tallies = {}
    for extractor_name, _, _ in EXTRACTORS:
        tallies[extractor_name] = {
            "reached": 0, "after_missed": 0, "after_false": 0, "beside_missed": 0, "beside_false": 0,
        }
    # The JSON leaves out the visibility walker: it is headline-antidote's own browser reader, not a scraper.
    pages_readings = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        chrome_version = browser.version
        browser_page = browser.new_page()
        for page in TEST_PAGES:
            rows = []
            readings = []
            for extractor_name, extract, reads_headline_element in EXTRACTORS:
                try:
                    scraped_text, document_for_guard = extract(page.html, browser_page)
                except Exception as error:  # report, do not hide, a scraper failure
                    scraped_text, document_for_guard = f"<error: {error}>", page.html
                survives = page.is_attack and page.attack_survives(scraped_text)
                after_verdict = guard.analyze(scraped_text).verdict
                beside_verdict = guard.analyze_html(
                    document_for_guard, "//h1", scraped_text if reads_headline_element else None,
                    rendered_by_browser=(extract is extract_playwright_visibility_walker),
                ).verdict
                after_label = outcome(page, survives, after_verdict)
                beside_label = outcome(page, survives, beside_verdict)
                extractor_tally = tallies[extractor_name]
                if survives:
                    extractor_tally["reached"] += 1
                for placement, label in (("after", after_label), ("beside", beside_label)):
                    if "MISSED" in label:
                        extractor_tally[placement + "_missed"] += 1
                    if "false alarm" in label:
                        extractor_tally[placement + "_false"] += 1
                rows.append((extractor_name, printable(scraped_text), "yes" if survives else "no",
                             after_label, beside_label))
                if extract is extract_playwright_visibility_walker:
                    continue
                readings.append({"reader": extractor_name.replace("`", ""), "text": scraped_text, "reached": survives,
                                 "verdict_beside": beside_verdict, "got_through_alone": survives,
                                 "got_through_beside": "MISSED" in beside_label,
                                 "outcome_beside": beside_label.replace("*", "")})
            rows_by_page.append((page, rows))
            pages_readings.append((page, readings))
        browser.close()

    with BrowserVerifier() as verifier:
        antidote_readings = [antidote_reading(page, guard, verifier) for page in TEST_PAGES]
    antidote_summary = write_json(pages_readings, antidote_readings, chrome_version)[ANTIDOTE]
    print(f"{ANTIDOTE} (extract_article, then the browser check): {antidote_summary}")

    attack_page_count = 0
    for page in TEST_PAGES:
        if page.is_attack:
            attack_page_count += 1
    lines = [
        "# Scraper comparison",
        "",
        "Generated by `scraper_comparison/run_comparison.py`. Versions: "
        f"beautifulsoup4 {BeautifulSoup.__module__ and __import__('bs4').__version__}, "
        f"trafilatura {trafilatura.__version__}, newspaper4k {newspaper.__version__}, "
        "Playwright driving the installed Google Chrome.",
        "",
        "Two guard placements are compared:",
        "",
        "- **after**: `guard.analyze(scraped_text)`, the guard only sees what the scraper produced.",
        "- **beside**: `guard.analyze_html(document, \"//h1\", scraped_text)`, the guard reads the same "
        "document as the scraper (raw HTML for HTML parsers, the rendered DOM for browsers) and compares "
        "it with the scraper's output.",
        "",
        "`MISSED` = the attack reached the scraper's text and the guard said `pass`.",
        "",
        "Body-text extractors do not read the headline element, so for them the **beside** guard "
        "checks the raw HTML without comparing texts.",
        "",
        "## Summary",
        "",
        f"{len(TEST_PAGES)} pages: {attack_page_count} attacks and "
        f"{len(TEST_PAGES) - attack_page_count} clean controls.",
        "",
        "| Extractor | Attacks reaching the model | Missed, guard after | Missed, guard beside "
        "| False alarms, after | False alarms, beside |",
        "|---|---|---|---|---|---|",
    ]
    for extractor_name, _, _ in EXTRACTORS:
        extractor_tally = tallies[extractor_name]
        lines.append(
            f"| {extractor_name} | {extractor_tally['reached']} | {extractor_tally['after_missed']} "
            f"| {extractor_tally['beside_missed']} | {extractor_tally['after_false']} "
            f"| {extractor_tally['beside_false']} |"
        )
    lines.append("")
    for page, rows in rows_by_page:
        lines.append(f"## `{page.name}`: {page.description}")
        lines.append("")
        lines.append("| Extractor | Scraped headline | Attack reaches model | Guard after | Guard beside |")
        lines.append("|---|---|---|---|---|")
        for row in rows:
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")
    with open(RESULTS_PATH, "w", encoding="utf-8", newline="") as file:
        file.write("\n".join(lines))
    summary_end = lines.index("## `" + TEST_PAGES[0].name + "`: " + TEST_PAGES[0].description)
    print("\n".join(lines[:summary_end]))


if __name__ == "__main__":
    main()
