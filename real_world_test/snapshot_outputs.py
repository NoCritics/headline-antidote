"""Old-versus-new equivalence check for refactors and optimizations: records everything the
static reading returns for every saved page, then compares two such records.

    .venv\\Scripts\\python -X utf8 -m real_world_test.snapshot_outputs --out before.json
    ... change the code ...
    .venv\\Scripts\\python -X utf8 -m real_world_test.snapshot_outputs --out after.json
    .venv\\Scripts\\python -X utf8 -m real_world_test.snapshot_outputs --compare before.json after.json

Each page is read twice: with its external stylesheets, the feed title and the feed's text,
as a pipeline would, and from the HTML alone, so the page's own <style> rules are tested
without the external ones.
"""

import argparse
import dataclasses
import json
import os
import sys
import warnings

from headline_guard import HeadlineGuard
from headline_guard.watchlists import PAPER_WATCHLIST

from .page_data import TEST_DIRECTORY, load_pages, load_stylesheet_entries, load_stylesheets, read_page

DEFAULT_DATA_DIRECTORIES = ["data", "data_2026-11-09"]


def article_record(article):
    flags = []
    for flag in article.flags:
        flags.append(dataclasses.asdict(flag))
    return {
        "headline": article.headline,
        "headline_source": article.headline_source,
        "body": article.body,
        "verdict": article.verdict,
        "flags": flags,
        "tickers": article.tickers,
        "metadata_titles": article.metadata_titles,
        "browser_check_reasons": article.browser_check_reasons,
        "headline_xpath": article.headline_xpath,
        "heading_text": article.heading_text,
        "heading_full_text": article.heading_full_text,
        "hidden_ending": article.hidden_ending,
    }


def snapshot(data_names):
    guard = HeadlineGuard(PAPER_WATCHLIST)
    records = {}
    for data_name in data_names:
        data_directory = os.path.join(TEST_DIRECTORY, data_name)
        stylesheet_entries = load_stylesheet_entries(data_directory)
        for page_entry in load_pages(data_directory):
            html_text = read_page(data_directory, page_entry)
            external_css = load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], []))
            page_key = f"{data_name}/{page_entry['file']}"
            full_reading = guard.extract_article(
                html_text, feed_title=page_entry["feed_title"], stylesheets=external_css,
                feed_body=page_entry.get("feed_body"),
            )
            records[page_key + " full"] = article_record(full_reading)
            records[page_key + " html only"] = article_record(guard.extract_article(html_text))
            print(f"{page_key}: {full_reading.verdict}", flush=True)
    return records


def compare(before_path, after_path):
    with open(before_path, encoding="utf-8") as file:
        before = json.load(file)
    with open(after_path, encoding="utf-8") as file:
        after = json.load(file)
    differences = 0
    for key in sorted(set(before) | set(after)):
        if key not in before or key not in after:
            print(f"{key}: only in {'after' if key in after else 'before'}")
            differences += 1
            continue
        for field_name in before[key]:
            if before[key][field_name] != after[key].get(field_name):
                differences += 1
                print(f"{key}: {field_name} differs")
                print(f"    before: {str(before[key][field_name])[:300]}")
                print(f"    after:  {str(after[key].get(field_name))[:300]}")
    print(f"{len(before)} readings before, {len(after)} after, {differences} differences")
    return differences


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", action="append", help="data directories under real_world_test/ "
                                                        f"(default: {' and '.join(DEFAULT_DATA_DIRECTORIES)})")
    parser.add_argument("--out", help="where to write the snapshot")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    arguments = parser.parse_args()
    if arguments.compare:
        sys.exit(1 if compare(arguments.compare[0], arguments.compare[1]) else 0)
    if not arguments.out:
        parser.error("--out or --compare is required")
    warnings.filterwarnings("ignore")
    records = snapshot(arguments.data or DEFAULT_DATA_DIRECTORIES)
    with open(arguments.out, "w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"{len(records)} readings saved to {arguments.out}")


if __name__ == "__main__":
    main()
