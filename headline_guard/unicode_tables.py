"""Loads the official Unicode data files the guard depends on.

The files are parsed strictly as data (never executed) and their SHA-256
hashes are checked against unicode_data/manifest.json before use.
"""

import bisect
import functools
import hashlib
import json
import os
import unicodedata

DATA_DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unicode_data")


class UnicodeDataError(RuntimeError):
    pass


def _read_verified_lines(file_name, expected_hashes):
    path = os.path.join(DATA_DIRECTORY, file_name)
    with open(path, "rb") as file:
        raw_bytes = file.read()
    actual_hash = hashlib.sha256(raw_bytes).hexdigest()
    if actual_hash != expected_hashes[file_name]:
        raise UnicodeDataError(
            f"{file_name} does not match the SHA-256 in manifest.json "
            f"(got {actual_hash}). Re-download it or update the manifest deliberately."
        )
    return raw_bytes.decode("utf-8-sig").splitlines()


def _data_fields(line):
    """Returns the ';'-separated fields of a data line, or None for comments and blanks."""
    content = line.split("#", 1)[0].strip()
    if not content:
        return None
    fields = []
    for field in content.split(";"):
        fields.append(field.strip())
    return fields


def _code_point_range(field):
    if ".." in field:
        first, last = field.split("..")
        return int(first, 16), int(last, 16)
    return int(field, 16), int(field, 16)


class UnicodeTables:
    def __init__(self):
        with open(os.path.join(DATA_DIRECTORY, "manifest.json"), encoding="utf-8") as file:
            manifest = json.load(file)
        expected_hashes = {}
        for file_name, file_entry in manifest["files"].items():
            expected_hashes[file_name] = file_entry["sha256"]

        self.confusable_targets = {}
        for line in _read_verified_lines("confusables.txt", expected_hashes):
            fields = _data_fields(line)
            if fields is None:
                continue
            target_characters = []
            for hex_value in fields[1].split():
                target_characters.append(chr(int(hex_value, 16)))
            self.confusable_targets[chr(int(fields[0], 16))] = "".join(target_characters)

        script_ranges = []
        for line in _read_verified_lines("Scripts.txt", expected_hashes):
            fields = _data_fields(line)
            if fields is None:
                continue
            first, last = _code_point_range(fields[0])
            script_ranges.append((first, last, fields[1]))
        script_ranges.sort()
        self._script_range_starts = []
        self._script_ranges = script_ranges
        for script_range in script_ranges:
            self._script_range_starts.append(script_range[0])

        self._default_ignorable_ranges = []
        for line in _read_verified_lines("DerivedCoreProperties.txt", expected_hashes):
            fields = _data_fields(line)
            if fields is None or fields[1] != "Default_Ignorable_Code_Point":
                continue
            self._default_ignorable_ranges.append(_code_point_range(fields[0]))

        # Bind per-instance caches; every headline revisits the same few hundred characters.
        self.script_of = functools.lru_cache(maxsize=None)(self._script_of)
        self.is_default_ignorable = functools.lru_cache(maxsize=None)(self._is_default_ignorable)
        self.ascii_lookalike = functools.lru_cache(maxsize=None)(self._ascii_lookalike)

    def _script_of(self, character):
        code_point = ord(character)
        position = bisect.bisect_right(self._script_range_starts, code_point) - 1
        if position >= 0:
            first, last, script = self._script_ranges[position]
            if first <= code_point <= last:
                return script
        return "Unknown"

    def _is_default_ignorable(self, character):
        code_point = ord(character)
        for first, last in self._default_ignorable_ranges:
            if first <= code_point <= last:
                return True
        return False

    def _ascii_lookalike(self, character):
        """The ASCII letter or digit this character is confusable with, or None."""
        target = self.confusable_targets.get(character)
        if target is not None and len(target) == 1 and target.isascii() and target.isalnum():
            # The table files every I-shaped letter under "l"; a capital (Cyrillic І, Greek Ι) reads as I.
            if target == "l" and character.isupper():
                return "I"
            return target
        return None

    def skeleton(self, text):
        """UTS #39 skeleton. Only meaningful for comparing two strings, never as clean text
        (for example, the skeleton of "I" is "l" and of "m" is "rn")."""
        mapped_parts = []
        for character in unicodedata.normalize("NFD", text):
            mapped_parts.append(self.confusable_targets.get(character, character))
        return unicodedata.normalize("NFD", "".join(mapped_parts))


@functools.lru_cache(maxsize=1)
def get_unicode_tables():
    return UnicodeTables()
