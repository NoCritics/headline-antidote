"""Visible-article extraction: the text a trader's LLM should receive.

Turns a news page into (headline, article body, flags), where:

* the headline is the heading a reader sees as the title, found by matching the
  page's <h1> elements against its metadata (JSON-LD, og:title) and, when given,
  the feed's title, instead of trusting the first <h1>;
* the body is the article text a reader sees: hidden elements are removed from
  the page before trafilatura's main-content detection runs, so navigation,
  "Trending now" boxes and comments are left out and hidden text never gets in;
* every hidden fragment that a standard extractor would have passed on, and every
  Unicode finding in the headline, body or metadata, is reported as a flag;
* the headline is compared with the feed and metadata titles, which never go through
  CSS or JavaScript: words the page's heading adds to them are flagged, which catches
  text hidden by JavaScript or by an overlay without running either;
* `browser_check_reasons` lists what this static reading could not rule out (scripts
  touching the headline, body text missing from the page's own copy of the article),
  so the caller can send only those pages to a browser (HeadlineGuard.verify_article_in_browser).

Use it where the page is turned into text, in front of whatever LLM scores it:

    article = guard.extract_article(page_html, feed_title=rss_title)
    if article.verdict != "quarantine":
        score = your_llm(article.headline, article.body)

Requires trafilatura (pip install trafilatura).
"""

import copy
import difflib
import json
import re
import unicodedata
from dataclasses import dataclass, field

from .css_values import quoted_strings
from .html_visibility import SCREEN_READER_ONLY_REASON, parse_document, visible_text_of_element
from .text_guard import HIGH, LOW, MEDIUM, Flag, _compact, reordered_text_flag, verdict_for_flags

HEADLINE_MATCH_THRESHOLD = 0.6
SITE_NAME_SEPARATORS = (" | ", " - ", " – ", " — ", " :: ", " · ")
DUPLICATE_HEADLINE_THRESHOLD = 0.9
# Hidden text is a harmless repeat when at most this share of its word trigrams is new.
MAXIMUM_REPEATED_SHARE_NEW = 0.1
# Hidden text inside these is interface text (accessibility labels, menus), not article content.
INTERFACE_TAGS = {"a", "button", "label", "form", "nav", "select", "option", "menu", "dialog"}
INTERFACE_ROLES = {"button", "navigation", "search", "dialog", "menu", "menubar", "toolbar", "tablist"}
# Screen-reader labels this short ("Published", "Image caption") are removed without a flag.
MAXIMUM_SCREEN_READER_LABEL_WORDS = 6
# A title shorter than this many words is too short to compare the headline with.
MINIMUM_TITLE_WORDS = 3
# Added words that change a headline's meaning even alone.
NEGATION_WORDS = {
    "not", "no", "never", "nor", "without", "cannot", "isn", "aren", "wasn", "weren", "won", "don",
    "doesn", "didn", "hasn", "haven", "hadn", "shouldn", "wouldn", "couldn", "nicht", "kein", "keine",
    "keinen", "nie", "niemals", "ohne", "pas", "jamais", "sans", "aucun", "aucune", "non", "nunca",
    "nada", "sin", "não", "nao", "sem", "nessun", "nessuna", "senza", "niet", "geen", "nooit", "inte",
    "ingen", "aldrig", "ikke", "bez", "не", "нет", "без", "ни", "ні", "немає", "değil", "yok",
}
# Body text missing from the page's own copy of the article is reported from this many words on.
MINIMUM_MISSING_RUN_WORDS = 12
# The page's copy counts as the same article when it covers at least this share of the body.
MINIMUM_COPY_COVERAGE = 0.6
# A class used on at most this many elements of the page names the headline's element.
MAXIMUM_DISTINCTIVE_CLASS_USES = 2
# A body passage missing from the page's copy is explained when a page description holds at
# least this share of its words, in order.
DESCRIPTION_MATCH_SHARE = 0.8
# Hidden passages that are at least this share of the article, in one block running to its end
# (at least TRAILING_BLOCK_HIDDEN_SHARE of the text from the first hidden passage on), are a
# collapsed article or a paywall: kept, with one medium flag. As in browser_check.py.
MOSTLY_HIDDEN_SHARE = 0.4
TRAILING_BLOCK_HIDDEN_SHARE = 0.9
# A body element is checked for scripts that change it only when it holds at least this many
# words of the article: smaller pieces can't carry a payload worth hiding.
MINIMUM_SCRIPTED_BODY_WORDS = 8
# Text whose hiding is only guessed (its color against an undeclared page background) is sent
# to the browser check when it puts at least this many words into the body.
MINIMUM_GUESSED_HIDDEN_WORDS = 3
# How close (in characters) an element lookup and a change must be to the element's name.
SCRIPT_WINDOW_CHARACTERS = 200
# A lookup with a literal argument: getElementById("x"), querySelector("#x .y"), $(".y").
LITERAL_LOOKUP_PATTERN = re.compile(
    r"(getElementById|getElementsByClassName|querySelector(?:All)?|\$|jQuery)\(\s*([\"'])([^\"'\n]{1,200})\2"
)
SELECTOR_NAME_PATTERN = re.compile(r"([#.])([A-Za-z_][\w-]*)")
DOM_LOOKUP_PATTERN = re.compile(
    r"getElementById|querySelector|getElementsByClassName|getElementsByTagName|closest\(|\$\(|jQuery\("
)
# Script code that changes what elements show.
DOM_MUTATION_PATTERN = re.compile(
    r"\.style\b|classList|className|setAttribute|\.hidden\b|\.remove\(|removeChild|innerHTML|outerHTML"
    r"|textContent|innerText|insertAdjacent|replaceWith|\.css\(|\.hide\(|\.addClass\(|\.attr\("
)


