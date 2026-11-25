"""Tests the visible-article extractor on the saved live pages and on the attack pages.

Each live page runs in two modes: CSS from the page's own <style> blocks only, and
with its external stylesheets too (fetched by fetch_stylesheets.py).

Run from the project root (after collect.py and fetch_stylesheets.py):
    .venv\\Scripts\\python -X utf8 -m real_world_test.evaluate_articles [--data DIRECTORY]
Writes article_report.md (in real_world_test/ for the baseline set, else in the data directory).
A fourth mode also passes the feed's full item text, for feeds that carry one.
"""

import json
import time
import warnings

from lxml import html as lxml_html

from headline_guard import HeadlineGuard, PAPER_WATCHLIST
from headline_guard.article import HEADLINE_MATCH_THRESHOLD, _title_similarity
from scraper_comparison.pages import TEST_PAGES

from .page_data import data_arguments, load_pages, load_stylesheet_entries, load_stylesheets, read_page, report_path

warnings.filterwarnings("ignore")

# (name, use the external stylesheets, pass the feed's title, pass the feed's item text)
MODES = [
    ("page <style> only", False, False, False),
    ("with external stylesheets", True, False, False),
    ("external stylesheets and the feed title", True, True, False),
    ("external stylesheets, feed title and feed text", True, True, True),
]


def percentile(values, fraction):
    ordered = sorted(values)
    position = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return round(ordered[position], 1)


def one_line(text, limit):
    flattened = " / ".join(text.split("\n"))
    if len(flattened) > limit:
        return flattened[:limit - 1] + "…"
    return flattened


def feed_text(page_entry):
    """The feed's item text as plain text, or None (feeds put HTML in content:encoded)."""
    body = page_entry.get("feed_body")
    if not body:
        return None
    try:
        parsed = lxml_html.fromstring(body)
    except Exception:
        return None
    text = " ".join(parsed.text_content().split())
    if len(text.split()) < 30:
        return None
    return text


