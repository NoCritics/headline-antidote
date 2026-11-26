"""Draws the benchmark charts from benchmark/results/*.json into benchmark/charts/*.png.

Needs matplotlib, which is not a dependency of the project:
    python -X utf8 benchmark/charts.py                    # every chart
    python -X utf8 benchmark/charts.py example_pages      # only the named ones
"""

import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402 reason=the backend must be chosen before pyplot loads
from matplotlib.patches import Patch  # noqa: E402 reason=as above

FOLDER = os.path.dirname(os.path.abspath(__file__))
RESULTS = os.path.join(FOLDER, "results")
CHARTS = os.path.join(FOLDER, "charts")
ANTIDOTE = "headline-antidote"
DATA_SETS = ["data", "data_2026-11-09"]
PLAIN_ATTACK_NAMES = {"body: paragraph removed by JavaScript (no name)":
                      "a script that removes a paragraph without naming it"}

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
ALONE = "#2a78d6"
WITH_ANTIDOTE = "#eb6834"
VERDICT_COLORS = {"pass": "#1baf7a", "review": "#eda100", "quarantine": "#e34948"}
DPI = 200

plt.rcParams.update({"font.family": ["Segoe UI", "DejaVu Sans"], "font.size": 9, "text.color": INK,
                     "axes.edgecolor": AXIS, "axes.labelcolor": INK_SECONDARY, "xtick.color": INK_SECONDARY,
                     "ytick.color": INK, "figure.facecolor": SURFACE, "axes.facecolor": SURFACE})


def load(name):
    with open(os.path.join(RESULTS, name), encoding="utf-8") as file:
        return json.load(file)


def new_figure(rows, width=7.6, row_height=0.42, extra_height=1.5):
    figure, axes = plt.subplots(figsize=(width, rows * row_height + extra_height), dpi=DPI)
    style_axes(axes)
    return figure, axes


def style_axes(axes):
    axes.grid(axis="x", color=GRID, linewidth=0.8)
    axes.set_axisbelow(True)
    for side in ("top", "right", "bottom"):
        axes.spines[side].set_visible(False)
    axes.tick_params(axis="x", length=0, labelsize=8)
    axes.tick_params(axis="y", length=0, labelsize=9)


def label_bar(axes, value, position, text, limit):
    """The value printed just past the end of its bar."""
    axes.text(value + limit * 0.01, position, text, va="center", ha="left", fontsize=8, color=INK_SECONDARY)


def finish(figure, title, subtitle, file_name, footnote=""):
    """Title and subtitle above the plot, an optional footnote below it, then the PNG."""
    height = figure.get_figheight()
    figure.text(0.02, 0.975, title, ha="left", va="top", fontsize=13, fontweight="bold", color=INK)
    figure.text(0.02, 0.975 - 0.32 / height, subtitle, ha="left", va="top", fontsize=8.5,
                color=INK_SECONDARY, linespacing=1.4)
    bottom = 0
    if footnote:
        figure.text(0.02, 0.12 / height, footnote, ha="left", va="bottom", fontsize=8, color=INK_SECONDARY,
                    linespacing=1.4)
        bottom = (0.2 + 0.17 * (footnote.count("\n") + 1)) / height
    top = 1 - (0.6 + 0.17 * (subtitle.count("\n") + 1)) / height
    figure.tight_layout(rect=(0, bottom, 1, top))
    os.makedirs(CHARTS, exist_ok=True)
    figure.savefig(os.path.join(CHARTS, file_name), facecolor=SURFACE)
    plt.close(figure)
    print("wrote", os.path.join(CHARTS, file_name))


