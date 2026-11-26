"""Headline antidote: decides whether a headline's text is what a human reader sees.

It does not invent a new Unicode algorithm. It applies the Unicode standard's own
building blocks (NFKC, UTS #39 confusables and skeletons, script data) under a
policy made for trading pipelines:

* it knows the watchlist, so a look-alike of a watched name is caught in any script;
* it respects real language, so Russian, Greek, Persian, Hindi or Japanese text is
  left alone;
* it never silently repairs: every change to the text comes with a flag, and the
  trading layer decides whether to drop, down-weight or alert.

All flag offsets point into the text that was passed to analyze().
"""

import copy
import difflib
import unicodedata
from dataclasses import dataclass

from .unicode_tables import get_unicode_tables

HIGH = "high"
MEDIUM = "medium"
LOW = "low"
SEVERITY_RANK = {LOW: 1, MEDIUM: 2, HIGH: 3}

TAG_FIRST = 0xE0000
TAG_LAST = 0xE007F
CANCEL_TAG = 0xE007F
WAVING_BLACK_FLAG = 0x1F3F4

ZERO_WIDTH_NON_JOINER = "‌"
ZERO_WIDTH_JOINER = "‍"
BYTE_ORDER_MARK = "﻿"
SOFT_HYPHEN = "­"
COMBINING_KEYCAP = "⃣"
DIRECTION_MARKS_AND_ISOLATES = {
    "‎", "‏", "؜",                      # LRM, RLM, ALM
    "‪", "‫", "‬",                      # embeddings and pop
    "⁦", "⁧", "⁨", "⁩",            # isolates
}
BIDI_OVERRIDES = {"‭", "‮"}

# Format characters (category Cf) that are drawn on screen, so they are not hidden.
VISIBLE_FORMAT_CHARACTERS = {
    "؀", "؁", "؂", "؃", "؄", "؅", "۝", "܏",
    "࢐", "࢑", "࣢", "\U000110bd", "\U000110cd",
}

# Scripts where ZWJ/ZWNJ change how letters join or form conjuncts.
JOINER_SCRIPTS = {
    "Arabic", "Syriac", "Nko", "Mongolian", "Thaana", "Mandaic",
    "Devanagari", "Bengali", "Gurmukhi", "Gujarati", "Oriya", "Tamil", "Telugu",
    "Kannada", "Malayalam", "Sinhala", "Khmer", "Myanmar", "Tibetan",
}
RIGHT_TO_LEFT_SCRIPTS = {
    "Arabic", "Hebrew", "Syriac", "Thaana", "Nko", "Samaritan", "Mandaic", "Adlam",
    "Hanifi_Rohingya",
}
CJK_SCRIPTS = {"Han", "Hiragana", "Katakana", "Hangul", "Bopomofo"}
SCRIPTS_THAT_DO_NOT_COUNT = {"Common", "Inherited", "Unknown"}

# UTS #39 "highly restrictive" profile: the only legitimate multi-script words.
ALLOWED_SCRIPT_COMBINATIONS = [
    {"Latin", "Han", "Hiragana", "Katakana"},
    {"Latin", "Han", "Bopomofo"},
    {"Latin", "Han", "Hangul"},
]

# Characters allowed between the words of a multi-word watched name ("Coca-Cola", "AT&T").
NAME_CONNECTORS = {"-", "&", ".", "'", "’", "‐", "‑"}

# Combining-mark stacks deeper than this on Latin, Greek or Cyrillic letters are not language.
MAXIMUM_NATURAL_COMBINING_MARKS = 2
SCRIPTS_WITH_SHALLOW_MARK_STACKS = {"Latin", "Greek", "Cyrillic"}

# Share of a script's letters that must look Latin before the script is treated as disguised Latin.
LATIN_DISGUISE_SHARE = 0.9

# Emoji subdivision flags (England, Scotland, Wales): the only legitimate tag-character sequences.
SUBDIVISION_FLAG_CODES = {"gbeng", "gbsct", "gbwls"}

# Flags whose severity is raised to HIGH when they fall inside a watched name.
FLAGS_RAISED_INSIDE_WATCHED_NAMES = {
    "invisible_character", "compatibility_lookalike", "excessive_combining_marks", "bidi_control",
}


@dataclass
class Flag:
    kind: str
    severity: str
    start: int | None
    end: int | None
    original: str
    # The facts of this finding that no other field holds (docs/report_format.md, "Evidence keys").
    evidence: dict
    # For article extraction: which output the flag belongs to ("headline", "body", "metadata", "page").
    field: str | None = None

    def to_dict(self):
        """The flag as it appears in a report (report_schema.json), without offsets."""
        return {"category": self.kind, "severity": self.severity, "field": self.field,
                "flagged_text": self.original, "evidence": copy.deepcopy(self.evidence)}