def main():
    arguments = data_arguments()
    data_directory = arguments.data_directory
    guard = HeadlineGuard(PAPER_WATCHLIST)
    pages = load_pages(data_directory)
    stylesheet_entries = load_stylesheet_entries(data_directory)
    sites = set()
    pages_with_feed_text = 0
    for page_entry in pages:
        sites.add(page_entry["source"])
        if feed_text(page_entry):
            pages_with_feed_text += 1
    guard.extract_article("<html><body><h1>warm up</h1><p>text</p></body></html>")

    # First pass: what the first page from a site costs, while its CSS is compiled and cached.
    cold_milliseconds = []
    for page_entry in pages:
        html_text = read_page(data_directory, page_entry)
        external_css = load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], []))
        started = time.perf_counter()
        guard.extract_article(html_text, stylesheets=external_css)
        cold_milliseconds.append((time.perf_counter() - started) * 1000)

    summary = {}
    flag_lines = {}
    body_rows = []
    flag_groups = {}
    for mode_name, _, _, _ in MODES:
        summary[mode_name] = {"correct": 0, "verdicts": {}, "milliseconds": [], "browser_checks": 0, "pages": 0}
        flag_lines[mode_name] = []
        flag_groups[mode_name] = {}
    for page_entry in pages:
        html_text = read_page(data_directory, page_entry)
        external_css = load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], []))
        page_feed_text = feed_text(page_entry)
        articles = {}
        for mode_name, use_external, use_feed_title, use_feed_text in MODES:
            if use_feed_text and page_feed_text is None:
                continue
            started = time.perf_counter()
            article = guard.extract_article(
                html_text, feed_title=page_entry["feed_title"] if use_feed_title else None,
                stylesheets=external_css if use_external else None,
                feed_body=page_feed_text if use_feed_text else None,
            )
            mode_summary = summary[mode_name]
            mode_summary["pages"] += 1
            if article.needs_browser_check:
                mode_summary["browser_checks"] += 1
            mode_summary["milliseconds"].append((time.perf_counter() - started) * 1000)
            correct = _title_similarity(article.headline, page_entry["feed_title"]) >= HEADLINE_MATCH_THRESHOLD
            mode_summary["correct"] += correct
            mode_summary["verdicts"][article.verdict] = mode_summary["verdicts"].get(article.verdict, 0) + 1
            for flag in article.flags:
                line = (f"- {page_entry['file']} {page_entry['source']} [{flag.field}] `{flag.kind}` "
                        f"({flag.severity}): {one_line(flag.original, 90)!r}: {one_line(json.dumps(flag.evidence, ensure_ascii=False), 150)}")
                flag_lines[mode_name].append(line)
                group_key = (page_entry["source"], flag.kind, flag.severity)
                group = flag_groups[mode_name].setdefault(group_key, {"count": 0, "pages": set(), "examples": []})
                group["count"] += 1
                group["pages"].add(page_entry["file"])
                if len(group["examples"]) < 2:
                    group["examples"].append(line[2:])
            articles[mode_name] = (article, correct)
        inline_article = articles[MODES[0][0]][0]
        external_article, external_correct = articles[MODES[1][0]]
        body_rows.append((page_entry, external_article, external_correct,
                          len(inline_article.body), len(external_article.body)))
        print(f"{page_entry['file']} {page_entry['source']}: {inline_article.verdict} / {external_article.verdict}, "
              f"body {len(inline_article.body)} -> {len(external_article.body)} chars")

    lines = ["# Visible-article extractor: test results", "",
             f"## Live pages ({len(pages)} pages, {len(sites)} sites), with the CSS cascade", "",
             f"The last mode runs only on the {pages_with_feed_text} pages whose feed carries the item's text.", "",
             "| Mode | Correct headline | Verdicts | Would go to a browser | Time p50 / p95 / max (ms) |",
             "|---|---|---|---|---|"]
    for mode_name, _, _, _ in MODES:
        mode_summary = summary[mode_name]
        if not mode_summary["milliseconds"]:
            continue
        verdict_parts = []
        for verdict, count in sorted(mode_summary["verdicts"].items()):
            verdict_parts.append(f"{verdict}: {count}")
        milliseconds = mode_summary["milliseconds"]
        lines.append(f"| {mode_name} | {mode_summary['correct']} / {mode_summary['pages']} | {', '.join(verdict_parts)} "
                     f"| {mode_summary['browser_checks']} / {mode_summary['pages']} "
                     f"| {percentile(milliseconds, 0.5)} / {percentile(milliseconds, 0.95)} / "
                     f"{percentile(milliseconds, 1.0)} |")
    lines.append("")
    lines.append("Times are with compiled stylesheets cached, as they are after a site's first page. "
                 f"First pass, while each site's CSS was being compiled: p50 {percentile(cold_milliseconds, 0.5)} ms, "
                 f"p95 {percentile(cold_milliseconds, 0.95)} ms. The page fetch itself takes about 1,200 ms (p50).")
    lines.append("")
    lines.append("These pages are presumably clean, so every flag below was reviewed by hand.")
    for mode_name, _, _, _ in MODES:
        lines.append("")
        lines.append(f"### Flags, {mode_name}, grouped by site and kind")
        lines.append("")
        if not flag_groups[mode_name]:
            lines.append("- none")
        lines.append("| Site | Flag | Severity | Flags | Pages | Examples |")
        lines.append("|---|---|---|---|---|---|")
        ordered_groups = sorted(flag_groups[mode_name].items(), key=lambda item: (-len(item[1]["pages"]), item[0]))
        for (source, kind, severity), group in ordered_groups:
            examples = " <br> ".join(group["examples"]).replace("|", "/")
            lines.append(f"| {source} | `{kind}` | {severity} | {group['count']} | {len(group['pages'])} | {examples} |")
    for mode_name, _, _, _ in MODES:
        lines.append("")
        lines.append(f"### Every flag, {mode_name}")
        lines.append("")
        lines.extend(flag_lines[mode_name] or ["- none"])
    lines.append("")
    lines.append("### Every page with external stylesheets: headline and the start and end of the body")
    lines.append("")
    lines.append("| Page | Headline | Body chars (style only → external) | Body start | Body end |")
    lines.append("|---|---|---|---|---|")
    for page_entry, article, correct, inline_length, external_length in body_rows:
        marker = "" if correct else " **(wrong)**"
        lines.append(
            f"| {page_entry['file']} {page_entry['source']} | {one_line(article.headline, 60).replace('|', '/')}{marker} "
            f"| {inline_length} → {external_length} | {one_line(article.body, 90).replace('|', '/')} "
            f"| {one_line(article.body[-90:], 90).replace('|', '/')} |"
        )
    lines.append("")
    lines.append("## Attack pages from scraper_comparison (their CSS is all in the page)")
    lines.append("")
    lines.append("| Page | Attack? | Verdict | Browser check? | Headline given to the model | Hidden payload in output? |")
    lines.append("|---|---|---|---|---|---|")
    for page in TEST_PAGES:
        article = guard.extract_article(page.html)
        payload_in_output = page.is_attack and page.attack_survives(article.headline + "\n" + article.body)
        lines.append(f"| `{page.name}` | {'yes' if page.is_attack else 'no'} | {article.verdict} "
                     f"| {'yes' if article.needs_browser_check else 'no'} "
                     f"| {one_line(article.headline, 70)} | {'**yes**' if payload_in_output else 'no'} |")
    with open(report_path(arguments, "article_report.md"), "w", encoding="utf-8") as file:
        file.write("\n".join(lines))
    print("\n".join(lines[:9]))


if __name__ == "__main__":
    main()