def example_pages_chart():
    results = load("example_pages.json")
    summary = results["summary"]
    total = results["attack_count"]
    readers = results["readers"]
    rows = len(readers) + 1
    figure, axes = new_figure(rows)
    bar_height = 0.36
    positions = list(range(rows))[::-1]
    for reader, position in zip(readers, positions):
        alone = summary[reader]["reached"]
        beside = summary[reader]["got_through_beside"]
        axes.barh(position + bar_height / 2, alone, height=bar_height, color=ALONE)
        axes.barh(position - bar_height / 2, beside, height=bar_height, color=WITH_ANTIDOTE)
        label_bar(axes, alone, position + bar_height / 2, str(alone), total)
        label_bar(axes, beside, position - bar_height / 2, str(beside), total)
    antidote = summary[ANTIDOTE]["got_through"]
    axes.barh(positions[-1], antidote, height=bar_height, color=WITH_ANTIDOTE)
    label_bar(axes, antidote, positions[-1], str(antidote), total)
    axes.set_yticks(positions, readers + ["headline-antidote (extract_article)"])
    axes.set_xlim(0, total)
    axes.set_xticks(range(0, total + 1, 5))
    legend = [Patch(color=ALONE), Patch(color=WITH_ANTIDOTE)]
    axes.legend(legend, ["Scraper alone", "Scraper + headline-antidote"], loc="lower right", frameon=False,
                fontsize=8.5)
    finish(figure, f"Attacks that reach the model: {total} example pages",
           "headline-antidote was built against these pages.\n"
           "An attack gets through when the model gets the hidden text with no warning.", "example_pages.png")


def share_text(through, variants):
    share = 100 * through / variants if variants else 0
    shown_share = f"{share:.1f}" if 0 < share < 1 else f"{share:.0f}"
    return f"{shown_share}%  ({through} of {variants})"


def _real_page_totals():
    """Per attack group: {reader: [variants, reached, errors, ambiguous]} summed over both sets, the
    antidote's [variants, got_through, browser_errors], its got_through per attack, the sites, the pages
    read and the pages with a body to splice into."""
    groups = {"headline": {}, "body": {}}
    antidote = {"headline": [0, 0, 0], "body": [0, 0, 0]}
    antidote_by_attack = {}
    sites = set()
    used_pages = 0
    body_pages = 0
    for data_name in DATA_SETS:
        results = load(f"real_pages_{data_name}.json")
        sites.update(results["sites"])
        used_pages += results["used_pages"]
        body_pages += results["used_pages"] - results["pages_without_body_anchor"]
        for attack in results["attacks"]:
            readers = groups[attack["where"]]
            for reader, counts in attack["readers"].items():
                totals = readers.setdefault(reader, [0, 0, 0, 0])
                for index, key in enumerate(("variants", "reached", "errors", "ambiguous")):
                    totals[index] += counts[key]
            for index, key in enumerate(("variants", "got_through", "browser_errors")):
                antidote[attack["where"]][index] += attack["antidote"][key]
            antidote_by_attack[attack["name"]] = (antidote_by_attack.get(attack["name"], 0)
                                                  + attack["antidote"]["got_through"])
    return groups, antidote, antidote_by_attack, sites, used_pages, body_pages


