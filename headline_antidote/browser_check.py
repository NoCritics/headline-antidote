"""Second opinion from a real browser for pages the static reading could not settle.

extract_article() reads HTML and CSS without running JavaScript or computing layout.
When it marks a page with needs_browser_check, verify_article_in_browser() renders the
same HTML in Chrome (browser_visibility.BrowserVerifier) and compares:

* headline words the static reading kept but the browser hides (a script, an element
  drawn over them): flagged high, and the model gets the browser's headline;
* headline words the static reading feared were hidden (headline_adds_words) but the
  browser shows: the doubt is cleared, and the model gets the full heading back. The
  browser's answer always replaces that suspicion: words it hides become one hidden_html_text
  flag, and only the words it hides are flagged;
* no rendered heading matching the static one (a script removed or rewrote it): flagged
  high, and the page is not marked verified;
* body text the browser hides: removed from the body (this includes text the static reading
  only suspected, possibly_hidden_text, which a conclusive render always settles). Live pages hide plenty of
  harmless text with scripts (collapsed boxes, promotions, labels), so removed passages
  are flagged low, as in the static reading. When most of the body is hidden as one block
  running to its end (a paywall script, or a hidden ending), it goes to hidden_ending with
  one medium flag saying the body is incomplete;
* text cut off by a preview window (a metered paywall, a collapsed section) is the
  publisher's own text: kept, with a low flag.

A render that shows almost none of the article (a consent wall, the page navigating
away, a script error, or a script hiding nearly all of the body) is inconclusive: the
static result is returned with a medium flag, so the page goes to review, and it still
counts as needing a check.
"""

import re
from dataclasses import replace

from .article import _comparison_words, _trigrams
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


def _missing_words(words, available_words):
    """Words (with repeats) that are not in available_words, in order."""
    available = {}
    for word in available_words:
        available[word] = available.get(word, 0) + 1
    missing = []
    for word in words:
        if available.get(word, 0) > 0:
            available[word] -= 1
        else:
            missing.append(word)
    return missing


def _words_with_spans(text):
    """Comparison words of text, each with the (start, end) of the original token it came from."""
    words = []
    spans = []
    for match in re.finditer(r"\w+", text):
        for word in _comparison_words(match.group()):
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
    if not article.heading_text:
        return headline, headline_source, flags
    if rendered.headline_text is None:
        # No rendered heading shares even half its words with the static one: a script removed or
        # rewrote it, so readers see another headline (or none) than the one the model would get.
        flags.append(Flag("headline_not_found_in_browser", HIGH, None, None, article.heading_text, {}, "headline"))
        return headline, headline_source, flags
    static_words = _comparison_words(article.heading_text)
    rendered_words = _comparison_words(rendered.headline_text)
    hidden_words = _missing_words(static_words, rendered_words)
    added_words = _missing_words(rendered_words, static_words)
    # Words the static reading hid only for a browser to settle: the render decides them.
    settled_ids = set()
    settled_texts = []
    for settled_flag in article.heading_settled_by_browser:
        settled_ids.add(id(settled_flag))
        settled_texts.append(settled_flag.original)
    settled_words = _comparison_words(" ".join(settled_texts))
    still_hidden = _missing_words(settled_words, added_words)
    shown_settled = len(still_hidden) < len(settled_words)
    added_words = _missing_words(added_words, settled_words)
    # The suspicion that words no title has were hidden is settled either way: the words the
    # browser hides become hidden_html_text, and the words it shows are cleared.
    suspected_adds_words = any(flag.kind == "headline_adds_words" for flag in flags)
    # By identity: a flag with the same text as a settled one may be a sure one.
    flags = [flag for flag in flags if id(flag) not in settled_ids and flag.kind != "headline_adds_words"]
    if still_hidden:
        flags.append(Flag(
            "hidden_html_text", HIGH, None, None, " ".join(still_hidden), {"cause": "svg_off_drawing"}, "headline",
        ))
    if hidden_words:
        flags.append(Flag(
            "hidden_html_text", HIGH, None, None, " ".join(hidden_words), {"cause": "script_or_overlay"}, "headline",
        ))
        headline = guard.analyze(rendered.headline_text).clean_text
        headline_source += "; as shown in a browser"
    elif _has_reordered_headline(flags):
        # A browser's text gives the letters in source order, so it can't confirm words shown to
        # readers reversed: the static reading's headline stands.
        pass
    elif suspected_adds_words:
        # Every word is visible: the fear that the heading's extra words were hidden is cleared.
        headline = guard.analyze(article.heading_text).clean_text
        headline_source = headline_source.replace("; words no title has were left out", "")
        headline_source += "; every word confirmed visible in a browser"
    if shown_settled and not hidden_words and not _has_reordered_headline(flags):
        headline = guard.analyze(rendered.headline_text).clean_text
        headline_source += "; as shown in a browser"
    if added_words:
        flags.append(Flag("script_generated_text", MEDIUM, None, None, " ".join(added_words), {}, "headline"))
    return headline, headline_source, flags


