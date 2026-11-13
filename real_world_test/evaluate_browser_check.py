"""Runs the browser check (warm Chrome, page served from the saved HTML) on every saved
live page, to measure its cost and whether it raises false alarms on clean pages.

Chrome loads each page's scripts and stylesheets from the live site; images, media and
fonts are blocked. Run from the project root:
    .venv\\Scripts\\python -X utf8 -m real_world_test.evaluate_browser_check [--data DIRECTORY] [--same-site] [--triaged-only]
Writes browser_check_report.md (in real_world_test/ for the baseline set, else in the data
directory). Chrome is restarted every RESTART_PAGES pages, so memory held by third-party
scripts doesn't build up over a long run.
"""

import time
import warnings

from headline_guard import HeadlineGuard, PAPER_WATCHLIST
from headline_guard.browser_visibility import BrowserVerifier

from .page_data import data_arguments, load_pages, read_page, report_path

warnings.filterwarnings("ignore")

RESTART_PAGES = 25


def percentile(values, fraction):
    ordered = sorted(values)
    position = min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))
    return round(ordered[position], 1)


def main():
    arguments = data_arguments(("--same-site", "--triaged-only"))
    data_directory = arguments.data_directory
    guard = HeadlineGuard(PAPER_WATCHLIST)
    pages = load_pages(data_directory)
    rows = []
    render_milliseconds = []
    escalated_milliseconds = []
    new_flag_lines = []
    verdicts_after = {}
    started_all = time.perf_counter()
    same_site_only = arguments.same_site
    with BrowserVerifier(same_site_only=same_site_only) as verifier:
        verifier.render("https://guard-test.invalid/", "<html><body><h1>warm up</h1></body></html>")
        rendered_count = 0
        for page_entry in pages:
            html_text = read_page(data_directory, page_entry)
            article = guard.extract_article(html_text, feed_title=page_entry["feed_title"])
            if arguments.triaged_only and not article.needs_browser_check:
                continue
            rendered_count += 1
            if rendered_count % RESTART_PAGES == 0:
                verifier.close()
                verifier.start()
            verified = guard.verify_article_in_browser(article, html_text, page_entry["url"], verifier)
            render_milliseconds.append(verified.browser_milliseconds)
            if article.needs_browser_check:
                escalated_milliseconds.append(verified.browser_milliseconds)
            verdicts_after[verified.verdict] = verdicts_after.get(verified.verdict, 0) + 1
            previous_flags = set()
            for flag in article.flags:
                previous_flags.add((flag.kind, flag.original))
            for flag in verified.flags:
                if (flag.kind, flag.original) not in previous_flags:
                    new_flag_lines.append(
                        f"- {page_entry['file']} {page_entry['source']} [{flag.field}] `{flag.kind}` "
                        f"({flag.severity}): {flag.original[:100]!r}: {flag.detail[:140]}"
                    )
            rows.append((page_entry, article, verified))
            print(f"{page_entry['file']} {page_entry['source']}: {article.verdict} -> {verified.verdict} "
                  f"in {verified.browser_milliseconds:.0f} ms, body {len(article.body)} -> {len(verified.body)}")
    total_seconds = time.perf_counter() - started_all

    loading = "only from each page's own site" if same_site_only else "from the live sites"
    lines = ["# Browser check on the saved live pages", "",
             f"{len(rows)} pages, rendered from the saved HTML in a warm Chrome (scripts and stylesheets "
             f"loaded {loading}; images, media and fonts blocked).", "",
             "| | Value |", "|---|---|",
             f"| Render time p50 / p95 / max | {percentile(render_milliseconds, 0.5)} / "
             f"{percentile(render_milliseconds, 0.95)} / {percentile(render_milliseconds, 1.0)} ms |",
             f"| Pages the static reading sent to the browser | {len(escalated_milliseconds)} / {len(pages)} |",
             f"| Verdicts after the browser check (all pages) | "
             + ", ".join(f"{verdict}: {count}" for verdict, count in sorted(verdicts_after.items())) + " |",
             f"| Total wall time | {total_seconds:.0f} s |", "",
             "## Flags the browser check added (these pages are presumably clean)", ""]
    lines.extend(new_flag_lines or ["- none"])
    lines.append("")
    lines.append("## Every page")
    lines.append("")
    lines.append("| Page | Sent to browser? | Verdict before → after | Render ms | Body chars before → after |")
    lines.append("|---|---|---|---|---|")
    for page_entry, article, verified in rows:
        lines.append(f"| {page_entry['file']} {page_entry['source']} | {'yes' if article.needs_browser_check else 'no'} "
                     f"| {article.verdict} → {verified.verdict} | {verified.browser_milliseconds:.0f} "
                     f"| {len(article.body)} → {len(verified.body)} |")
    report_name = "browser_check_report.md"
    if same_site_only:
        report_name = "browser_check_report_same_site.md"
    if arguments.triaged_only:
        report_name = report_name.replace(".md", "_triaged.md")
    with open(report_path(arguments, report_name), "w", encoding="utf-8") as file:
        file.write("\n".join(lines))
    print("\n".join(lines[:12]))


if __name__ == "__main__":
    main()