@dataclass
class ArticleResult:
    headline: str
    headline_source: str
    body: str
    flags: list
    tickers: list
    metadata_titles: dict
    # Why a browser check is worth running on this page; empty when the static reading is enough.
    browser_check_reasons: list = field(default_factory=list)
    headline_xpath: str = None  # the headline element's path in the page, for the browser check
    heading_text: str = ""      # the heading's visible text as this static reading sees it
    heading_full_text: str = ""  # all of the heading element's text, hidden parts included
    browser_verified: bool = False
    browser_milliseconds: float = None
    # Hidden text that is most of the article and runs to its end: usually a "Read more" collapse
    # or a paywall, but an attacker's hidden ending looks the same. Readers can't see it, so it is
    # never part of body; it is untrusted text a pipeline may use only by choice (see the README).
    hidden_ending: str = ""

    @property
    def verdict(self):
        """'quarantine' (any high flag), 'review' (any medium flag) or 'pass'."""
        return verdict_for_flags(self.flags)

    @property
    def needs_browser_check(self):
        return bool(self.browser_check_reasons)


def _normalized_title(text):
    return " ".join(unicodedata.normalize("NFKC", text or "").casefold().split())


def _without_site_name(title):
    """'Headline | Site' -> 'Headline'. Only the trailing segment is removed, never compared alone."""
    best_position = -1
    for separator in SITE_NAME_SEPARATORS:
        position = title.rfind(separator)
        if position > best_position:
            best_position = position
    if best_position <= 0:
        return title
    return title[:best_position]


def _title_similarity(candidate, reference):
    candidate_text = _normalized_title(candidate)
    reference_text = _normalized_title(reference)
    if not candidate_text or not reference_text:
        return 0.0
    best_ratio = 0.0
    for variant in _title_variants(reference_text):
        ratio = difflib.SequenceMatcher(a=candidate_text, b=variant, autojunk=False).ratio()
        best_ratio = max(best_ratio, ratio)
    return best_ratio


def _find_json_ld_string(value, key):
    """The first non-blank string under key anywhere in a parsed JSON-LD value, or None."""
    if isinstance(value, dict):
        found = value.get(key)
        if isinstance(found, str) and found.strip():
            return found
        for nested_value in value.values():
            found = _find_json_ld_string(nested_value, key)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_json_ld_string(item, key)
            if found:
                return found
    return None


def _first_json_ld_string(root, key):
    """_find_json_ld_string over the page's JSON-LD scripts in order; broken JSON is skipped."""
    for script in root.xpath("//script[@type='application/ld+json']"):
        try:
            found = _find_json_ld_string(json.loads(script.text or ""), key)
        except (ValueError, RecursionError):
            continue
        if found:
            return found
    return None


def _metadata_titles(root):
    titles = {}
    headline = _first_json_ld_string(root, "headline")
    if headline:
        titles["json-ld headline"] = headline.strip()
    for label, xpath in (("og:title", "//meta[@property='og:title']/@content"),
                         ("twitter:title", "//meta[@name='twitter:title']/@content")):
        values = root.xpath(xpath)
        if values and values[0].strip():
            titles[label] = values[0].strip()
    title_values = root.xpath("//title/text()")
    if title_values and title_values[0].strip():
        titles["<title>"] = title_values[0].strip()
    return titles


def _comparison_words(text):
    """Word tokens without punctuation, so "what’s" and "what's" compare equal."""
    return re.findall(r"\w+", unicodedata.normalize("NFKC", text or "").casefold())


def _trigrams(words):
    trigrams = set()
    for position in range(len(words) - 2):
        trigrams.add((words[position], words[position + 1], words[position + 2]))
    return trigrams


def _word_trigrams(text):
    return _trigrams(_comparison_words(text))


def _leading_label_words(headline_element):
    """The words of the heading's first child element when the heading starts with it (no
    text before it): the shape of a kicker. [] otherwise."""
    if (headline_element.text or "").strip():
        return []
    for child in headline_element:
        if not isinstance(child.tag, str):
            continue
        return _comparison_words(" ".join(child.itertext()))
    return []


