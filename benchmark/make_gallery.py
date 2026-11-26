"""Builds the attack gallery from benchmark/results/example_pages.json: each example page as a file,
a screenshot of what a reader sees (headless Chrome), and benchmark/README.md with what every
scraper and headline-antidote hand the model.

Run from the project root:
    .venv/Scripts/python.exe -X utf8 benchmark/make_gallery.py
"""

import json
import os
import re
import unicodedata

from playwright.sync_api import sync_playwright

FOLDER = os.path.dirname(os.path.abspath(__file__))
PAGES = os.path.join(FOLDER, "pages")
SCREENSHOTS = os.path.join(FOLDER, "screenshots")
README = os.path.join(FOLDER, "README.md")
CHART_URL = "https://raw.githubusercontent.com/NoCritics/headline-antidote/master/benchmark/charts/{}.png"
SHOWN_CHARACTERS = 80
ATTACK_MARKUP = re.compile(r"<style>.*?</style>|<script>.*?</script>|<h1>.*?</h1>", re.DOTALL)


def shown(text):
    """text on one line, with invisible and format characters written as <U+XXXX>."""
    characters = []
    for character in " ".join(text.split()):
        if unicodedata.category(character) in ("Cf", "Cc", "Mn") or 0xE0000 <= ord(character) <= 0xE007F:
            characters.append(f"<U+{ord(character):04X}>")
        else:
            characters.append(character)
    return "".join(characters)


def escaped(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "\\|")


def table_cell(text):
    """The reading on one line, shortened, with the full text one click away when it is long."""
    text = shown(text)
    if not text:
        return "(nothing)"
    if len(text) <= SHOWN_CHARACTERS:
        return escaped(text)
    return (f"<details><summary>{escaped(text[:SHOWN_CHARACTERS - 1])}…</summary>"
            f"{escaped(text)}</details>")


def outcome(page, reached, got_through, verdict):
    if not page["is_attack"]:
        return "pass" if verdict == "pass" else f"false alarm ({verdict})"
    if got_through:
        return "**gets through**"
    if reached:
        return "reached, flagged"
    return "stopped"


def page_section(page):
    name = page["name"]
    lines = [f"## {name}", "", page["description"] + ".", "",
             f"[The page](pages/{name}.html)", "", f"![What a reader sees on {name}](screenshots/{name}.png)", "",
             "<details><summary>" + ("The attack in the page's HTML" if page["is_attack"] else "The page's HTML")
             + "</summary>", "", "```html",
             *ATTACK_MARKUP.findall(page["html"]), "```", "", "</details>", "",
             "| Reader | What the model gets | Alone | With headline-antidote beside it |", "|---|---|---|---|"]
    for reading in page["readings"]:
        alone = outcome(page, reading["reached"], reading["got_through_alone"], "pass") if page["is_attack"] else "—"
        beside = outcome(page, reading["reached"], reading["got_through_beside"], reading["verdict_beside"])
        lines.append(f"| {reading['reader']} | {table_cell(reading['text'])} | {alone} | {beside} |")
    antidote = page["antidote"]
    own = outcome(page, antidote["reached"], antidote["got_through"], antidote["verdict"])
    checked = ", after the browser check" if antidote["browser_checked"] else ""
    lines.append(f"| headline-antidote alone (extract_article{checked}) | {table_cell(antidote['headline'])} "
                 f"| {own} | |")
    lines.append("")
    return lines


def write_pages_and_screenshots(pages):
    os.makedirs(PAGES, exist_ok=True)
    os.makedirs(SCREENSHOTS, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        tab = browser.new_page(viewport={"width": 1366, "height": 900})
        for page in pages:
            with open(os.path.join(PAGES, page["name"] + ".html"), "w", encoding="utf-8", newline="") as file:
                file.write(page["html"])
            tab.set_content(page["html"])
            tab.locator("article").screenshot(path=os.path.join(SCREENSHOTS, page["name"] + ".png"))
        browser.close()


def main():
    with open(os.path.join(FOLDER, "results", "example_pages.json"), encoding="utf-8") as file:
        results = json.load(file)
    pages = results["pages"]
    write_pages_and_screenshots(pages)
    lines = ["# Attack gallery", "",
             f"The {results['attack_count']} attack pages and {results['clean_count']} clean pages behind the first "
             "chart of the [README](../README.md): what a reader sees, the attack in the page's HTML, and what each "
             "scraper and headline-antidote hand the model.", "",
             "*Gets through*: the attack reaches the model's text with no warning. *Reached, flagged*: it reaches the "
             "text, and the verdict is `review` or `quarantine`. *Stopped*: it never reaches the text.", "",
             f"![Attacks that get through to the model]({CHART_URL.format('example_pages')})", "",
             f"The same attacks spliced into real news pages: [chart]({CHART_URL.format('real_pages')}). "
             f"Verdicts on clean news: [chart]({CHART_URL.format('false_alarms')}).", "",
             f"Generated by `make_gallery.py` from `results/example_pages.json` ({results['generated']}, "
             f"Chrome {results['chrome']}).", ""]
    for page in pages:
        lines.extend(page_section(page))
    with open(README, "w", encoding="utf-8", newline="") as file:
        file.write("\n".join(lines))
    print("wrote", README, "and", len(pages), "pages and screenshots")


if __name__ == "__main__":
    main()
