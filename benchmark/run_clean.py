"""Run C of the benchmark: false alarms on clean pages and feed headlines.

Every saved page of both sets is read as a pipeline would read it: its external stylesheets and the
feed's title, then the browser check for pages the static reading sends there. Every saved feed
headline is checked as plain text. Writes benchmark/results/clean.json: verdict counts only.

Run from the project root (Chrome loads each page's scripts and stylesheets from the live site):
    PYTHONPATH=. .venv/Scripts/python.exe -X utf8 benchmark/run_clean.py
"""

import datetime
import json
import os
import warnings

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST
from headline_antidote.browser_visibility import BrowserVerifier
from real_world_test.page_data import (TEST_DIRECTORY, load_pages, load_stylesheet_entries, load_stylesheets,
                                       read_page)

warnings.filterwarnings("ignore")

DATA_SETS = ["data", "data_2026-11-09"]
RESTART_PAGES = 25
VERDICTS = ("pass", "review", "quarantine")
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "clean.json")


def verdict_counts(verdicts):
    counts = dict.fromkeys(VERDICTS, 0)
    for verdict in verdicts:
        counts[verdict] += 1
    return counts


def read_pages(guard, data_name, verifier):
    """Verdicts of every saved page of one set: static, and end to end with the browser check."""
    data_directory = os.path.join(TEST_DIRECTORY, data_name)
    stylesheet_entries = load_stylesheet_entries(data_directory)
    static_verdicts = []
    final_verdicts = []
    browser_checks = 0
    browser_errors = 0
    for page_entry in load_pages(data_directory):
        html = read_page(data_directory, page_entry)
        stylesheets = load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], []))
        article = guard.extract_article(html, feed_title=page_entry["feed_title"], stylesheets=stylesheets)
        static_verdicts.append(article.verdict)
        if not article.needs_browser_check:
            final_verdicts.append(article.verdict)
            continue
        if browser_checks and browser_checks % RESTART_PAGES == 0:
            verifier.close()
            verifier.start()
        browser_checks += 1
        try:
            article = guard.verify_article_in_browser(article, html, page_entry["url"], verifier)
        except Exception as error:  # a failed check leaves the static verdict, and is counted
            browser_errors += 1
            print(f"{data_name} {page_entry['file']}: browser check failed ({type(error).__name__})")
            verifier.close()
            verifier.start()
        final_verdicts.append(article.verdict)
        print(f"{data_name} {page_entry['file']}: {static_verdicts[-1]} -> {article.verdict}")
    return {"count": len(static_verdicts), "static": verdict_counts(static_verdicts),
            "end_to_end": verdict_counts(final_verdicts), "sent_to_browser": browser_checks,
            "browser_errors": browser_errors}


def read_headlines(guard, data_name):
    with open(os.path.join(TEST_DIRECTORY, data_name, "feed_titles.json"), encoding="utf-8") as file:
        entries = json.load(file)
    return {"count": len(entries), "verdicts": verdict_counts(guard.analyze(entry["title"]).verdict for entry in entries)}


def main():
    guard = HeadlineAntidote(PAPER_WATCHLIST)
    document = {"generated": datetime.date.today().isoformat(), "pages": {}, "headlines": {}}
    with BrowserVerifier() as verifier:
        for data_name in DATA_SETS:
            document["pages"][data_name] = read_pages(guard, data_name, verifier)
    for data_name in DATA_SETS:
        document["headlines"][data_name] = read_headlines(guard, data_name)
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8", newline="") as file:
        json.dump(document, file, ensure_ascii=False, indent=1)
    print(json.dumps({key: document[key] for key in ("pages", "headlines")}, indent=1))


if __name__ == "__main__":
    main()