def _html_comment_flag(fragment):
    return Flag("html_comment_text", MEDIUM, None, None, fragment.text, {})


def hiding_evidence(fragment):
    """The cause of a hidden fragment, and the CSS rule when one hides it."""
    if fragment.css is None:
        return {"cause": fragment.cause}
    return {"cause": fragment.cause, "css": fragment.css}


def _hidden_fragment_flag(fragment, severity):
    return Flag("hidden_html_text", severity, None, None, fragment.text, hiding_evidence(fragment))


# The version of report_schema.json that to_dict() output follows.
REPORT_SCHEMA_VERSION = "1.0"


def verdict_for_flags(flags):
    """'quarantine' (any high flag), 'review' (any medium flag) or 'pass'."""
    highest_rank = 0
    for flag in flags:
        highest_rank = max(highest_rank, SEVERITY_RANK[flag.severity])
    if highest_rank == SEVERITY_RANK[HIGH]:
        return "quarantine"
    if highest_rank == SEVERITY_RANK[MEDIUM]:
        return "review"
    return "pass"


@dataclass
class EntityMention:
    ticker: str
    canonical_spelling: str
    start: int
    end: int
    via_lookalike: bool


@dataclass
class GuardResult:
    original_text: str
    clean_text: str
    flags: list
    entities: list

    @property
    def verdict(self):
        """'quarantine' (any high flag), 'review' (any medium flag) or 'pass'."""
        return verdict_for_flags(self.flags)

    @property
    def tickers(self):
        found_tickers = []
        for entity in self.entities:
            if entity.ticker not in found_tickers:
                found_tickers.append(entity.ticker)
        return found_tickers

    def to_dict(self):
        """The text report: plain JSON types, matching report_schema.json (docs/report_format.md)."""
        return {
            "schema_version": REPORT_SCHEMA_VERSION, "report_type": "text", "verdict": self.verdict,
            "text_as_written": self.original_text, "text_cleaned": self.clean_text,
            "tickers": self.tickers,
            "flags": [{**flag.to_dict(), "start": flag.start, "end": flag.end} for flag in self.flags],
        }


def _is_word_character(character):
    return unicodedata.category(character)[0] in "LMN"


def _is_emoji_like(character):
    if not character:
        return False
    code_point = ord(character)
    if 0x1F000 <= code_point <= 0x1FAFF or 0x2600 <= code_point <= 0x27BF:
        return True
    if 0x2300 <= code_point <= 0x23FF or 0x2B00 <= code_point <= 0x2BFF:
        return True
    if character == "️" or character == COMBINING_KEYCAP:
        return True
    return unicodedata.category(character) == "So"


def _is_variation_selector(character):
    code_point = ord(character)
    if 0xFE00 <= code_point <= 0xFE0F or 0xE0100 <= code_point <= 0xE01EF:
        return True
    return 0x180B <= code_point <= 0x180F


def _swapped_characters(window, spelling):
    """The characters of window that stand in for the spelling's letters, each once: the other
    script's letters, or the ASCII ones ("I" for "l"; "rn" for "m", which differs in length)."""
    swapped = []
    matcher = difflib.SequenceMatcher(a=spelling, b=window, autojunk=False)
    for operation, _, _, window_start, window_end in matcher.get_opcodes():
        if operation == "equal":
            continue
        for character in window[window_start:window_end]:
            if character not in swapped:
                swapped.append(character)
    return swapped


def _character_evidence(characters):
    return [{"code_point": f"U+{ord(character):04X}", "name": unicodedata.name(character, "UNNAMED")}
            for character in characters]


