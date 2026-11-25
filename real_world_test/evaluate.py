"""Runs the guard on real headlines and pages: false alarms and timings.

These are ordinary, presumably clean news pages, so every flag is either a false alarm
or a real finding, and is listed for manual review.

Run from the project root after collect.py:
    .venv\\Scripts\\python -X utf8 -m real_world_test.evaluate
Writes real_world_test/results.json and real_world_test/report.md.
"""

import json
import os
import statistics
import time
import warnings

import lxml.html
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

from headline_guard import HeadlineGuard, PAPER_WATCHLIST
from headline_guard.browser_visibility import rendered_visible_text

warnings.filterwarnings("ignore")

TEST_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
DATA_DIRECTORY = os.path.join(TEST_DIRECTORY, "data")
PAGES_DIRECTORY = os.path.join(DATA_DIRECTORY, "pages")
NAVIGATION_TIMEOUT_MILLISECONDS = 30000


def decode_page(raw_bytes, declared_encoding):
    for encoding in ("utf-8", declared_encoding or "utf-8"):
        try:
            return raw_bytes.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw_bytes.decode("utf-8", errors="replace")


def describe_flags(result):
    descriptions = []
    for flag in result.flags:
        descriptions.append({
            "kind": flag.kind, "severity": flag.severity,
            "original": flag.original[:120], "evidence": flag.evidence,
        })
    return descriptions


def percentile(values, fraction):
    if not values:
        return None
    ordered = sorted(values)
    position = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return round(ordered[position], 1)


def evaluate_feed_titles(guard):
    with open(os.path.join(DATA_DIRECTORY, "feed_titles.json"), encoding="utf-8") as file:
        feed_titles = json.load(file)
    flagged = []
    started = time.perf_counter()
    for entry in feed_titles:
        result = guard.analyze(entry["title"])
        if result.flags:
            flagged.append({
                "source": entry["source"], "title": entry["title"], "verdict": result.verdict,
                "flags": describe_flags(result),
            })
    microseconds_per_title = (time.perf_counter() - started) * 1e6 / max(1, len(feed_titles))
    return {"count": len(feed_titles), "flagged": flagged, "microseconds_per_title": round(microseconds_per_title, 1)}


def browser_check(browser_context, url, html_text, guard, prefetched_html_bytes=None):
    """Loads the page (live, or our fetched HTML with its assets from the network) and runs browser mode."""
    page = browser_context.new_page()
    outcome = {}
    try:
        if prefetched_html_bytes is not None:
            def serve_fetched_document(route):
                if route.request.url == url and route.request.resource_type == "document":
                    route.fulfill(status=200, body=prefetched_html_bytes, content_type="text/html; charset=utf-8")
                else:
                    route.continue_()
            page.route("**/*", serve_fetched_document)
        started = time.perf_counter()
        page.goto(url, wait_until="load", timeout=NAVIGATION_TIMEOUT_MILLISECONDS)
        outcome["load_milliseconds"] = round((time.perf_counter() - started) * 1000, 1)
        heading = page.locator("h1").first
        if page.locator("h1").count() == 0:
            outcome["status"] = "no h1 after rendering"
            return outcome
        started = time.perf_counter()
        visible_text = rendered_visible_text(heading)
        rendered_document = page.content()
        outcome["walker_milliseconds"] = round((time.perf_counter() - started) * 1000, 1)
        started = time.perf_counter()
        result = guard.analyze_html(rendered_document, "//h1", scraped_text=visible_text, rendered_by_browser=True)
        outcome["guard_milliseconds"] = round((time.perf_counter() - started) * 1000, 1)
        outcome["status"] = "ok"
        outcome["visible_headline"] = visible_text[:200]
        outcome["verdict"] = result.verdict
        outcome["flags"] = describe_flags(result)
    except Exception as error:
        outcome["status"] = f"error: {type(error).__name__}: {str(error)[:150]}"
    finally:
        page.close()
    return outcome


