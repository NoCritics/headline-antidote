"""Times the static reading (extract_article with external stylesheets and the feed title)
in the three situations a pipeline meets, without a profiler:

- cold: nothing cached, as for the first article of a site (or after its CSS changes);
- seen site: another article of the same site was read just before, so its external
  stylesheets are cached but this page's own <style> blocks are not;
- stream: every page once, in a shuffled order that mixes the sites, with the caches the
  library keeps by itself; also split into the first page of each external CSS set (which
  must compile it) and the rest, which show whether other pages pushed a site's CSS out of
  the caches.

    .venv\\Scripts\\python -X utf8 -m real_world_test.benchmark_static [--data DIR] [--sample N] [--out FILE]

This times one version. Do not compare versions with separate runs on a machine whose CPU
clock varies: runs minutes apart differed up to 3x here. Load both versions into one process
(the old one copied under another package name) and time them page by page, back to back.
"""

import argparse
import collections
import json
import os
import random
import time
import warnings

from headline_antidote import HeadlineAntidote, css_cascade
from headline_antidote.watchlists import PAPER_WATCHLIST

from .page_data import TEST_DIRECTORY, load_pages, load_stylesheet_entries, load_stylesheets, read_page

STREAM_SEED = 20261109


def memory_megabytes():
    """(current, peak) memory of this process in MB: the working set on Windows, the peak
    resident size elsewhere (current is then unknown)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
        get_process_memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
        get_process_memory_info(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb)
        return round(counters.WorkingSetSize / 1e6), round(counters.PeakWorkingSetSize / 1e6)
    import resource

    return None, round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e3)


def clear_caches():
    """Empties the module-level caches of compiled stylesheets and rule sets."""
    for value in vars(css_cascade).values():
        if isinstance(value, collections.OrderedDict):
            value.clear()


def percentile(sorted_values, share):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, int(len(sorted_values) * share))
    return sorted_values[index]


def summary(milliseconds):
    ordered = sorted(milliseconds)
    return {
        "pages": len(ordered),
        "p50": round(percentile(ordered, 0.5), 1),
        "p90": round(percentile(ordered, 0.9), 1),
        "p95": round(percentile(ordered, 0.95), 1),
        "max": round(ordered[-1], 1),
        "total_seconds": round(sum(ordered) / 1000, 2),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data_2026-11-09")
    parser.add_argument("--sample", type=int, default=4,
                        help="time the cold and seen-site readings on every Nth page (the stream reads all pages)")
    parser.add_argument("--out", help="also write the per-page times to this JSON file")
    arguments = parser.parse_args()
    warnings.filterwarnings("ignore")
    data_directory = os.path.join(TEST_DIRECTORY, arguments.data)
    stylesheet_entries = load_stylesheet_entries(data_directory)
    guard = HeadlineAntidote(PAPER_WATCHLIST)
    inputs = []
    for page_entry in load_pages(data_directory):
        inputs.append({
            "file": page_entry["file"],
            "site": page_entry["source"],
            "html": read_page(data_directory, page_entry),
            "css": load_stylesheets(data_directory, stylesheet_entries.get(page_entry["file"], [])),
            "feed_title": page_entry["feed_title"],
        })
    pages_by_site = {}
    for page_input in inputs:
        pages_by_site.setdefault(page_input["site"], []).append(page_input)

    def read(page_input):
        started = time.perf_counter()
        guard.extract_article(page_input["html"], feed_title=page_input["feed_title"], stylesheets=page_input["css"])
        return (time.perf_counter() - started) * 1000

    read({"html": "<html><body><h1>warm up</h1><p>text</p></body></html>", "feed_title": None, "css": []})
    sampled = inputs[::arguments.sample]
    times = {"cold": {}, "seen site": {}, "stream": {}, "stream, first of its CSS": {}, "stream, CSS seen before": {}}

    for page_input in sampled:
        clear_caches()
        times["cold"][page_input["file"]] = read(page_input)

    for page_input in sampled:
        other_page = None
        for candidate in pages_by_site[page_input["site"]]:
            if candidate["file"] != page_input["file"] and candidate["css"] == page_input["css"]:
                other_page = candidate
                break
        if other_page is None:
            continue
        clear_caches()
        read(other_page)
        times["seen site"][page_input["file"]] = read(page_input)

    clear_caches()
    stream_order = list(inputs)
    random.Random(STREAM_SEED).shuffle(stream_order)
    # The first page of each external CSS set must compile it; the others show the caches at work.
    seen_stylesheet_sets = set()
    for page_input in stream_order:
        milliseconds = read(page_input)
        times["stream"][page_input["file"]] = milliseconds
        stylesheet_set = tuple(page_input["css"])
        if stylesheet_set in seen_stylesheet_sets:
            times["stream, CSS seen before"][page_input["file"]] = milliseconds
        else:
            times["stream, first of its CSS"][page_input["file"]] = milliseconds
            seen_stylesheet_sets.add(stylesheet_set)

    result = {}
    for situation, page_times in times.items():
        result[situation] = summary(list(page_times.values()))
    # After the stream, the working set is mostly what the caches hold.
    result["memory_mb_after_stream"], result["peak_memory_mb"] = memory_megabytes()
    print(json.dumps(result))
    if arguments.out:
        with open(arguments.out, "w", encoding="utf-8") as file:
            json.dump({"summary": result, "times": times}, file, indent=1)


if __name__ == "__main__":
    main()
