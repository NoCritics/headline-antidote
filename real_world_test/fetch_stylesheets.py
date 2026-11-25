"""Fetches the external stylesheets of the saved pages, once each, into a cache.

Run from the project root after collect.py:
    .venv\\Scripts\\python -X utf8 -m real_world_test.fetch_stylesheets [--data DIRECTORY]
Writes <data>/css/*.css and <data>/stylesheets.json.
"""

import hashlib
import json
import os
import time

import requests

from headline_antidote.html_visibility import linked_stylesheet_urls

from .collect import REQUEST_TIMEOUT_SECONDS, USER_AGENT, allowed_by_robots
from .page_data import data_arguments, load_pages, read_page

MAXIMUM_STYLESHEET_BYTES = 3_000_000


def main():
    data_directory = data_arguments().data_directory
    css_directory = os.path.join(data_directory, "css")
    os.makedirs(css_directory, exist_ok=True)
    pages = load_pages(data_directory)
    fetched_by_url = {}
    stylesheets_by_page = {}
    for page_entry in pages:
        html_text = read_page(data_directory, page_entry)
        page_stylesheets = []
        for url in linked_stylesheet_urls(html_text, page_entry["url"]):
            if url not in fetched_by_url:
                status = "skipped"
                file_name = None
                fetch_milliseconds = None
                if not url.startswith("http"):
                    status = "not http"
                elif not allowed_by_robots(url):
                    status = "robots.txt disallows"
                else:
                    started = time.perf_counter()
                    try:
                        response = requests.get(url, headers={"User-Agent": USER_AGENT},
                                                timeout=REQUEST_TIMEOUT_SECONDS)
                        fetch_milliseconds = round((time.perf_counter() - started) * 1000, 1)
                        if response.status_code == 200 and len(response.content) <= MAXIMUM_STYLESHEET_BYTES:
                            file_name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20] + ".css"
                            with open(os.path.join(css_directory, file_name), "wb") as css_file:
                                css_file.write(response.content)
                            status = "ok"
                        else:
                            status = f"HTTP {response.status_code}, {len(response.content)} bytes"
                    except requests.RequestException as error:
                        status = f"error {type(error).__name__}"
                fetched_by_url[url] = {"url": url, "file": file_name, "status": status,
                                       "fetch_milliseconds": fetch_milliseconds}
            page_stylesheets.append(fetched_by_url[url])
        stylesheets_by_page[page_entry["file"]] = page_stylesheets
        statuses = []
        for entry in page_stylesheets:
            statuses.append(entry["status"])
        print(f"{page_entry['file']} {page_entry['source']}: {len(page_stylesheets)} stylesheets {statuses}")
    with open(os.path.join(data_directory, "stylesheets.json"), "w", encoding="utf-8") as file:
        json.dump(stylesheets_by_page, file, indent=1)
    ok_count = 0
    for entry in fetched_by_url.values():
        if entry["status"] == "ok":
            ok_count += 1
    print(f"\n{len(fetched_by_url)} distinct stylesheets, {ok_count} fetched")


if __name__ == "__main__":
    main()
