"""Shared loading for the saved page sets: which data directory, how to decode a page, and
its cached stylesheets."""

import argparse
import codecs
import json
import os
import re

TEST_DIRECTORY = os.path.dirname(os.path.abspath(__file__))
META_CHARSET_PATTERN = re.compile(rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9_\-:.]+)""", re.IGNORECASE)
HEADER_CHARSET_PATTERN = re.compile(r"charset\s*=\s*[\"']?([A-Za-z0-9_\-:.]+)", re.IGNORECASE)


def data_arguments(extra_flags=()):
    """Parses --data (a directory under real_world_test/, default data) and any boolean
    flags named in extra_flags. Returns the parsed arguments with .data_directory set."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    for flag in extra_flags:
        parser.add_argument(flag, action="store_true")
    arguments = parser.parse_args()
    arguments.data_directory = os.path.join(TEST_DIRECTORY, arguments.data)
    return arguments


def report_path(arguments, file_name):
    """The baseline set keeps its reports where the README links them; other sets write
    their reports inside their own data directory."""
    if arguments.data == "data":
        return os.path.join(TEST_DIRECTORY, file_name)
    return os.path.join(arguments.data_directory, file_name)


def _known_codec(name):
    if not name:
        return None
    try:
        return codecs.lookup(name).name
    except LookupError:
        return None


def decode_page(raw_bytes, page_entry):
    """Decodes a saved page as a browser would: the charset the server sent, else the
    page's own <meta charset>, else UTF-8. Returns (text, codec name, replaced characters)."""
    candidates = []
    header_match = HEADER_CHARSET_PATTERN.search(page_entry.get("content_type") or "")
    if header_match:
        candidates.append(header_match.group(1))
    meta_match = META_CHARSET_PATTERN.search(raw_bytes[:4096])
    if meta_match:
        candidates.append(meta_match.group(1).decode("ascii", errors="ignore"))
    candidates.append("utf-8")
    for candidate in candidates:
        codec_name = _known_codec(candidate)
        if codec_name is None:
            continue
        try:
            return raw_bytes.decode(codec_name), codec_name, 0
        except UnicodeDecodeError:
            continue
    text = raw_bytes.decode("utf-8", errors="replace")
    return text, "utf-8 (with replacements)", text.count("�")


def read_page(data_directory, page_entry):
    with open(os.path.join(data_directory, "pages", page_entry["file"]), "rb") as file:
        raw_bytes = file.read()
    text, _, _ = decode_page(raw_bytes, page_entry)
    return text


def load_pages(data_directory):
    with open(os.path.join(data_directory, "pages.json"), encoding="utf-8") as file:
        return json.load(file)


def load_stylesheet_entries(data_directory):
    path = os.path.join(data_directory, "stylesheets.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def load_stylesheets(data_directory, entries):
    texts = []
    for entry in entries:
        if entry["file"]:
            with open(os.path.join(data_directory, "css", entry["file"]), "rb") as file:
                texts.append(file.read().decode("utf-8", errors="replace"))
    return texts