def real_pages_chart():
    groups, antidote, antidote_by_attack, sites, used_pages, body_pages = _real_page_totals()
    rows = sum(len(readers) + 1 for readers in groups.values())
    figure, (headline_axes, body_axes) = plt.subplots(
        2, 1, figsize=(7.6, rows * 0.36 + 2.2), dpi=DPI,
        gridspec_kw={"height_ratios": [len(groups["headline"]) + 1, len(groups["body"]) + 1]})
    for axes, where, heading in ((headline_axes, "headline", "Headline attacks, in the <h1>"),
                                  (body_axes, "body", "Body attacks, after the first paragraph")):
        style_axes(axes)
        readers = groups[where]
        names = list(readers) + [ANTIDOTE]
        positions = list(range(len(names)))[::-1]
        for name, position in zip(names, positions):
            if name == ANTIDOTE:
                variants, through, _ = antidote[where]
                color = WITH_ANTIDOTE
            else:
                variants, through, _, _ = readers[name]
                color = ALONE
            share = 100 * through / variants if variants else 0
            axes.barh(position, share, height=0.6, color=color)
            label_bar(axes, share, position, share_text(through, variants), 100)
        axes.set_yticks(positions, names)
        axes.set_xlim(0, 100)
        axes.set_xticks(range(0, 101, 25), [f"{tick}%" for tick in range(0, 101, 25)])
        axes.set_title(heading, loc="left", fontsize=10, fontweight="bold", color=INK, pad=6)
    headline_axes.legend([Patch(color=ALONE), Patch(color=WITH_ANTIDOTE)], ["Scraper alone", ANTIDOTE],
                         loc="lower right", frameon=False, fontsize=8.5)
    subtitle = (f"{antidote['headline'][0] // used_pages} headline attacks on each of {used_pages} pages from "
                f"{len(sites)} news sites, and {antidote['body'][0] // body_pages} body attacks on {body_pages} of them.")
    footnotes = ["trafilatura and newspaper4k don't take the title from the <h1>, where these attacks are."]
    worst_attack, worst_count = max(antidote_by_attack.items(), key=lambda item: item[1])
    body_misses = antidote["body"][1]
    if body_misses and worst_count * 2 >= body_misses:
        plain_name = PLAIN_ATTACK_NAMES.get(worst_attack, worst_attack.split(": ", 1)[-1])
        footnotes.append(f"{worst_count} of headline-antidote's {body_misses} body misses are one attack: {plain_name}.")
    rebuilding = load("rebuilding.json")
    rebuilt_unsure = sum(count for name, count in rebuilding["body_variants_sent_leaking"].items()
                         if "removed by JavaScript" not in name)
    footnotes.append(f"On {len(rebuilding['rebuilding_pages'])} of {rebuilding['pages_read']} pages, scripts rebuild "
                     "the article and drop the attack, so Chrome scores better than it should.")
    footnotes.append(f"The same rebuild could hide up to {rebuilt_unsure} more headline-antidote misses.")
    finish(figure, "Attacks that reach the model: real news pages", subtitle, "real_pages.png",
           footnote="\n".join(footnotes))


def false_alarms_chart():
    results = load("clean.json")
    rows = []
    for data_name, label in zip(DATA_SETS, ("Nov 7", "Nov 9")):
        pages = results["pages"][data_name]
        rows.append((f"Pages, {label} ({pages['count']:,})", pages["end_to_end"], pages["count"]))
    for data_name, label in zip(DATA_SETS, ("Nov 7", "Nov 9")):
        headlines = results["headlines"][data_name]
        rows.append((f"Headlines, {label} ({headlines['count']:,})", headlines["verdicts"], headlines["count"]))
    figure, axes = new_figure(len(rows), row_height=0.5)
    positions = list(range(len(rows)))[::-1]
    for (label, verdicts, count), position in zip(rows, positions):
        start = 0.0
        outside = []
        for verdict, color in VERDICT_COLORS.items():
            share = 100 * verdicts[verdict] / count
            axes.barh(position, share, left=start, height=0.6, color=color, edgecolor=SURFACE, linewidth=1)
            if share >= 9:
                axes.text(start + share / 2, position, f"{verdicts[verdict]:,}", ha="center", va="center",
                          fontsize=8, color="white", fontweight="bold")
            elif verdicts[verdict]:
                outside.append(f"{verdicts[verdict]:,} {verdict}")
            start += share
        if outside:
            axes.text(101, position, ", ".join(outside), ha="left", va="center", fontsize=8, color=INK_SECONDARY)
    axes.set_yticks(positions, [label for label, _, _ in rows])
    axes.set_xlim(0, 100)
    axes.set_xticks(range(0, 101, 25), [f"{tick}%" for tick in range(0, 101, 25)])
    legend = [Patch(color=color) for color in VERDICT_COLORS.values()]
    axes.legend(legend, list(VERDICT_COLORS), loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3,
                frameon=False, fontsize=8.5)
    page_count = sum(results["pages"][data_name]["count"] for data_name in DATA_SETS)
    headline_count = sum(results["headlines"][data_name]["count"] for data_name in DATA_SETS)
    finish(figure, "Verdicts on clean news",
           f"{page_count} saved news pages and {headline_count:,} feed headlines, with no attacks.", "false_alarms.png")


CHARTS_BY_NAME = {"example_pages": example_pages_chart, "real_pages": real_pages_chart,
                  "false_alarms": false_alarms_chart}


def main():
    for name in sys.argv[1:] or list(CHARTS_BY_NAME):
        CHARTS_BY_NAME[name]()


if __name__ == "__main__":
    main()
