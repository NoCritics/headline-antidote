"""Second opinion from a real browser for pages the static reading could not settle.

extract_article() reads HTML and CSS without running JavaScript or computing layout.
When it marks a page with needs_browser_check, verify_article_in_browser() renders the
same HTML in Chrome (browser_visibility.BrowserVerifier) and compares:

* headline words the static reading kept but the browser hides (a script, an element
  drawn over them): flagged high, and the model gets the browser's headline;
* headline words the static reading feared were hidden but the browser shows: the
  doubt is cleared, and the model gets the full heading back;
* body text the browser hides: removed from the body. Live pages hide plenty of
  harmless text with scripts (collapsed boxes, promotions, labels), so removed passages
  are flagged medium (review), short labels low. When most of the body is hidden (a
  paywall script), nothing is removed and the page is flagged for review;
* text cut off by a preview window (a metered paywall, a collapsed section) is the
  publisher's own text: kept, with a low flag.

A render that shows almost none of the article (a consent wall, the page navigating
away, a script error) is inconclusive: the static result is returned unchanged, with a
low flag, and the page still counts as needing a check.
"""

import re
import unicodedata
from dataclasses import replace

from .article import _comparison_words
from .text_guard import HIGH, LOW, MEDIUM, Flag

# Hidden runs shorter than this inside a visible paragraph are left alone (word-boundary noise).
MINIMUM_HIDDEN_RUN_WORDS = 3
# A paragraph counts as cut off by a preview window when at least this share of it is.
MINIMUM_CLIPPED_SHARE = 0.5
# When a browser hides at least this share of the body, as one block running to its end,
# it is a paywall (which hides the rest of the article), not a passage slipped in: the
# text is kept and the page reviewed. Hidden text elsewhere is removed as usual.
MOSTLY_HIDDEN_SHARE = 0.4
# "One block running to the end": at least this share of the words from the first hidden
# word on are hidden.
TRAILING_BLOCK_HIDDEN_SHARE = 0.9
# A render that shows less than this share of a body of at least INCONCLUSIVE_MINIMUM_WORDS
# words (a consent wall, a redirect, a script error) proves nothing: the static result stands.
INCONCLUSIVE_VISIBLE_SHARE = 0.05
INCONCLUSIVE_MINIMUM_WORDS = 30

VISIBLE = "visible"
CLIPPED = "clipped"
HIDDEN = "hidden"


def _word_counts(words):
    counts = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    return counts


def _missing_words(words, available_words):
    """Words (with repeats) that are not in available_words, in order."""
    available = _word_counts(available_words)
    missing = []
    for word in words:
        if available.get(word, 0) > 0:
            available[word] -= 1
        else:
            missing.append(word)
    return missing


def _trigrams(words):
    trigrams = set()
    for position in range(len(words) - 2):
        trigrams.add((words[position], words[position + 1], words[position + 2]))
    return trigrams


def _words_with_spans(text):
    """Comparison words of text, each with the (start, end) of the original token it came from."""
    words = []
    spans = []
    for match in re.finditer(r"\w+", text):
        for word in re.findall(r"\w+", unicodedata.normalize("NFKC", match.group()).casefold()):
            words.append(word)
            spans.append((match.start(), match.end()))
    return words, spans


def _shown_in(words, position, trigram_set, word_set):
    if len(words) < 3:
        return words[position] in word_set
    for start in (position - 2, position - 1, position):
        if 0 <= start and start + 3 <= len(words):
            if (words[start], words[start + 1], words[start + 2]) in trigram_set:
                return True
    return False


def _word_states(words, visible, clipped):
    """visible / clipped / hidden for each word, judged in its three-word context."""
    states = []
    for position in range(len(words)):
        if _shown_in(words, position, visible["trigrams"], visible["words"]):
            states.append(VISIBLE)
        elif _shown_in(words, position, clipped["trigrams"], clipped["words"]):
            states.append(CLIPPED)
        else:
            states.append(HIDDEN)
    return states