def main():
    guard = HeadlineGuard(PAPER_WATCHLIST)
    feed_results = evaluate_feed_titles(guard)
    print(f"text mode: {feed_results['count']} feed titles, {len(feed_results['flagged'])} flagged, "
          f"{feed_results['microseconds_per_title']} us each")

    with open(os.path.join(DATA_DIRECTORY, "pages.json"), encoding="utf-8") as file:
        pages = json.load(file)
    page_results = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        browser_context = browser.new_context(viewport={"width": 1366, "height": 900})
        for page_entry in pages:
            with open(os.path.join(PAGES_DIRECTORY, page_entry["file"]), "rb") as file:
                raw_bytes = file.read()
            html_text = decode_page(raw_bytes, page_entry.get("encoding"))
            record = dict(page_entry)

            headings = lxml.html.document_fromstring(raw_bytes).xpath("//h1")
            record["h1_count_in_raw_html"] = len(headings)
            if headings:
                started = time.perf_counter()
                scraped_heading = BeautifulSoup(html_text, "lxml").find("h1").get_text()
                record["beautifulsoup_milliseconds"] = round((time.perf_counter() - started) * 1000, 1)
                started = time.perf_counter()
                html_result = guard.analyze_html(html_text, "//h1", scraped_text=scraped_heading)
                record["html_mode_milliseconds"] = round((time.perf_counter() - started) * 1000, 1)
                record["html_mode"] = {
                    "scraped_headline": " ".join(scraped_heading.split())[:200],
                    "verdict": html_result.verdict, "flags": describe_flags(html_result),
                }
            else:
                record["html_mode"] = {"verdict": "no h1 in raw HTML", "flags": []}

            record["browser_live"] = browser_check(browser_context, page_entry["url"], html_text, guard)
            record["browser_prefetched"] = browser_check(
                browser_context, page_entry["url"], html_text, guard, prefetched_html_bytes=raw_bytes
            )
            page_results.append(record)
            print(f"{page_entry['file']} {page_entry['source']}: html={record['html_mode']['verdict']} "
                  f"live={record['browser_live'].get('verdict', record['browser_live'].get('status'))} "
                  f"prefetched={record['browser_prefetched'].get('verdict', record['browser_prefetched'].get('status'))}")
        browser.close()

    with open(os.path.join(TEST_DIRECTORY, "results.json"), "w", encoding="utf-8") as file:
        json.dump({"feed_titles": feed_results, "pages": page_results}, file, ensure_ascii=False, indent=1)
    write_report(feed_results, page_results)


def write_report(feed_results, page_results):
    lines = ["# Real-world test", ""]
    lines.append(f"Text mode on {feed_results['count']} real feed headlines: "
                 f"{len(feed_results['flagged'])} flagged, {feed_results['microseconds_per_title']} µs each.")
    lines.append("")

    def tally(mode_key):
        counts = {}
        for record in page_results:
            mode = record.get(mode_key, {})
            label = mode.get("verdict") or mode.get("status") or "missing"
            if label.startswith("error"):
                label = "error"
            counts[label] = counts.get(label, 0) + 1
        return counts

    lines.append(f"## Pages ({len(page_results)})")
    lines.append("")
    lines.append("| Mode | Verdicts |")
    lines.append("|---|---|")
    for mode_key, mode_name in (("html_mode", "HTML mode (raw HTML + BeautifulSoup text)"),
                                ("browser_live", "Browser mode, live page"),
                                ("browser_prefetched", "Browser mode, fetched HTML + live assets")):
        counts = tally(mode_key)
        parts = []
        for label, count in sorted(counts.items()):
            parts.append(f"{label}: {count}")
        lines.append(f"| {mode_name} | {', '.join(parts)} |")
    lines.append("")

    lines.append("## Timings (milliseconds, p50 / p95)")
    lines.append("")
    timing_rows = [
        ("HTTP fetch of the article", [record.get("fetch_milliseconds") for record in page_results]),
        ("BeautifulSoup h1 extraction", [record.get("beautifulsoup_milliseconds") for record in page_results]),
        ("Guard, HTML mode (whole page)", [record.get("html_mode_milliseconds") for record in page_results]),
        ("Browser: live page load", [record["browser_live"].get("load_milliseconds") for record in page_results]),
        ("Browser: fetched HTML + live assets", [record["browser_prefetched"].get("load_milliseconds") for record in page_results]),
        ("Browser: visibility walker + page.content()", [record["browser_live"].get("walker_milliseconds") for record in page_results]),
        ("Guard, browser mode", [record["browser_live"].get("guard_milliseconds") for record in page_results]),
    ]
    lines.append("| Step | p50 | p95 | n |")
    lines.append("|---|---|---|---|")
    for step_name, raw_values in timing_rows:
        values = []
        for value in raw_values:
            if value is not None:
                values.append(value)
        lines.append(f"| {step_name} | {percentile(values, 0.5)} | {percentile(values, 0.95)} | {len(values)} |")
    lines.append("")

    lines.append("## Every flag, for manual review")
    lines.append("")
    for entry in feed_results["flagged"]:
        for flag in entry["flags"]:
            lines.append(f"- feed title, {entry['source']}: `{flag['kind']}` ({flag['severity']}) "
                         f"in {entry['title']!r}: {flag['evidence']}")
    for record in page_results:
        for mode_key in ("html_mode", "browser_live", "browser_prefetched"):
            for flag in record.get(mode_key, {}).get("flags", []):
                lines.append(f"- {record['file']} {record['source']} [{mode_key}]: `{flag['kind']}` "
                             f"({flag['severity']}) {flag['original']!r}: {flag['evidence']}")
    lines.append("")
    lines.append("## Pages without a usable headline")
    lines.append("")
    for record in page_results:
        problems = []
        if record.get("h1_count_in_raw_html", 0) == 0:
            problems.append("no h1 in raw HTML")
        for mode_key in ("browser_live", "browser_prefetched"):
            status = record.get(mode_key, {}).get("status", "")
            if status and status != "ok":
                problems.append(f"{mode_key}: {status}")
        if problems:
            lines.append(f"- {record['file']} {record['source']} {record['url']}: {'; '.join(problems)}")
    with open(os.path.join(TEST_DIRECTORY, "report.md"), "w", encoding="utf-8") as file:
        file.write("\n".join(lines))


if __name__ == "__main__":
    main()