class HeadlineAntidote:
    """Build once per watchlist, then call analyze() or analyze_html() per headline.

    watchlist maps each ticker to the names it is reported under, for example
    {"TSLA": ["Tesla"], "GOOGL": ["Alphabet", "Google"]}. Tickers match
    case-sensitively; names match as written, in UPPER case or in Title case.
    """

    def __init__(self, watchlist):
        self._tables = get_unicode_tables()
        self._exact_spellings = {}
        self._lowercase_spellings = set()
        self._spellings_by_skeleton = {}
        self._longest_name_in_words = 1
        for ticker, names in watchlist.items():
            self._register_spelling(ticker, ticker, include_case_variants=False)
            for name in names:
                self._register_spelling(ticker, name, include_case_variants=True)

    def _register_spelling(self, ticker, name, include_case_variants):
        name_words = self._split_into_words(unicodedata.normalize("NFKC", name))
        self._longest_name_in_words = max(self._longest_name_in_words, len(name_words))
        name_key = " ".join(name_words)
        exact_variants = [name_key]
        if include_case_variants:
            exact_variants.append(name_key.upper())
            exact_variants.append(name_key.title())
        for variant in exact_variants:
            self._exact_spellings.setdefault(variant, (ticker, variant))
            self._spellings_by_skeleton.setdefault(self._tables.skeleton(variant), (ticker, variant))
        if include_case_variants:
            self._lowercase_spellings.add(name_key.lower())
            self._spellings_by_skeleton.setdefault(
                self._tables.skeleton(name_key.lower()), (ticker, name_key.lower())
            )

    @staticmethod
    def _split_into_words(text):
        words = []
        current_word = []
        for character in text:
            if _is_word_character(character):
                current_word.append(character)
            elif current_word:
                words.append("".join(current_word))
                current_word = []
        if current_word:
            words.append("".join(current_word))
        return words

    def analyze(self, text):
        return _HeadlineAnalysis(self, text).run()

    def extract_article(self, html, feed_title=None, stylesheets=None, feed_body=None):
        """The headline and article text a reader sees, with flags. See article.py. Needs trafilatura.

        stylesheets: CSS text of the page's external stylesheets, if fetched (see
        html_visibility.linked_stylesheet_urls); used when tinycss2 and cssselect2 are installed.
        feed_body: the article's full text from the feed, if it has one (RSS content:encoded).
        """
        from .article import extract_article

        return extract_article(self, html, feed_title, stylesheets, feed_body)

    def prepare_stylesheets(self, stylesheets):
        """Compiles a site's external stylesheets before its articles arrive, for example when
        the scraper fetches them. A big site's CSS takes 0.5 to 3 s to compile; it is cached
        either way, but without this call the site's first article waits for it. Pass the same
        list, in the same order, as to extract_article(). Call it from the thread that calls
        extract_article(): the caches are not shared safely between threads.
        """
        try:
            from .css_cascade import external_rule_set
        except ImportError:
            return  # without tinycss2 and cssselect2, external stylesheets are not read at all
        from .html_tree import PageTooComplex
        from .html_visibility import check_css_numbers

        try:
            check_css_numbers(stylesheets)
        except PageTooComplex:
            return  # nothing to compile: extract_article() flags these pages for the browser check
        external_rule_set(stylesheets)

    def verify_article_in_browser(self, article, html, url, verifier):
        """Renders the page in Chrome and merges what readers see into an extract_article() result.

        verifier: a started browser_visibility.BrowserVerifier, kept open across pages. Use it
        for results with needs_browser_check. See browser_check.py.
        """
        from .browser_check import verify_article_in_browser

        return verify_article_in_browser(self, article, html, url, verifier)

    def analyze_html(self, html, headline_xpath=None, scraped_text=None, rendered_by_browser=False,
                     stylesheets=None):
        """Analyses only the text a browser would show, and flags any hidden text.

        headline_xpath: read only this element (for example "//h1"), as a scraper would.
        scraped_text: what your scraper extracted from the same element. Any difference
            from the visible text is flagged, because whatever the scraper adds or drops
            is what the model will actually read. Pass the scraper's raw output.
        rendered_by_browser: set when scraped_text comes from
            browser_visibility.rendered_visible_text() and html is the rendered page
            (page.content()). The browser then decides what is visible: it knows external
            stylesheets, complex selectors and JavaScript, which this parser does not.

        Offsets in the returned flags point into result.original_text. Hidden-text and
        scraper flags have no offsets.
        """
        from .html_tree import PageTooComplex
        from .html_visibility import extract_visible_text

        try:
            visible_text, hidden_fragments = extract_visible_text(html, headline_xpath, stylesheets)
        except PageTooComplex as error:
            result = self.analyze("")
            result.flags.append(Flag("page_too_complex_to_read", MEDIUM, None, None, "", {"message": str(error)}))
            return result
        if visible_text is None:
            result = self.analyze("")
            result.flags.append(Flag("headline_not_found", MEDIUM, None, None, "", {}))
            return result
        if rendered_by_browser:
            if scraped_text is None:
                raise ValueError("rendered_by_browser needs scraped_text from rendered_visible_text()")
            return self._analyze_browser_rendered(visible_text, hidden_fragments, scraped_text)
        result = self.analyze(visible_text)
        if scraped_text is not None:
            scraper_flag = _compare_with_scraped_text(visible_text, scraped_text, hidden_fragments)
            if scraper_flag is not None:
                result.flags.append(scraper_flag)
        for fragment in hidden_fragments:
            if fragment.kind == "html_comment":
                result.flags.append(_html_comment_flag(fragment))
            elif fragment.kind == "reordered_text":
                result.flags.append(reordered_text_flag(fragment))
            else:
                result.flags.append(_hidden_fragment_flag(fragment, fragment.severity))
        return result

    def _analyze_browser_rendered(self, parser_visible_text, hidden_fragments, browser_visible_text):
        """Browser mode: the browser's visible text is what a reader sees, so that is analysed."""
        result = self.analyze(browser_visible_text)
        browser_compact = _compact(browser_visible_text)
        for fragment in hidden_fragments:
            if fragment.kind == "html_comment":
                result.flags.append(_html_comment_flag(fragment))
                continue
            if fragment.kind == "reordered_text":
                result.flags.append(reordered_text_flag(fragment))
                continue
            if fragment.severity == MEDIUM and _compact(fragment.text) in browser_compact:
                # The parser only guessed the background; the browser knows it and shows this text.
                continue
            result.flags.append(_hidden_fragment_flag(fragment, HIGH))
        added_words, dropped_words = _word_differences(parser_visible_text, browser_visible_text)
        if dropped_words:
            result.flags.append(Flag(
                "hidden_html_text", HIGH, None, None, " ".join(dropped_words), {"cause": "script_or_overlay"},
            ))
        unexplained_words = list(added_words)
        for fragment in hidden_fragments:
            for word in unicodedata.normalize("NFC", fragment.text).split():
                if word in unexplained_words:
                    unexplained_words.remove(word)
        if unexplained_words:
            result.flags.append(Flag("script_generated_text", MEDIUM, None, None, " ".join(unexplained_words), {}))
        return result