def _hidden_runs(states):
    """(first, last) word positions of each run of hidden words long enough to matter."""
    runs = []
    run_start = None
    for position in range(len(states) + 1):
        hidden = position < len(states) and states[position] == HIDDEN
        if hidden and run_start is None:
            run_start = position
        elif not hidden and run_start is not None:
            if position - run_start >= MINIMUM_HIDDEN_RUN_WORDS or (run_start == 0 and position == len(states)):
                runs.append((run_start, position - 1))
            run_start = None
    return runs


def _without_runs(paragraph, spans, runs):
    kept_parts = []
    cursor = 0
    for first, last in runs:
        kept_parts.append(paragraph[cursor:spans[first][0]])
        cursor = spans[last][1]
    kept_parts.append(paragraph[cursor:])
    return re.sub(r"\s+", " ", "".join(kept_parts)).strip()


def _text_index(text):
    words = _comparison_words(text)
    return {"words": set(words), "trigrams": _trigrams(words)}


def _has_reordered_headline(flags):
    for flag in flags:
        if flag.kind == "reordered_text" and flag.field == "headline":
            return True
    return False


def _compare_headline(guard, article, rendered, flags):
    """(headline, headline_source, flags) after comparing the heading with the browser's."""
    headline = article.headline
    headline_source = article.headline_source
    if rendered.headline_text is None or not article.heading_text:
        return headline, headline_source, flags
    static_words = _comparison_words(article.heading_text)
    rendered_words = _comparison_words(rendered.headline_text)
    hidden_words = _missing_words(static_words, rendered_words)
    added_words = _missing_words(rendered_words, static_words)
    if hidden_words:
        flags.append(Flag(
            "hidden_html_text", HIGH, None, None, " ".join(hidden_words),
            "in a browser the headline shows without these words (hidden by a script or an element "
            "drawn over them); HTML-based scrapers would pass them on",
            "headline",
        ))
        headline = guard.analyze(rendered.headline_text).clean_text
        headline_source += "; as shown in a browser"
    elif _has_reordered_headline(flags):
        # A browser's text gives the letters in source order, so it can't confirm words shown to
        # readers reversed: the static reading's headline stands.
        pass
    else:
        # Every word is visible: the fear that the heading's extra words were hidden is cleared.
        kept_flags = []
        cleared = False
        for flag in flags:
            if flag.kind == "headline_adds_words":
                cleared = True
                continue
            kept_flags.append(flag)
        flags = kept_flags
        if cleared:
            headline = guard.analyze(article.heading_text).clean_text
            headline_source = headline_source.replace("; words no title has were left out", "")
            headline_source += "; every word confirmed visible in a browser"
    if added_words:
        flags.append(Flag(
            "scraper_text_differs", MEDIUM, None, None, rendered.headline_text,
            f"the browser shows headline words missing from the page's HTML (added by a script): "
            f"{' '.join(added_words)!r}",
            "headline",
        ))
    return headline, headline_source, flags