def _adds_new_text(hidden_text, visible_text, visible_trigrams):
    """False when hidden text only repeats what readers already see (a hidden copy of the article,
    a duplicate caption): it cannot change what the model learns. Injected text is new."""
    hidden_words = _comparison_words(hidden_text)
    if len(hidden_words) < 3:
        return " ".join(hidden_words) not in " ".join(_comparison_words(visible_text))
    hidden_trigrams = _word_trigrams(hidden_text)
    new_trigrams = 0
    for trigram in hidden_trigrams:
        if trigram not in visible_trigrams:
            new_trigrams += 1
    return new_trigrams > MAXIMUM_REPEATED_SHARE_NEW * len(hidden_trigrams)


def _remove_keeping_tail(node):
    parent = node.getparent()
    if parent is None:
        return
    tail = node.tail
    if tail:
        previous = node.getprevious()
        if previous is not None:
            previous.tail = (previous.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail
    parent.remove(node)


def _title_variants(title):
    """The title, then the title without each trailing ' | Site name' segment."""
    variants = [title]
    shortened = _without_site_name(title)
    while shortened != variants[-1]:
        variants.append(shortened)
        shortened = _without_site_name(shortened)
    return variants


def _inserted_words(title_words, headline_words):
    """Words the headline adds when every title word appears in it, in order: the title is the
    headline with words left out. None when the two are worded differently."""
    matcher = difflib.SequenceMatcher(a=title_words, b=headline_words, autojunk=False)
    inserted = []
    for tag, title_start, title_end, headline_start, headline_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert":
            return None
        for word in headline_words[headline_start:headline_end]:
            inserted.append(word)
    return inserted


def _page_descriptions(root):
    """The page's summaries: meta description, og:/twitter:description, and JSON-LD
    description, alternativeHeadline and abstract."""
    descriptions = []
    for meta in root.iter("meta"):
        meta_name = (meta.get("name") or meta.get("property") or "").lower()
        if meta_name in ("description", "og:description", "twitter:description") and meta.get("content"):
            descriptions.append(meta.get("content"))
    for script in root.xpath("//script[@type='application/ld+json']"):
        try:
            pending = [json.loads(script.text or "")]
        except (ValueError, RecursionError):
            continue
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                for key, value in item.items():
                    if key in ("description", "alternativeHeadline", "abstract") and isinstance(value, str):
                        descriptions.append(value)
                    else:
                        pending.append(value)
            elif isinstance(item, list):
                for value in item:
                    pending.append(value)
    return descriptions


def _runs_not_in_descriptions(runs, descriptions):
    """The runs (space-joined comparison words) that no description holds, at least
    DESCRIPTION_MATCH_SHARE of their words in order."""
    description_words = []
    for description in descriptions:
        description_words.append(_comparison_words(description))
    unexplained = []
    for run in runs:
        run_words = run.split()
        explained = False
        for words in description_words:
            matcher = difflib.SequenceMatcher(a=words, b=run_words, autojunk=False)
            matched = 0
            for block in matcher.get_matching_blocks():
                matched += block.size
            if matched >= DESCRIPTION_MATCH_SHARE * len(run_words):
                explained = True
                break
        if not explained:
            unexplained.append(run)
    return unexplained


def _missing_runs(reference_text, body_text):
    """(coverage, runs): the share of body words found in the reference in order, and the
    runs of at least MINIMUM_MISSING_RUN_WORDS body words it lacks."""
    reference_words = _comparison_words(reference_text)
    body_words = _comparison_words(body_text)
    if not body_words:
        return 1.0, []
    matcher = difflib.SequenceMatcher(a=reference_words, b=body_words, autojunk=False)
    matched_words = 0
    runs = []
    for tag, reference_start, reference_end, body_start, body_end in matcher.get_opcodes():
        if tag == "equal":
            matched_words += body_end - body_start
        elif tag in ("insert", "replace") and body_end - body_start >= MINIMUM_MISSING_RUN_WORDS:
            runs.append(" ".join(body_words[body_start:body_end]))
    return matched_words / len(body_words), runs


def _with_field(flags, field_name, detail_prefix=""):
    for flag in flags:
        flag.field = field_name
        if detail_prefix:
            flag.detail = detail_prefix + flag.detail
    return flags


def _inline_scripts_that_change_elements(root):
    """The code of each inline script (not JSON data) that changes the page somewhere."""
    scripts = []
    for script in root.iter("script"):
        if script.get("src") or (script.get("type") or "").lower() in ("application/ld+json", "application/json"):
            continue
        code = script.text or ""
        if code and DOM_MUTATION_PATTERN.search(code) is not None:
            scripts.append(code)
    return scripts


class _ArticleExtraction:
    def __init__(self, guard, html, feed_title, stylesheets=None, feed_body=None):
        self.guard = guard
        self.feed_title = feed_title
        self.feed_body = feed_body
        self.root, self.rules = parse_document(html, stylesheets)
        self.flags = []
        self.tickers = []
        self.browser_check_reasons = []
        self.hidden_ending = ""
        self._page_wrappers = set()

    def _add_browser_reason(self, reason):
        if reason not in self.browser_check_reasons:
            self.browser_check_reasons.append(reason)

    def _add_tickers(self, tickers):
        for ticker in tickers:
            if ticker not in self.tickers:
                self.tickers.append(ticker)

    def run(self):
        metadata_titles = _metadata_titles(self.root)
        headline_text, headline_source, headline_element = self._locate_headline(metadata_titles)
        headline_result = self.guard.analyze(headline_text)
        self.flags.extend(_with_field(headline_result.flags, "headline"))
        self._add_tickers(headline_result.tickers)
        self._check_metadata(metadata_titles, headline_text)
        headline_xpath = None
        heading_full_text = ""
        model_headline = headline_result.clean_text
        if headline_element is not None:
            headline_xpath = headline_element.getroottree().getpath(headline_element)
            heading_full_text = " ".join(" ".join(headline_element.itertext()).split())
            title_wording = self._check_headline_against_titles(metadata_titles, headline_text, headline_element)
            if title_wording is not None:
                # The added words may be hidden from readers: give the model the title's wording.
                title_result = self.guard.analyze(title_wording)
                model_headline = title_result.clean_text
                headline_source += "; words no title has were left out"
            self._check_headline_drawing(headline_element)
            self._check_scripts_touching(headline_element)
        body_text = self._extract_body(headline_text, headline_element)
        self._check_body_against_page_copy(body_text)
        body_result = self.guard.analyze(body_text)
        self.flags.extend(_with_field(body_result.flags, "body"))
        self._add_tickers(body_result.tickers)
        return ArticleResult(
            model_headline, headline_source, body_result.clean_text,
            self.flags, self.tickers, metadata_titles, self.browser_check_reasons, headline_xpath,
            headline_text if headline_element is not None else "", heading_full_text,
            hidden_ending=self.hidden_ending,
        )

    # ---- headline ---------------------------------------------------------

    def _locate_headline(self, metadata_titles):
        references = self._titles_to_compare(metadata_titles)
        for heading_tag in ("h1", "h2"):
            best = None
            for heading in self.root.iter(heading_tag):
                visible_text, hidden_fragments = visible_text_of_element(heading, self.rules)
                if not visible_text:
                    continue
                for reference_label, reference_text in references:
                    similarity = _title_similarity(visible_text, reference_text)
                    if similarity >= HEADLINE_MATCH_THRESHOLD and (best is None or similarity > best[0]):
                        best = (similarity, visible_text, hidden_fragments, reference_label, heading)
            if best is not None:
                similarity, visible_text, hidden_fragments, reference_label, heading_element = best
                self._flag_hidden_in_headline(hidden_fragments)
                return visible_text, f"<{heading_tag}> matching the {reference_label}", heading_element

        if not references:
            for heading in self.root.iter("h1"):
                visible_text, hidden_fragments = visible_text_of_element(heading, self.rules)
                if visible_text:
                    self._flag_hidden_in_headline(hidden_fragments)
                    self.flags.append(Flag(
                        "headline_unconfirmed", LOW, None, None, visible_text,
                        "no metadata or feed title to confirm this <h1> is the headline", "headline",
                    ))
                    return visible_text, "first visible <h1> (unconfirmed)", heading
            return "", "none found", None

        fallback_label, fallback_text = references[0]
        for preferred_label in ("json-ld headline", "og:title", "feed title"):
            for reference_label, reference_text in references:
                if reference_label == preferred_label:
                    fallback_label, fallback_text = reference_label, reference_text
                    break
            if fallback_label == preferred_label:
                break
        self.flags.append(Flag(
            "headline_from_metadata", LOW, None, None, fallback_text,
            f"no visible heading matches the page's titles; using the {fallback_label}, "
            "which is not checked for visibility", "headline",
        ))
        return fallback_text, fallback_label, None

    def _flag_hidden_in_headline(self, hidden_fragments):
        for fragment in hidden_fragments:
            if fragment.kind == "reordered_text":
                self.flags.append(reordered_text_flag(fragment, HIGH, "headline"))
            elif fragment.kind == "html_comment":
                self.flags.append(Flag(
                    "html_comment_text", MEDIUM, None, None, fragment.text,
                    "text inside an HTML comment in the headline", "headline",
                ))
            else:
                self.flags.append(Flag(
                    "hidden_html_text", fragment.severity, None, None, fragment.text,
                    f"hidden text in the headline ({fragment.reason}); a standard scraper would pass it on",
                    "headline",
                ))

    def _check_metadata(self, metadata_titles, headline_text):
        """Unicode checks on metadata titles, which scrapers such as newspaper4k use as the headline."""
        already_checked = {_compact(headline_text)}
        for label, title in metadata_titles.items():
            compact_title = _compact(title)
            if compact_title in already_checked:
                continue
            already_checked.add(compact_title)
            metadata_result = self.guard.analyze(title)
            self.flags.extend(_with_field(metadata_result.flags, "metadata", f"in the {label}: "))

    def _titles_to_compare(self, metadata_titles):
        titles = []
        if self.feed_title:
            titles.append(("feed title", self.feed_title))
        for label in ("json-ld headline", "og:title", "twitter:title", "<title>"):
            if label in metadata_titles:
                titles.append((label, metadata_titles[label]))
        return titles

    def _check_headline_against_titles(self, metadata_titles, headline_text, headline_element):
        """Words the visible heading adds to the feed and metadata titles.

        Those titles are plain text that never goes through CSS or JavaScript. When one of
        them is the heading with words left out, and no title has the extra words, they are
        likely hidden from readers by something this reader cannot evaluate (a script, an
        overlay). Differently worded titles (an SEO title) are not compared.

        Returns the title's wording when the added words change the meaning, otherwise None.
        """
        headline_words = _comparison_words(headline_text)
        all_title_words = set()
        titles = self._titles_to_compare(metadata_titles)
        for _, title in titles:
            for word in _comparison_words(title):
                all_title_words.add(word)
        best = None
        for label, title in titles:
            for variant in _title_variants(title):
                title_words = _comparison_words(variant)
                if len(title_words) < MINIMUM_TITLE_WORDS:
                    continue
                inserted = _inserted_words(title_words, headline_words)
                if inserted is None:
                    continue
                if best is None or len(inserted) < len(best[1]):
                    best = (label, inserted, variant)
        if best is None:
            return None
        label, inserted, title_wording = best
        unexplained = []
        for word in inserted:
            if word not in all_title_words:
                unexplained.append(word)
        if not unexplained:
            return None
        meaningful = len(unexplained) >= 2
        negation_or_number = False
        for word in unexplained:
            if word in NEGATION_WORDS or word.isdigit():
                meaningful = True
                negation_or_number = True
        # A topic label in its own element before the headline ("Handel mit Wertpapieren"): a
        # common layout, so low; the model still gets the title's wording until a browser looks.
        kicker = (meaningful and not negation_or_number
                  and _leading_label_words(headline_element) == list(unexplained)
                  and list(inserted[:len(unexplained)]) == list(unexplained))
        severity = MEDIUM if meaningful and not kicker else LOW
        detail = (f"the page's heading adds {' '.join(unexplained)!r} to the {label}, and no other title has "
                  "these words; they may be hidden from readers by a script or an overlay")
        if kicker:
            detail += "; they are a label in their own element before the headline (a kicker)"
        if meaningful:
            detail += "; the model gets the title's wording"
        self.flags.append(Flag("headline_adds_words", severity, None, None, " ".join(unexplained), detail, "headline"))
        # Even one ordinary word could be hidden ("surge <span>fraud</span>"): let a browser settle it.
        self._add_browser_reason(f"the heading adds words to the {label}")
        if not meaningful:
            return None
        return title_wording.strip()

    def _check_headline_drawing(self, headline_element):
        """Words readers see that the text lacks: CSS-generated text, and embedded fonts."""
        if hasattr(self.rules, "generated_text_candidates"):
            generated_parts = []
            unchecked = False
            for element in headline_element.iter():
                if not isinstance(element.tag, str):
                    continue
                # Rules under @supports, @container or @scope may or may not apply in Chrome, so
                # every content value some combination of them shows counts.
                contents, element_unchecked = self.rules.generated_text_candidates(element)
                if element_unchecked:
                    unchecked = True
                for content in contents:
                    for string in quoted_strings(content):
                        letters = 0
                        for character in string:
                            if character.isalpha():
                                letters += 1
                        if letters >= 2 and string.strip() not in generated_parts:
                            generated_parts.append(string.strip())
            if generated_parts or unchecked:
                detail = ("readers see this text in the headline, added by CSS (::before/::after); "
                          "scrapers and the model never receive it")
                if unchecked:
                    detail += ("; CSS may also add other text here, under more @supports, @container "
                               "or @scope conditions than were checked")
                self.flags.append(Flag(
                    "css_generated_text", MEDIUM, None, None, " ".join(generated_parts), detail, "headline",
                ))
        embedded_families = getattr(self.rules, "data_uri_font_families", None)
        if embedded_families and hasattr(self.rules, "font_family_for"):
            families_text = self.rules.font_family_for(headline_element)
            if families_text is None:
                # A `font` shorthand names the family after the size.
                node = headline_element
                while node is not None and families_text is None:
                    if isinstance(node.tag, str):
                        families_text = self.rules.full_declarations(node).get("font")
                    node = node.getparent()
            for family in (families_text or "").split(","):
                family_name = family.strip().strip("'\"").lower()
                for embedded_family in embedded_families:
                    if family_name == embedded_family or family_name.endswith(" " + embedded_family):
                        self.flags.append(Flag(
                            "embedded_font", MEDIUM, None, None, embedded_family,
                            "the headline is drawn with a font embedded in the page's CSS (a data: URI); "
                            "such a font can draw other letters than the text contains",
                            "headline",
                        ))
                        self._add_browser_reason("the headline uses a font embedded in the page")
                        return

    def _check_scripts_touching(self, headline_element):
        """Scripts that may change the headline after the page loads, which this reader never runs."""
        for element in headline_element.iter():
            if not isinstance(element.tag, str):
                continue
            if element.tag.lower() == "script":
                self._add_browser_reason("a script inside the headline")
            for attribute_name in element.attrib:
                if attribute_name.lower().startswith("on"):
                    self._add_browser_reason("an event-handler attribute inside the headline")
        names = self._distinctive_names(headline_element.iter(), self.root)
        changed_name = self._name_a_script_changes(names, self.root)
        if changed_name is not None:
            self._add_browser_reason(f"an inline script finds {changed_name!r}, used in the headline, and changes it")

    @staticmethod
    def _distinctive_names(elements, root):
        """Ids, and classes used on at most a couple of elements of the page, of the given
        elements. Utility classes ("font-bold") and component names appear in every page's
        script data, so only distinctive names say a script targets these elements."""
        candidate_classes = set()
        names = []
        for element in elements:
            if not isinstance(element.tag, str):
                continue
            element_id = element.get("id")
            if element_id and len(element_id) >= 2 and element_id not in names:
                names.append(element_id)
            for class_name in (element.get("class") or "").split():
                if len(class_name) >= 3:
                    candidate_classes.add(class_name)
        if candidate_classes:
            class_uses = {}
            for element in root.iter():
                if not isinstance(element.tag, str):
                    continue
                for class_name in (element.get("class") or "").split():
                    if class_name in candidate_classes:
                        class_uses[class_name] = class_uses.get(class_name, 0) + 1
            for class_name in sorted(candidate_classes):
                if class_uses.get(class_name, 0) <= MAXIMUM_DISTINCTIVE_CLASS_USES:
                    names.append(class_name)
        return names

    @staticmethod
    def _name_a_script_changes(names, root):
        """The first of names that an inline script looks up and changes, or None."""
        if not names:
            return None
        for code in _inline_scripts_that_change_elements(root):
            for name in names:
                for match in re.finditer(r"[\"'#. ]" + re.escape(name) + r"[\"' .\[:)]", code):
                    # The name, an element lookup and a change close together: a script that finds
                    # this element and changes it, not a name somewhere in a data blob.
                    window = code[max(0, match.start() - SCRIPT_WINDOW_CHARACTERS):match.end() + SCRIPT_WINDOW_CHARACTERS]
                    if DOM_LOOKUP_PATTERN.search(window) and DOM_MUTATION_PATTERN.search(window):
                        return name
        return None

    @staticmethod
    def _names_scripts_change(root):
        """(ids, classes) that inline scripts look up by a literal name and change nearby."""
        ids = set()
        classes = set()
        for code in _inline_scripts_that_change_elements(root):
            for lookup in LITERAL_LOOKUP_PATTERN.finditer(code):
                window = code[lookup.end():lookup.end() + SCRIPT_WINDOW_CHARACTERS]
                if DOM_MUTATION_PATTERN.search(window) is None:
                    continue
                function_name = lookup.group(1)
                argument = lookup.group(3)
                if function_name == "getElementById":
                    ids.add(argument.strip())
                elif function_name == "getElementsByClassName":
                    for class_name in argument.split():
                        classes.add(class_name)
                else:
                    for kind, name in SELECTOR_NAME_PATTERN.findall(argument):
                        if kind == "#":
                            ids.add(name)
                        else:
                            classes.add(name)
        return ids, classes

    def _check_scripts_touching_body(self, body_text, unpruned_root):
        """Inline scripts that look up an element holding article text and change it: text a
        script hides after loading reads as visible here. Only literal names count (an id, or
        a class used on at most a couple of elements), and the element must hold at least
        MINIMUM_SCRIPTED_BODY_WORDS words, all of them in the body."""
        ids, classes = self._names_scripts_change(unpruned_root)
        if not ids and not classes:
            return
        candidates = []
        class_uses = {}
        for element in unpruned_root.iter():
            if not isinstance(element.tag, str):
                continue
            if element.get("id") in ids:
                candidates.append((element.get("id"), element))
            if classes:
                for class_name in (element.get("class") or "").split():
                    if class_name in classes:
                        class_uses[class_name] = class_uses.get(class_name, 0) + 1
                        candidates.append((class_name, element))
        body_compact = None
        for name, element in candidates:
            if name in class_uses and class_uses[name] > MAXIMUM_DISTINCTIVE_CLASS_USES:
                continue
            element_text = " ".join(element.itertext())
            if len(element_text.split()) < MINIMUM_SCRIPTED_BODY_WORDS:
                continue
            if body_compact is None:
                body_compact = _compact(body_text)
            if _compact(element_text) in body_compact:
                self._add_browser_reason(f"an inline script finds {name!r}, which holds article text, "
                                         "and changes it")
                return

    def _check_body_against_page_copy(self, body_text):
        """Body text missing from the page's own copy of the article (JSON-LD articleBody, or a
        feed's full text). Subheadings and captions often differ too, so this only asks for
        a browser check and never changes the verdict."""
        reference = self.feed_body
        reference_label = "feed's article text"
        if not reference:
            reference = _first_json_ld_string(self.root, "articleBody")
            reference_label = "page's JSON-LD articleBody"
        if not reference or not body_text:
            return
        coverage, runs = _missing_runs(reference, body_text)
        if coverage < MINIMUM_COPY_COVERAGE or not runs:
            return
        # The standfirst under the headline is usually in the page's description, not its copy.
        runs = _runs_not_in_descriptions(runs, _page_descriptions(self.root))
        if not runs:
            return
        self.flags.append(Flag(
            "body_text_not_in_page_copy", LOW, None, None, " / ".join(runs)[:500],
            f"{len(runs)} passage(s) of the body are missing from the {reference_label}; usually "
            "subheadings or captions, but text hidden by a script would look the same",
            "body",
        ))
        self._add_browser_reason(f"body passages missing from the {reference_label}")

    # ---- body -------------------------------------------------------------

    def _set_aside_hidden_ending(self, hidden_passages, unpruned_compact, body):
        """When the hidden passages are most of the article (at least MOSTLY_HIDDEN_SHARE of it)
        and run as one block to its end, as in an article collapsed behind "Read more" or a
        metered paywall: one MEDIUM flag saying the body is incomplete replaces their LOW flags,
        and their text goes to self.hidden_ending. It stays out of the body either way, since
        an attacker's hidden ending looks the same. The same rule as the browser check's."""
        if not hidden_passages:
            return
        hidden_passages.sort()
        first_hidden_position = hidden_passages[0][0]
        hidden_characters = 0
        for _, passage_compact, _, _ in hidden_passages:
            hidden_characters += len(passage_compact)
        visible_after = 0
        for line in body.split("\n"):
            line_compact = _compact(line)
            if line_compact and unpruned_compact.find(line_compact) > first_hidden_position:
                visible_after += len(line_compact)
        all_characters = hidden_characters + len(_compact(body))
        if hidden_characters < MOSTLY_HIDDEN_SHARE * all_characters:
            return
        if hidden_characters < TRAILING_BLOCK_HIDDEN_SHARE * (hidden_characters + visible_after):
            return
        flag_positions = set()
        set_aside = []
        for _, _, passage_text, flag_position in hidden_passages:
            flag_positions.add(flag_position)
            set_aside.append(" ".join(passage_text.split()))
        kept_flags = []
        for position, flag in enumerate(self.flags):
            if position not in flag_positions:
                kept_flags.append(flag)
        self.flags = kept_flags
        self.flags.append(Flag(
            "most_of_article_hidden", MEDIUM, None, None, "",
            f"{len(hidden_passages)} passage(s) running to the end of the article, most of its text, are hidden "
            "from readers (usually a \"Read more\" collapse or a paywall, but it could be a hidden ending): "
            "the body is incomplete; the hidden text is in hidden_ending, not in the body",
            "body",
        ))
        self.hidden_ending = "\n".join(set_aside)

    def _check_guessed_hiding(self, guessed_fragments, body):
        body_compact = _compact(body)
        for fragment in guessed_fragments:
            fragment_text = " ".join(" ".join(fragment.element.itertext()).split())
            if len(fragment_text.split()) < MINIMUM_GUESSED_HIDDEN_WORDS:
                continue
            if _compact(fragment_text) not in body_compact:
                continue
            self.flags.append(Flag(
                "possibly_hidden_text", LOW, None, None, fragment_text[:500],
                f"may be invisible ({fragment.reason}); kept in the body until a browser check decides",
                "body",
            ))
            self._add_browser_reason("body text whose color may match the page background")
            return

    def _is_interface_text(self, element):
        """Part of a link, button, form or navigation: accessibility labels, not article content.
        An element that also holds the headline wraps the page (ASP.NET puts every page in one
        <form>), so the walk stops there."""
        page_wrappers = self._page_wrappers
        node = element
        while node is not None:
            if node in page_wrappers:
                return False
            node_tag = node.tag.lower() if isinstance(node.tag, str) else ""
            if node_tag in INTERFACE_TAGS or (node.get("role") or "").lower() in INTERFACE_ROLES:
                return True
            node = node.getparent()
        return False

    @staticmethod
    def _is_inside_headline(element, headline_element):
        if headline_element is None:
            return False
        if element is headline_element:
            return True
        for ancestor in element.iterancestors():
            if ancestor is headline_element:
                return True
        return False

    def _extract_body(self, headline_text, headline_element):
        """Article text with every hidden element removed first.

        Real pages often hide text inside articles (duplicate captions, promotions,
        paywall notices, related headlines), so hidden body text is always removed but
        only flagged when a standard extractor would actually have passed it to the
        model, and only as LOW: the model never sees it either way.
        """
        import trafilatura

        extraction_options = {"include_comments": False, "include_tables": True, "output_format": "txt"}
        unpruned_root = copy.deepcopy(self.root)
        self._page_wrappers = set()
        if headline_element is not None:
            for ancestor in headline_element.iterancestors():
                self._page_wrappers.add(ancestor)
        candidates, guessed_fragments = self._remove_hidden_fragments(headline_element)

        body = trafilatura.extract(self.root, **extraction_options) or ""
        if not body.strip():
            self.flags.append(Flag(
                "article_body_not_found", LOW, None, None, "",
                "no article text was found on the page", "body",
            ))
            return ""
        self._check_scripts_touching_body(body, unpruned_root)
        self._check_guessed_hiding(guessed_fragments, body)

        if candidates:
            unpruned_compact = _compact(trafilatura.extract(unpruned_root, **extraction_options) or "")
            pruned_compact = _compact(body)
            visible_trigrams = _word_trigrams(headline_text + "\n" + body)
            reported = {_compact(headline_text)}
            hidden_passages = []
            for fragment, fragment_full_text in candidates:
                fragment_compact = _compact(fragment.text)
                if not fragment_compact or fragment_compact in reported:
                    continue
                short_label = len(fragment.text.split()) <= MAXIMUM_SCREEN_READER_LABEL_WORDS
                if fragment.reason.startswith(SCREEN_READER_ONLY_REASON) and short_label:
                    continue
                if (fragment_compact in unpruned_compact and fragment_compact not in pruned_compact
                        and _adds_new_text(fragment_full_text, headline_text + "\n" + body, visible_trigrams)):
                    reported.add(fragment_compact)
                    # Low: the text is removed, so the model never sees it, and real pages hide
                    # their own text all the time (paywall and print notices, collapsed bios).
                    # The flag still tells the caller the page carried hidden text.
                    self.flags.append(Flag(
                        "hidden_text_in_article", LOW, None, None, fragment.text[:500],
                        f"hidden from readers ({fragment.reason}); a standard extractor would pass it "
                        "to the model; removed from the body",
                        "body",
                    ))
                    if not short_label:
                        hidden_passages.append((unpruned_compact.find(fragment_compact), fragment_compact,
                                                fragment_full_text, len(self.flags) - 1))
            self._set_aside_hidden_ending(hidden_passages, unpruned_compact, body)
        return _without_repeated_headline(body, headline_text)

    def _is_article_candidate(self, element, headline_element):
        """Hidden text here is a candidate for a body flag: not in the headline, not interface text."""
        return not self._is_inside_headline(element, headline_element) and not self._is_interface_text(element)

    def _remove_hidden_fragments(self, headline_element):
        """Removes hidden text and the headline from self.root before extraction.

        Returns (candidates, guessed_fragments): (fragment, full text) pairs that may get a body
        flag, and fragments whose hiding is only guessed, which are kept for the browser.
        """
        _, hidden_fragments = visible_text_of_element(self.root, self.rules)
        candidates = []
        guessed_fragments = []
        # Loose text (an element's own text or a tail) first, before removing elements moves tails.
        for fragment in hidden_fragments:
            if fragment.text_of is None or fragment.severity != HIGH:
                continue
            owner, attribute = fragment.text_of
            context_element = owner if attribute == "text" else owner.getparent()
            if context_element is not None and self._is_article_candidate(context_element, headline_element):
                candidates.append((fragment, fragment.text))
            setattr(owner, attribute, None)
        for fragment in hidden_fragments:
            if fragment.element is None:
                continue
            if fragment.kind == "reordered_text":
                if not self._is_inside_headline(fragment.element, headline_element):
                    self.flags.append(reordered_text_flag(fragment, MEDIUM, "body"))
                continue
            if fragment.kind == "html_comment":
                _remove_keeping_tail(fragment.element)
                continue
            if fragment.severity != HIGH:
                # Hiding only guessed (its color against an undeclared page background): the text
                # is kept, and the browser, which knows the background, decides.
                if self._is_article_candidate(fragment.element, headline_element):
                    guessed_fragments.append(fragment)
                continue
            if self._is_article_candidate(fragment.element, headline_element):
                candidates.append((fragment, " ".join(fragment.element.itertext())))
            _remove_keeping_tail(fragment.element)
        if headline_element is not None and headline_element.getparent() is not None:
            _remove_keeping_tail(headline_element)  # returned separately as the headline
        return candidates, guessed_fragments


def _without_repeated_headline(body, headline_text):
    """The body without its first line when that line repeats the headline."""
    body_lines = body.split("\n")
    if body_lines and headline_text:
        first_line_similarity = difflib.SequenceMatcher(
            a=_normalized_title(body_lines[0]), b=_normalized_title(headline_text), autojunk=False
        ).ratio()
        if first_line_similarity >= DUPLICATE_HEADLINE_THRESHOLD:
            body_lines = body_lines[1:]
    return "\n".join(body_lines).strip()


def extract_article(guard, html, feed_title=None, stylesheets=None, feed_body=None):
    """feed_body: the article's full text from the feed (RSS content:encoded), when there is one;
    otherwise the page's JSON-LD articleBody is used for the body comparison."""
    return _ArticleExtraction(guard, html, feed_title, stylesheets, feed_body).run()