def reordered_text_flag(fragment, severity=None, field=None):
    """Readers see these letters in reverse order, so the page's text is not what they read."""
    return Flag("reordered_text", severity or fragment.severity, None, None, fragment.text,
                {"css": fragment.css}, field)


def _severity_for_added_words(added_words, hidden_fragments):
    """Added words explained by hidden fragments inherit their severity; unexplained ones are HIGH.

    This keeps a deliberate MEDIUM (white text whose page background is only guessed)
    from being escalated just because the scraper, correctly, read that text.
    """
    explaining_severities = []
    remaining_words = list(added_words)
    for fragment in hidden_fragments:
        if fragment.kind != "hidden_element":
            continue
        fragment_words = unicodedata.normalize("NFC", fragment.text).split()
        fragment_explains_something = False
        for word in fragment_words:
            if word in remaining_words:
                remaining_words.remove(word)
                fragment_explains_something = True
        if fragment_explains_something:
            explaining_severities.append(fragment.severity)
    if remaining_words or not explaining_severities:
        return HIGH
    highest_severity = LOW
    for severity in explaining_severities:
        if SEVERITY_RANK[severity] > SEVERITY_RANK[highest_severity]:
            highest_severity = severity
    return highest_severity


def _compare_with_scraped_text(visible_text, scraped_text, hidden_fragments):
    """Flags any difference between what a reader sees and what the scraper extracted.

    Spacing is ignored, since scrapers join inline elements differently.
    """
    if _compact(visible_text) == _compact(scraped_text):
        return None
    added_words, dropped_words = _word_differences(visible_text, scraped_text)
    if not added_words and not dropped_words:
        # Same words, different characters inside them, for example a stripped zero-width space.
        return Flag("scraper_text_differs", MEDIUM, None, None, scraped_text, {})
    evidence = {}
    if added_words:
        evidence["added_text"] = " ".join(added_words)
    if dropped_words:
        evidence["dropped_text"] = " ".join(dropped_words)
    severity = MEDIUM
    if added_words:
        severity = _severity_for_added_words(added_words, hidden_fragments)
    return Flag("scraper_text_differs", severity, None, None, scraped_text, evidence)