def _hidden_text_evidence(removed_text, suspicions):
    """The evidence for body text the browser hides: a static suspicion it confirms keeps its own
    cause and rule (the browser sees only that the text is not shown); otherwise script_or_overlay."""
    removed_words = set(_comparison_words(removed_text))
    for suspicion in suspicions:
        suspected_words = set(_comparison_words(suspicion.original))
        if suspected_words and len(removed_words & suspected_words) * 2 >= len(suspected_words):
            return dict(suspicion.evidence)
    return {"cause": "script_or_overlay"}


def _remove_hidden_runs(paragraphs, flags, suspicions=()):
    """(body, clipped paragraph count, removed passages): each paragraph without its hidden runs,
    one LOW flag appended per paragraph that lost text. suspicions: the static possibly_hidden_text
    flags this render settles."""
    kept_paragraphs = []
    removed_passages = []
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
        removed_passages.append(" ".join(removed_parts))
        # Low, as in the static reading: removed, so the model never sees it.
        removed_text = " … ".join(removed_parts)
        flags.append(Flag(
            "hidden_text_in_article", LOW, None, None, removed_text[:500],
            _hidden_text_evidence(removed_text, suspicions), "body",
        ))
        if remaining:
            kept_paragraphs.append(remaining)
    return "\n".join(kept_paragraphs).strip(), clipped_paragraphs, removed_passages


def compare_with_rendered_page(guard, article, rendered):
    """A new ArticleResult with the browser's findings merged in (see the module docstring)."""
    flags = []
    for flag in article.flags:
        flags.append(flag)
    if not rendered.complete:
        flags.append(Flag("browser_check_incomplete", LOW, None, None, rendered.note, {}, "page"))
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
    hidden_words = 0
    first_hidden = None
    for position, state in enumerate(all_states):
        if state == HIDDEN:
            hidden_words += 1
            if first_hidden is None:
                first_hidden = position
    shown_words = body_words - hidden_words
    if body_words >= INCONCLUSIVE_MINIMUM_WORDS and shown_words < INCONCLUSIVE_VISIBLE_SHARE * body_words:
        # Always medium: a consent wall looks like this, but so does a script that hides almost all
        # of the body, whose payload would otherwise pass in the static body that stands.
        flags.append(Flag(
            "browser_check_inconclusive", MEDIUM, None, None, rendered.note,
            {"words_shown": shown_words, "words_total": body_words}, "page",
        ))
        return replace(article, flags=flags, browser_milliseconds=rendered.milliseconds)

    # The render compares the whole body, so it settles text only suspected to be hidden: if the
    # browser hides it, it is removed below with a flag of its own; if it shows it, the guess is wrong.
    # Unless the browser skipped its color test there (a shadow, a gradient, an image behind it):
    # then showing the text proves nothing, and the suspicion stands.
    color_unchecked_words = set(_comparison_words(rendered.color_unchecked_text))
    kept_flags = []
    settled_suspicions = []
    for flag in flags:
        if flag.kind == "possibly_hidden_text" and color_unchecked_words.isdisjoint(_comparison_words(flag.original)):
            settled_suspicions.append(flag)
            continue
        kept_flags.append(flag)
    flags = kept_flags
    headline, headline_source, flags = _compare_headline(guard, article, rendered, flags)
    # The check settles the page only when it found the headline it was sent to confirm.
    headline_confirmed = rendered.headline_text is not None or not article.heading_text
    remaining_reasons = [] if headline_confirmed else list(article.browser_check_reasons)
    trailing_block = False
    if first_hidden is not None:
        hidden_after_first = 0
        for state in all_states[first_hidden:]:
            if state == HIDDEN:
                hidden_after_first += 1
        trailing_block = hidden_after_first >= TRAILING_BLOCK_HIDDEN_SHARE * (body_words - first_hidden)
    if body_words and hidden_words >= MOSTLY_HIDDEN_SHARE * body_words and trailing_block:
        # Set aside, as in the static reading: one MEDIUM flag instead of a LOW flag per passage.
        body, _, removed_passages = _remove_hidden_runs(paragraphs, [])
        set_aside = []
        if article.hidden_ending:
            set_aside.append(article.hidden_ending)
        for passage in removed_passages:
            set_aside.append(passage)
        flags.append(Flag("most_of_article_hidden", MEDIUM, None, None, "", {}, "body"))
        return replace(
            article, headline=headline, headline_source=headline_source, body=body,
            hidden_ending="\n".join(set_aside), flags=flags, browser_check_reasons=remaining_reasons,
            browser_verified=headline_confirmed, browser_milliseconds=rendered.milliseconds,
        )

    body, clipped_paragraphs, _ = _remove_hidden_runs(paragraphs, flags, settled_suspicions)
    if clipped_paragraphs:
        flags.append(Flag("text_behind_preview_window", LOW, None, None, "", {}, "body"))
    return replace(
        article, headline=headline, headline_source=headline_source, body=body, flags=flags,
        browser_check_reasons=remaining_reasons, browser_verified=headline_confirmed,
        browser_milliseconds=rendered.milliseconds,
    )


def verify_article_in_browser(guard, article, html, url, verifier):
    """Renders html as the page at url with a BrowserVerifier and merges what readers see."""
    full_heading_text = article.heading_full_text or article.heading_text
    rendered = verifier.render(url, html, article.headline_xpath, full_heading_text,
                               expected_words=len(article.body.split()))
    return compare_with_rendered_page(guard, article, rendered)