def compare_with_rendered_page(guard, article, rendered):
    """A new ArticleResult with the browser's findings merged in (see the module docstring)."""
    flags = []
    for flag in article.flags:
        flags.append(flag)
    if not rendered.complete:
        flags.append(Flag(
            "browser_check_incomplete", LOW, None, None, rendered.note,
            "the page did not finish loading in the browser; the check used what had rendered", "page",
        ))
    visible = _text_index(rendered.page_text)
    clipped = _text_index(rendered.clipped_text)
    paragraphs = []
    all_states = []
    for paragraph in article.body.split("\n"):
        words, spans = _words_with_spans(paragraph)
        states = _word_states(words, visible, clipped)
        for state in states:
            all_states.append(state)
        paragraphs.append((paragraph, words, spans, states))
    body_words = len(all_states)
    shown_words = 0
    for state in all_states:
        if state != HIDDEN:
            shown_words += 1
    if body_words >= INCONCLUSIVE_MINIMUM_WORDS and shown_words < INCONCLUSIVE_VISIBLE_SHARE * body_words:
        # On a page the static reading sent to the browser, the reason for checking still stands.
        flags.append(Flag(
            "browser_check_inconclusive", MEDIUM if article.needs_browser_check else LOW, None, None, rendered.note,
            f"the browser showed {shown_words} of the body's {body_words} words (a consent wall, a redirect "
            "or a script error); nothing was concluded, the static result stands"
            + (", and the reason for the check is unresolved" if article.needs_browser_check else ""),
            "page",
        ))
        return replace(article, flags=flags, browser_milliseconds=rendered.milliseconds)

    headline, headline_source, flags = _compare_headline(guard, article, rendered, flags)
    hidden_words = 0
    first_hidden = None
    for position, state in enumerate(all_states):
        if state == HIDDEN:
            hidden_words += 1
            if first_hidden is None:
                first_hidden = position
    trailing_block = False
    if first_hidden is not None:
        hidden_after_first = 0
        for state in all_states[first_hidden:]:
            if state == HIDDEN:
                hidden_after_first += 1
        trailing_block = hidden_after_first >= TRAILING_BLOCK_HIDDEN_SHARE * (body_words - first_hidden)
    if body_words and hidden_words >= MOSTLY_HIDDEN_SHARE * body_words and trailing_block:
        flags.append(Flag(
            "most_of_article_hidden", MEDIUM, None, None, "",
            f"a browser hides the last {hidden_words} of the body's {body_words} words from readers: "
            "usually a paywall, but it could be a hidden ending; kept in the body",
            "body",
        ))
        return replace(
            article, headline=headline, headline_source=headline_source, flags=flags,
            browser_check_reasons=[], browser_verified=True, browser_milliseconds=rendered.milliseconds,
        )

    kept_paragraphs = []
    clipped_paragraphs = 0
    for paragraph, words, spans, states in paragraphs:
        if not words:
            kept_paragraphs.append(paragraph)
            continue
        clipped_count = 0
        for state in states:
            if state == CLIPPED:
                clipped_count += 1
        if clipped_count >= MINIMUM_CLIPPED_SHARE * len(words):
            clipped_paragraphs += 1
        runs = _hidden_runs(states)
        if not runs:
            kept_paragraphs.append(paragraph)
            continue
        removed_parts = []
        for first, last in runs:
            removed_parts.append(paragraph[spans[first][0]:spans[last][1]])
        remaining = _without_runs(paragraph, spans, runs)
        # Low, as in the static reading: removed, so the model never sees it.
        flags.append(Flag(
            "hidden_text_in_article", LOW, None, None, " … ".join(removed_parts)[:500],
            "a browser hides this from readers (a script or an element drawn over it); removed from the body",
            "body",
        ))
        if remaining:
            kept_paragraphs.append(remaining)
    if clipped_paragraphs:
        flags.append(Flag(
            "text_behind_preview_window", LOW, None, None, "",
            f"{clipped_paragraphs} paragraph(s) are cut off by a preview window in the browser (a metered "
            "paywall or a collapsed section); this is the publisher's text, kept in the body",
            "body",
        ))
    body = "\n".join(kept_paragraphs).strip()

    return replace(
        article, headline=headline, headline_source=headline_source, body=body, flags=flags,
        browser_check_reasons=[], browser_verified=True, browser_milliseconds=rendered.milliseconds,
    )


def verify_article_in_browser(guard, article, html, url, verifier):
    """Renders html as the page at url with a BrowserVerifier and merges what readers see."""
    full_heading_text = article.heading_full_text or article.heading_text
    rendered = verifier.render(url, html, article.headline_xpath, full_heading_text,
                               expected_words=len(article.body.split()))
    return compare_with_rendered_page(guard, article, rendered)