def _compact(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def _word_differences(reference_text, other_text):
    """Words other_text adds to reference_text, and words it drops from it."""
    reference_words = unicodedata.normalize("NFC", reference_text).split()
    other_words = unicodedata.normalize("NFC", other_text).split()
    added_words = []
    dropped_words = []
    matcher = difflib.SequenceMatcher(a=reference_words, b=other_words, autojunk=False)
    for operation, reference_start, reference_end, other_start, other_end in matcher.get_opcodes():
        if operation in ("replace", "insert"):
            added_words.extend(other_words[other_start:other_end])
        if operation in ("replace", "delete"):
            dropped_words.extend(reference_words[reference_start:reference_end])
    return added_words, dropped_words


class _HeadlineAnalysis:
    """State for analysing one headline."""

    def __init__(self, guard, text):
        self.guard = guard
        self.tables = guard._tables
        self.text = text
        self.flags = []
        self.entities = []
        # Characters kept after stripping and NFKC, each with its index in self.text.
        self.kept_characters = []
        self.kept_origins = []
        # Clean-text repairs: kept position -> replacement, and span start -> (span end, replacement).
        self.character_replacements = {}
        self.span_replacements = {}
        self.words_already_checked = set()

        letter_counts_by_script = {}
        lookalike_letter_counts_by_script = {}
        for character in text:
            if unicodedata.category(character).startswith("L"):
                script = self.tables.script_of(character)
                if script not in SCRIPTS_THAT_DO_NOT_COUNT:
                    letter_counts_by_script[script] = letter_counts_by_script.get(script, 0) + 1
                    if script != "Latin" and self.tables.ascii_lookalike(character) is not None:
                        lookalike_letter_counts_by_script[script] = (
                            lookalike_letter_counts_by_script.get(script, 0) + 1
                        )
        # Real Russian, Greek and so on always use letters with no Latin look-alike (б, д, и, л, Π...).
        # A script whose letters nearly all look Latin is a disguise, so it counts as Latin.
        # Otherwise an attacker could write a whole headline in look-alikes to switch off the checks.
        for script, lookalike_count in lookalike_letter_counts_by_script.items():
            if lookalike_count >= LATIN_DISGUISE_SHARE * letter_counts_by_script[script]:
                letter_counts_by_script["Latin"] = (
                    letter_counts_by_script.get("Latin", 0) + letter_counts_by_script.pop(script)
                )
        self.dominant_script = "Common"
        highest_count = 0
        for script, count in letter_counts_by_script.items():
            if count > highest_count:
                self.dominant_script = script
                highest_count = count
        self.has_cjk = False
        self.has_right_to_left = False
        for script in letter_counts_by_script:
            if script in CJK_SCRIPTS:
                self.has_cjk = True
            if script in RIGHT_TO_LEFT_SCRIPTS:
                self.has_right_to_left = True

    def run(self):
        self._scan_characters()
        self._strip_excessive_combining_marks()
        self.words = self._segment_words()
        self._match_watchlist()
        self._check_word_scripts()
        self._raise_severity_inside_entities()
        return GuardResult(self.text, self._build_clean_text(), self.flags, self.entities)

    # ---- flags -------------------------------------------------------------

    def _add_flag(self, kind, severity, start, end, evidence):
        """Adds a flag, merging it into the previous one when they are adjacent and alike."""
        if self.flags:
            previous = self.flags[-1]
            if (previous.kind == kind and previous.severity == severity
                    and previous.end == start and kind != "watchlist_homoglyph"):
                previous.end = end
                previous.original = self.text[previous.start:end]
                for key, value in evidence.items():
                    previous.evidence[key] += value  # characters extend; looks_like and decoded_text continue
                return
        self.flags.append(Flag(kind, severity, start, end, self.text[start:end], evidence))

    def _keep(self, character, origin):
        self.kept_characters.append(character)
        self.kept_origins.append(origin)

    def _original_span(self, kept_start, kept_end):
        return self.kept_origins[kept_start], self.kept_origins[kept_end - 1] + 1

    # ---- pass 1: invisible characters and compatibility forms ---------------

    def _scan_characters(self):
        text = self.text
        index = 0
        while index < len(text):
            character = text[index]
            code_point = ord(character)

            if TAG_FIRST <= code_point <= TAG_LAST:
                run_end = index
                while run_end < len(text) and TAG_FIRST <= ord(text[run_end]) <= TAG_LAST:
                    run_end += 1
                if self._is_emoji_flag_tag_sequence(index, run_end):
                    for tag_index in range(index, run_end):
                        self._keep(text[tag_index], tag_index)
                else:
                    decoded_characters = []
                    for tag_character in text[index:run_end]:
                        tag_code_point = ord(tag_character)
                        if 0xE0020 <= tag_code_point <= 0xE007E:
                            decoded_characters.append(chr(tag_code_point - TAG_FIRST))
                    self._add_flag("hidden_tag_characters", HIGH, index, run_end,
                                   {"decoded_text": "".join(decoded_characters)})
                index = run_end
                continue

            if self._is_invisible(character):
                judgement = self._judge_invisible(index)
                if judgement == "keep":
                    self._keep(character, index)
                elif judgement != "drop":
                    kind, severity = judgement
                    self._add_flag(kind, severity, index, index + 1, {"characters": _character_evidence(character)})
                index += 1
                continue

            normalized = unicodedata.normalize("NFKC", character)
            if normalized != character:
                severity = self._compatibility_severity(character, normalized)
                if severity is not None:
                    self._add_flag("compatibility_lookalike", severity, index, index + 1,
                                   {"characters": _character_evidence(character), "looks_like": normalized})
                elif not 0xFF00 <= code_point <= 0xFFEF:
                    # Legitimate compatibility characters ("CO₂", "1º", "™") stay as written:
                    # the text is only changed where a flag says why. Full-width and
                    # half-width forms are the one exception, being the same text at another width.
                    normalized = character
            for normalized_character in normalized:
                self._keep(normalized_character, index)
            index += 1

    def _is_emoji_flag_tag_sequence(self, run_start, run_end):
        """Subdivision flags such as Scotland are a black flag, a known region code in tags, and CANCEL TAG."""
        if run_start == 0 or ord(self.text[run_start - 1]) != WAVING_BLACK_FLAG:
            return False
        if ord(self.text[run_end - 1]) != CANCEL_TAG:
            return False
        region_code_characters = []
        for tag_character in self.text[run_start:run_end - 1]:
            region_code_characters.append(chr(ord(tag_character) - TAG_FIRST))
        return "".join(region_code_characters) in SUBDIVISION_FLAG_CODES

    def _is_invisible(self, character):
        if character in VISIBLE_FORMAT_CHARACTERS:
            return False
        if unicodedata.category(character) == "Cf":
            return True
        return self.tables.is_default_ignorable(character)

    def _judge_invisible(self, index):
        """Returns 'keep', 'drop' (silently) or (flag kind, severity) for an invisible character."""
        text = self.text
        character = text[index]
        previous_character = text[index - 1] if index > 0 else ""
        next_character = text[index + 1] if index + 1 < len(text) else ""

        if character == BYTE_ORDER_MARK and index == 0:
            return "drop"
        if character == ZERO_WIDTH_JOINER or character == ZERO_WIDTH_NON_JOINER:
            if previous_character and self.tables.script_of(previous_character) in JOINER_SCRIPTS:
                return "keep"
            if next_character and self.tables.script_of(next_character) in JOINER_SCRIPTS:
                return "keep"
            if _is_emoji_like(previous_character) and _is_emoji_like(next_character):
                return "keep"
            return ("invisible_character", self._invisible_severity(index))
        if _is_variation_selector(character):
            if _is_emoji_like(previous_character) or next_character == COMBINING_KEYCAP:
                return "keep"
            if previous_character and self.tables.script_of(previous_character) in {"Han", "Mongolian"}:
                return "keep"
            return ("invisible_character", self._invisible_severity(index))
        if character in DIRECTION_MARKS_AND_ISOLATES:
            if self.has_right_to_left:
                return "keep"
            return ("bidi_control", MEDIUM)
        if character in BIDI_OVERRIDES:
            return ("bidi_control", MEDIUM)
        if character == SOFT_HYPHEN:
            return ("invisible_character", LOW)
        return ("invisible_character", self._invisible_severity(index))

    def _invisible_severity(self, index):
        """MEDIUM inside a word, where it can split a name or a sentiment word; LOW between words.

        (Inside a watched name it is raised to HIGH later.)
        """
        text = self.text
        previous_index = index - 1
        while previous_index >= 0 and self._is_invisible(text[previous_index]):
            previous_index -= 1
        next_index = index + 1
        while next_index < len(text) and self._is_invisible(text[next_index]):
            next_index += 1
        if previous_index < 0 or next_index >= len(text):
            return LOW
        if _is_word_character(text[previous_index]) and _is_word_character(text[next_index]):
            return MEDIUM
        return LOW

    def _compatibility_severity(self, character, normalized):
        """Flags only compatibility forms that disguise ASCII letters or digits (math bold, full-width)."""
        disguises_ascii = False
        for normalized_character in normalized:
            if normalized_character.isascii() and normalized_character.isalnum():
                disguises_ascii = True
                break
        if not disguises_ascii:
            return None
        category = unicodedata.category(character)
        if category == "Lm" or not (category.startswith("L") or category == "Nd"):
            return None
        if character in ("ª", "º"):  # Spanish and Portuguese ordinal indicators
            return None
        code_point = ord(character)
        if 0xFF01 <= code_point <= 0xFF5E and self.has_cjk:
            return None
        if 0xFB00 <= code_point <= 0xFB06:  # typographic ligatures such as "fi"
            return LOW
        return MEDIUM

    # ---- pass 2: stacked combining marks -----------------------------------

    def _strip_excessive_combining_marks(self):
        filtered_characters = []
        filtered_origins = []
        base_script = None
        mark_run = []

        def finish_mark_run():
            if not mark_run:
                return
            if len(mark_run) > MAXIMUM_NATURAL_COMBINING_MARKS and base_script in SCRIPTS_WITH_SHALLOW_MARK_STACKS:
                marks = []
                for mark_character, _ in mark_run:
                    marks.append(mark_character)
                self._add_flag("excessive_combining_marks", MEDIUM, mark_run[0][1], mark_run[-1][1] + 1,
                               {"characters": _character_evidence(marks)})
            else:
                for mark_character, mark_origin in mark_run:
                    filtered_characters.append(mark_character)
                    filtered_origins.append(mark_origin)
            mark_run.clear()

        for position in range(len(self.kept_characters)):
            character = self.kept_characters[position]
            origin = self.kept_origins[position]
            if unicodedata.category(character) == "Mn":
                mark_run.append((character, origin))
                continue
            finish_mark_run()
            base_script = self.tables.script_of(character)
            filtered_characters.append(character)
            filtered_origins.append(origin)
        finish_mark_run()
        self.kept_characters = filtered_characters
        self.kept_origins = filtered_origins

    # ---- pass 3: words and the watchlist -----------------------------------

    def _segment_words(self):
        words = []
        word_start = None
        for position in range(len(self.kept_characters)):
            if _is_word_character(self.kept_characters[position]):
                if word_start is None:
                    word_start = position
            elif word_start is not None:
                words.append((word_start, position))
                word_start = None
        if word_start is not None:
            words.append((word_start, len(self.kept_characters)))
        return words

    def _word_text(self, word_number):
        word_start, word_end = self.words[word_number]
        return unicodedata.normalize("NFC", "".join(self.kept_characters[word_start:word_end]))

    def _words_are_joined(self, first_word_number, last_word_number):
        for word_number in range(first_word_number, last_word_number):
            gap_start = self.words[word_number][1]
            gap_end = self.words[word_number + 1][0]
            for position in range(gap_start, gap_end):
                gap_character = self.kept_characters[position]
                if not gap_character.isspace() and gap_character not in NAME_CONNECTORS:
                    return False
        return True

    def _match_watchlist(self):
        word_number = 0
        while word_number < len(self.words):
            longest_window = min(self.guard._longest_name_in_words, len(self.words) - word_number)
            window_length = longest_window
            matched = False
            while window_length >= 1:
                last_word_number = word_number + window_length - 1
                if self._words_are_joined(word_number, last_word_number):
                    window_words = []
                    for window_word_number in range(word_number, last_word_number + 1):
                        window_words.append(self._word_text(window_word_number))
                    if self._match_window(word_number, last_word_number, " ".join(window_words)):
                        matched = True
                        break
                window_length -= 1
            if matched:
                word_number += window_length
            else:
                word_number += 1

    def _match_window(self, first_word_number, last_word_number, window_key):
        kept_start = self.words[first_word_number][0]
        kept_end = self.words[last_word_number][1]
        original_start, original_end = self._original_span(kept_start, kept_end)

        exact_spelling = self.guard._exact_spellings.get(window_key)
        if exact_spelling is not None:
            self.entities.append(EntityMention(exact_spelling[0], exact_spelling[1], original_start, original_end, False))
            self._mark_words_checked(first_word_number, last_word_number)
            return True
        if window_key in self.guard._lowercase_spellings:
            self._mark_words_checked(first_word_number, last_word_number)
            return True

        lookalike_spelling = self.guard._spellings_by_skeleton.get(self.tables.skeleton(window_key))
        if lookalike_spelling is None:
            return self._match_accented_window(first_word_number, last_word_number, window_key)
        ticker, spelling = lookalike_spelling
        self._mark_words_checked(first_word_number, last_word_number)

        window_scripts = set()
        for character in window_key:
            if unicodedata.category(character).startswith("L"):
                script = self.tables.script_of(character)
                if script not in SCRIPTS_THAT_DO_NOT_COUNT:
                    window_scripts.add(script)
        if len(window_scripts) == 1 and "Latin" not in window_scripts and self.dominant_script in window_scripts:
            # For example "МЕТА" (Ukrainian and Russian for "goal") inside a Cyrillic headline.
            self._add_flag("possible_watchlist_lookalike", LOW, original_start, original_end,
                           {"looks_like": spelling, "tickers": [ticker]})
            return True

        self._add_flag("watchlist_homoglyph", HIGH, original_start, original_end, {
            "looks_like": spelling, "tickers": [ticker],
            "characters": _character_evidence(_swapped_characters(window_key, spelling)),
        })
        self.entities.append(EntityMention(ticker, spelling, original_start, original_end, True))
        self.span_replacements[kept_start] = (kept_end, spelling)
        return True

    def _match_accented_window(self, first_word_number, last_word_number, window_key):
        """A watched name with accents added ("Tésla") would otherwise be dropped without a trace."""
        base_characters = []
        added_marks = []
        for character in unicodedata.normalize("NFD", window_key):
            if unicodedata.category(character) == "Mn":
                added_marks.append(character)
            else:
                base_characters.append(character)
        if not added_marks:
            return False
        lookalike_spelling = self.guard._spellings_by_skeleton.get(
            self.tables.skeleton(unicodedata.normalize("NFC", "".join(base_characters)))
        )
        if lookalike_spelling is None:
            return False
        ticker, spelling = lookalike_spelling
        # An all-lowercase word is an ordinary word ("metà" is Italian for "half"), just as plain
        # "meta" is never taken for Meta: only a capitalised one names the company.
        if window_key == window_key.lower():
            return False
        kept_start = self.words[first_word_number][0]
        kept_end = self.words[last_word_number][1]
        original_start, original_end = self._original_span(kept_start, kept_end)
        self._mark_words_checked(first_word_number, last_word_number)
        self._add_flag("accented_watchlist_name", MEDIUM, original_start, original_end, {
            "looks_like": spelling, "tickers": [ticker], "characters": _character_evidence(added_marks),
        })
        self.entities.append(EntityMention(ticker, spelling, original_start, original_end, True))
        self.span_replacements[kept_start] = (kept_end, spelling)
        return True

    def _mark_words_checked(self, first_word_number, last_word_number):
        for word_number in range(first_word_number, last_word_number + 1):
            self.words_already_checked.add(word_number)

    # ---- pass 4: scripts inside each remaining word ------------------------

    def _check_word_scripts(self):
        for word_number in range(len(self.words)):
            if word_number in self.words_already_checked:
                continue
            word_start, word_end = self.words[word_number]
            letter_counts_by_script = {}
            letter_count = 0
            for position in range(word_start, word_end):
                character = self.kept_characters[position]
                if not unicodedata.category(character).startswith("L"):
                    continue
                letter_count += 1
                script = self.tables.script_of(character)
                if script not in SCRIPTS_THAT_DO_NOT_COUNT:
                    letter_counts_by_script[script] = letter_counts_by_script.get(script, 0) + 1
            word_scripts = set(letter_counts_by_script)
            if len(word_scripts) > 1:
                if not self._is_allowed_script_combination(word_scripts):
                    self._flag_mixed_script_word(word_start, word_end, letter_counts_by_script)
            elif len(word_scripts) == 1 and letter_count >= 2:
                only_script = next(iter(word_scripts))
                if only_script != "Latin" and self.dominant_script == "Latin":
                    self._check_whole_script_lookalike(word_start, word_end)

    @staticmethod
    def _is_allowed_script_combination(word_scripts):
        for allowed_combination in ALLOWED_SCRIPT_COMBINATIONS:
            if word_scripts <= allowed_combination:
                return True
        return False

    def _flag_mixed_script_word(self, word_start, word_end, letter_counts_by_script):
        majority_script = None
        majority_count = 0
        for script, count in letter_counts_by_script.items():
            if count > majority_count or (count == majority_count and script == "Latin"):
                majority_script = script
                majority_count = count
        minority_characters = []
        confusable_minority = False
        for position in range(word_start, word_end):
            character = self.kept_characters[position]
            if not unicodedata.category(character).startswith("L"):
                continue
            script = self.tables.script_of(character)
            if script == majority_script or script in SCRIPTS_THAT_DO_NOT_COUNT:
                continue
            minority_characters.append(character)
            lookalike = self.tables.ascii_lookalike(character)
            if character.isascii() or lookalike is not None:
                confusable_minority = True
            if majority_script == "Latin" and lookalike is not None:
                self.character_replacements[position] = lookalike
        original_start, original_end = self._original_span(word_start, word_end)
        self._add_flag("mixed_script_word", HIGH if confusable_minority else MEDIUM, original_start, original_end,
                       {"characters": _character_evidence(minority_characters)})

    def _check_whole_script_lookalike(self, word_start, word_end):
        """A word written entirely in, say, Cyrillic letters that all look Latin, inside a Latin headline."""
        replacements = {}
        for position in range(word_start, word_end):
            character = self.kept_characters[position]
            if not unicodedata.category(character).startswith("L"):
                continue
            lookalike = self.tables.ascii_lookalike(character)
            if lookalike is None:
                return
            replacements[position] = lookalike
        self.character_replacements.update(replacements)
        original_start, original_end = self._original_span(word_start, word_end)
        lookalike_word = []
        for position in range(word_start, word_end):
            lookalike_word.append(replacements.get(position, self.kept_characters[position]))
        self._add_flag("whole_script_lookalike", MEDIUM, original_start, original_end,
                       {"looks_like": "".join(lookalike_word)})

    # ---- finishing ---------------------------------------------------------

    def _raise_severity_inside_entities(self):
        for flag in self.flags:
            if flag.kind not in FLAGS_RAISED_INSIDE_WATCHED_NAMES or flag.start is None:
                continue
            for entity in self.entities:
                if entity.start < flag.end and flag.start < entity.end:
                    flag.severity = HIGH
                    flag.evidence["inside_name"] = entity.canonical_spelling
                    flag.evidence["tickers"] = [entity.ticker]
                    break

    def _build_clean_text(self):
        pieces = []
        position = 0
        while position < len(self.kept_characters):
            span = self.span_replacements.get(position)
            if span is not None:
                pieces.append(span[1])
                position = span[0]
                continue
            pieces.append(self.character_replacements.get(position, self.kept_characters[position]))
            position += 1
        return unicodedata.normalize("NFC", "".join(pieces))
