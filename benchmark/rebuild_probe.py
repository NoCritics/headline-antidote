"""Which real pages rebuild their headline or body with scripts, dropping HTML spliced into them?

Splices a plain visible marker into the headline and after the body anchor of every page Run B uses,
reads the page in headless Chrome, and checks the markers survive. On pages that drop them, Chrome's
reading of an attack says nothing about the attack, and the browser check of headline-antidote sees
the rebuilt page: the body variants it sends there with the payload still in its text are counted per
attack. Writes benchmark/results/rebuilding.json.

Run from the project root (Chrome loads each page's scripts from the live site):
    PYTHONPATH=. .venv/Scripts/python.exe -X utf8 benchmark/rebuild_probe.py
"""

import datetime
import json
import os
import warnings

import lxml.html

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST
from headline_antidote.html_tree import parse_html
from real_world_test import evaluate_injections as harness
from real_world_test.page_data import TEST_DIRECTORY, load_pages, load_stylesheet_entries, load_stylesheets, read_page
from real_world_test.scraper_readings import ChromeReader

warnings.filterwarnings("ignore")

DATA_SETS = ["data", "data_2026-11-09"]
HEADLINE_MARKER = "Quillwort headline marker"
BODY_MARKER = "Quillwort body marker paragraph"
RESULTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "rebuilding.json")


def usable_control(guard, page_entry, control_html, stylesheets):
    """The clean reading of a page Run B uses, or None for a page it skips."""
    control = guard.extract_article(control_html, feed_title=page_entry["feed_title"], stylesheets=stylesheets)
    if harness._title_similarity(control.headline, page_entry["feed_title"]) < harness.HEADLINE_MATCH_THRESHOLD:
        return None
    if len(control.body.split()) < harness.MINIMUM_BODY_WORDS:
        return None
    if harness.leaked(control, harness.HEADLINE_PAYLOAD_CHECK) or harness.leaked(control, harness.BODY_PAYLOAD_CHECK):
        return None
    if harness.find_headline(parse_html(control_html), control) is None:
        return None
    return control


def marked_html(control_html, control):
    root = parse_html(control_html)
    harness.find_headline(root, control).append(harness._span(" " + HEADLINE_MARKER, {}))
    anchor = harness.find_anchor(root, control)
    if anchor is not None:
        anchor.addnext(harness._paragraph(BODY_MARKER, {}))
    return lxml.html.tostring(root, encoding="unicode"), anchor is not None


def body_variants_sent_leaking(guard, page_entry, control_html, control, stylesheets):
    """Names of the body attacks whose static reading still has the payload and goes to the browser check."""
    names = []
    for name, where, splice in harness.ATTACKS:
        if where != "body":
            continue
        root = parse_html(control_html)
        extra_css = splice(root, harness.find_headline(root, control), harness.find_anchor(root, control))
        variant = guard.extract_article(lxml.html.tostring(root, encoding="unicode"),
                                        feed_title=page_entry["feed_title"],
                                        stylesheets=list(stylesheets) + ([extra_css] if extra_css else []))
        if variant.needs_browser_check and harness.leaked(variant, harness.BODY_PAYLOAD_CHECK):
            names.append(name)
    return names


def main():
    guard = HeadlineAntidote(PAPER_WATCHLIST)
    document = {"generated": datetime.date.today().isoformat(), "pages_read": 0, "read_failed": 0,
                "rebuilding_pages": [], "body_variants_sent_leaking": {}}
    with ChromeReader() as chrome:
        for data_name in DATA_SETS:
            data_directory = os.path.join(TEST_DIRECTORY, data_name)
            stylesheet_entries = load_stylesheet_entries(data_directory)
            for page_entry in load_pages(data_directory):
                stylesheets = load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], []))
                control_html = lxml.html.tostring(parse_html(read_page(data_directory, page_entry)), encoding="unicode")
                control = usable_control(guard, page_entry, control_html, stylesheets)
                if control is None:
                    continue
                html, has_anchor = marked_html(control_html, control)
                body_text = chrome.read(page_entry["url"], html)["Chrome body inner_text"]
                label = f"{data_name} {page_entry['file']} {page_entry['source']}"
                if body_text.startswith("<error"):
                    document["read_failed"] += 1
                    print(f"{label}: read failed")
                    continue
                document["pages_read"] += 1
                dropped = [where for where, marker, spliced in (("headline", HEADLINE_MARKER, True),
                                                                ("body", BODY_MARKER, has_anchor))
                           if spliced and marker not in body_text]
                if not dropped:
                    continue
                document["rebuilding_pages"].append({"page": label, "dropped": dropped})
                print(f"{label}: dropped {dropped}")
                if not has_anchor:
                    continue
                for name in body_variants_sent_leaking(guard, page_entry, control_html, control, stylesheets):
                    counts = document["body_variants_sent_leaking"]
                    counts[name] = counts.get(name, 0) + 1
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8", newline="") as file:
        json.dump(document, file, ensure_ascii=False, indent=1)
    print(json.dumps({key: document[key] for key in ("pages_read", "read_failed", "body_variants_sent_leaking")}))
    print(len(document["rebuilding_pages"]), "rebuilding pages")


if __name__ == "__main__":
    main()
