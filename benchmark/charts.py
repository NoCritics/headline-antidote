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


def finish(figure, title, subtitle, file_name, top=0.86):
    figure.text(0.02, 0.975, title, ha="left", va="top", fontsize=13, fontweight="bold", color=INK)
    figure.text(0.02, 0.975 - 0.32 / figure.get_figheight(), subtitle, ha="left", va="top", fontsize=8.5,
                color=INK_SECONDARY, linespacing=1.4)
    figure.tight_layout(rect=(0, 0, 1, top))
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
    axes.set_yticks(positions, readers + ["headline-antidote alone\n(extract_article)"])
    axes.set_xlim(0, total)
    axes.set_xticks(range(0, total + 1, 5))
    legend = [Patch(color=ALONE), Patch(color=WITH_ANTIDOTE)]
    axes.legend(legend, ["Scraper alone", "With headline-antidote"], loc="lower right", frameon=False, fontsize=8.5)
    finish(figure, f"Attacks that get through to the model, of {total}",
           f"{total} poisoned example pages, read by common scrapers alone and with headline-antidote beside them.\n"
           "Got through: the attack reached the model's text with no warning.", "example_pages.png")


def share_text(through, variants):
    share = 100 * through / variants if variants else 0
    shown_share = f"{share:.1f}" if 0 < share < 1 else f"{share:.0f}"
    return f"{shown_share}%  ({through} of {variants})"


def _real_page_totals():
    """Per attack group: {reader: [variants, reached, errors, ambiguous]} summed over both sets, the
    antidote's [variants, got_through, browser_errors], its got_through per attack, and the sites and
    pages read."""
    groups = {"headline": {}, "body": {}}
    antidote = {"headline": [0, 0, 0], "body": [0, 0, 0]}
    antidote_by_attack = {}
    sites = set()
    used_pages = 0
    for data_name in DATA_SETS:
        results = load(f"real_pages_{data_name}.json")
        sites.update(results["sites"])
        used_pages += results["used_pages"]
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
    return groups, antidote, antidote_by_attack, sites, used_pages


def real_pages_chart():
    groups, antidote, antidote_by_attack, sites, used_pages = _real_page_totals()
    rows = sum(len(readers) + 1 for readers in groups.values())
    figure, (headline_axes, body_axes) = plt.subplots(
        2, 1, figsize=(7.6, rows * 0.36 + 2.2), dpi=DPI,
        gridspec_kw={"height_ratios": [len(groups["headline"]) + 1, len(groups["body"]) + 1]})
    left_out = []
    for axes, where, heading in ((headline_axes, "headline", "Headline attacks, spliced into the <h1> only"),
                                  (body_axes, "body", "Body attacks, spliced after the first paragraph")):
        style_axes(axes)
        readers = groups[where]
        names = list(readers) + [ANTIDOTE]
        positions = list(range(len(names)))[::-1]
        for name, position in zip(names, positions):
            if name == ANTIDOTE:
                variants, through, errors = antidote[where]
                color = WITH_ANTIDOTE
                if errors:
                    left_out.append(f"{errors} failed browser checks")
            else:
                variants, through, errors, ambiguous = readers[name]
                color = ALONE
                parts = [f"{count} {label}" for count, label in ((errors, "failed"), (ambiguous, "ambiguous")) if count]
                if parts:
                    left_out.append(f"{name}: {', '.join(parts)}")
            share = 100 * through / variants if variants else 0
            axes.barh(position, share, height=0.6, color=color)
            label_bar(axes, share, position, share_text(through, variants), 100)
        axes.set_yticks(positions, names)
        axes.set_xlim(0, 100)
        axes.set_xticks(range(0, 101, 25), [f"{tick}%" for tick in range(0, 101, 25)])
        axes.set_title(heading, loc="left", fontsize=10, fontweight="bold", color=INK, pad=6)
    subtitle = (f"{len(sites)} news sites, {used_pages} real pages, each attack spliced into every page.\n"
                "Blue: the scraper alone. Orange: headline-antidote, with the browser check on pages it flags.")
    worst_attack, worst_count = max(antidote_by_attack.items(), key=lambda item: item[1])
    body_misses = antidote["body"][1]
    if body_misses and worst_count * 2 >= body_misses:
        subtitle += (f"\n{worst_count} of headline-antidote's {body_misses} body misses are one attack: "
                     f"{worst_attack.split(': ', 1)[1]}.")
    if left_out:
        subtitle += "\nLeft out of the shares: " + "; ".join(left_out) + "."
    finish(figure, "Attacks that get through to the model, on real pages", subtitle, "real_pages.png",
           top=0.92 - 0.035 * (subtitle.count("\n") + 1))


def false_alarms_chart():
    results = load("clean.json")
    rows = []
    for data_name, label in zip(DATA_SETS, ("Nov 7", "Nov 9")):
        pages = results["pages"][data_name]
        rows.append((f"Pages saved {label} ({pages['count']:,})", pages["end_to_end"], pages["count"]))
    for data_name, label in zip(DATA_SETS, ("Nov 7", "Nov 9")):
        headlines = results["headlines"][data_name]
        rows.append((f"Headlines saved {label} ({headlines['count']:,})", headlines["verdicts"], headlines["count"]))
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
                outside.append(f"{verdict} {verdicts[verdict]:,}")
            start += share
        if outside:
            axes.text(101, position, ", ".join(outside), ha="left", va="center", fontsize=8, color=INK_SECONDARY)
    axes.set_yticks(positions, [label for label, _, _ in rows])
    axes.set_xlim(0, 100)
    axes.set_xticks(range(0, 101, 25), [f"{tick}%" for tick in range(0, 101, 25)])
    legend = [Patch(color=color) for color in VERDICT_COLORS.values()]
    axes.legend(legend, list(VERDICT_COLORS), loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3,
                frameon=False, fontsize=8.5)
    finish(figure, "Verdicts on clean news, no attacks",
           "Saved real pages read end to end (stylesheets, feed title, browser check when asked), and feed headlines.\n"
           "Anything but pass on these is a false alarm or a real finding.", "false_alarms.png", top=0.76)


CHARTS_BY_NAME = {"example_pages": example_pages_chart, "real_pages": real_pages_chart,
                  "false_alarms": false_alarms_chart}


def main():
    for name in sys.argv[1:] or list(CHARTS_BY_NAME):
        CHARTS_BY_NAME[name]()


if __name__ == "__main__":
    main()
