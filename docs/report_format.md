# headline_guard report format (draft for review)

The JSON report that `ArticleResult.to_dict()` and `GuardResult.to_dict()` will return. The schema is
[headline_guard/report_schema.json](../headline_guard/report_schema.json). Nothing is built yet.

## Versioning

`schema_version` is "major.minor", and `report_type` is `article` or `text`.

- **Minor change:** a new field, or a new value of `category`, `cause` or browser `reason`.
- **Major change:** a renamed or removed field, or a new value of a closed list: `verdict`, `severity`,
  `certain`, `field`, `found_by`, `action`, `report_type`, `browser_check.outcome`.
- Every other list of values is open (`x-known-values` in the schema): `category`, `cause`, browser
  `reason`, `difference`, `cleared_category`, `headline_source.browser`, `found_in`.
- **Consumers ignore fields they don't know.** For a category they don't know, they branch on `severity`
  and `action`, which never take new values within a major version.
- **Open lists:** the schema lists the values each release produces under `x-known-values`. It doesn't
  reject new ones.

## A flag: core and evidence

Every flag has the same core, the fields consumers branch on without knowing the category:

| field | always | meaning |
|---|---|---|
| `id` | yes | unique within one report, for `confirms` links |
| `category` | yes | what was found (open list) |
| `severity` | yes | how bad: high, medium, low |
| `certain` | yes | confirmed (true) or suspected (false) |
| `field` | yes | which part of the result it affects |
| `found_by` | yes | static or browser |
| `action` | yes | removed, replaced, set_aside, none |
| `detail` | yes | the sentence for people |
| `evidence` | yes | category-specific facts; `{}` when there are none |
| `found_in` | no | where on the page; absent for whole-page flags and in text reports |
| `flagged_text` | no | the page text it is about; absent when it is not about a piece of text |
| `tickers` | no | the watched tickers of the name it imitates or sits inside (routing) |
| `confirms` | no | the id of the flag this one confirms |
| `truncated` | no | true when `flagged_text` or an evidence string was cut at 500 code points |

Text reports add `start` and `end`. Everything else lives in `evidence`, listed per category below. The
schema requires each known category's evidence, and lets unknown categories through with any evidence.

## No value: null or absent

- Text fields are empty strings when there is no text: `headline_as_written`, `headline_cleaned`,
  `body_cleaned`, `hidden_ending`, `text_as_written`, `text_cleaned`. An empty text is still a text.
- Other keys every report or flag always has use `null` for "no value": the top-level keys, `browser_check`,
  `headline_source`, and the flag keys `id`, `category`, `severity`, `certain`, `field`, `found_by`,
  `action`, `detail` (`field` is `null` in a text report).
- `evidence` is always present, `{}` when a category has nothing extra.
- Optional flag fields, in the core or in `evidence`, are left out when they do not apply, never `null`. So `"css" in flag` and
  `flag.get("css")` always agree.

## `field` and `found_in`

- `field` is which part of the result the flag affects: `headline`, `body`, `metadata` (a title not used
  as the headline) or `page` (the page as a whole).
- `found_in` is where on the page the flagged text sits: a tag name (any element, since a `headline_xpath`
  may point at a `<div>`), a title's name, or `body`. It is absent for whole-page flags.

Example: with no usable heading the headline is taken from the og:title, which has a homoglyph:
`"field": "headline", "found_in": "og:title"`. The same homoglyph in an og:title that is not the headline:
`"field": "metadata", "found_in": "og:title"`.

## Untrusted strings

An attacker controls the page, so every string the report takes from it is attacker-controlled:
`flagged_text`, `looks_like`, `decoded_text`, `css`, `font_family`, `titles`, `target`, `added_text`,
`dropped_text`, `headline_as_written`, the cleaned texts, and `detail`, which quotes them.

What the guard does:

- **`detail` is safe to log and display.** Page text it quotes has invisible and control characters
  written as visible escapes: line breaks, terminal escape codes, text-direction overrides, tag characters
  (`'Tesla\u202e…'`, not the live character). `flagged_text` stays raw, because it is the evidence.
- **Page strings are capped at 500 code points**, with `"truncated": true` on the flag: `flagged_text`, and in
  `evidence` `css`, `looks_like`, `decoded_text`, `font_family` and each `added_text`/`dropped_text` run;
  also each browser reason's `target` and each title.
- **`headline_as_written` is capped at 2,000 code points**, with `headline_as_written_truncated: true`. The
  cleaned headline and body are not capped: they are the product.

What consumers must do:

- Give the model only `headline_cleaned` and `body_cleaned` (or `text_cleaned`), after checking `verdict`.
- Never feed the report, or any sentence in it, to an LLM as instructions.
- Treat every quoted string as data: escape it when displaying, and never use it in a shell command, a
  file path or a query.

## Rules for `detail`

Each flag's `detail` is one sentence for people, built only from the flag's fields, `evidence` included:

1. It names the flagged text and where it was found.
2. It says "possibly" exactly when `certain` is false: the guard suspects the finding but has not
   confirmed it.
3. It states the finding only. What the guard did goes in `action`, and why a category matters goes in
   the category notes below.
4. It stands alone: no "these words", "either", or reference to another flag.
5. Page text it quotes is escaped (see Untrusted strings).

In the templates, field names refer to the core or to `evidence` alike:

- `{where}` is `found_in` in plain words: "the <h1>", "the <h2>", "the og:title", "the body". In a text
  report, which has no `found_in`, it is "the text".
- `{compared_with}` is the list in plain words: "the og:title", "the og:title and the <title>", "the
  og:title, the <title> and the feed title".
- `{text}` is `flagged_text`.
- Square brackets mark a part that appears only when the named field is set.

## `certain`

Every flag has `certain: true` or `certain: false`. Severity says how bad a finding is; `certain` says
whether the guard has confirmed it. These flags can be `certain: false`:

- `headline_adds_words` and `body_text_not_in_page_copy`: words or passages missing from a reference,
  which a script may hide.
- `hidden_html_text` and `hidden_text_in_article` found statically when the reader had to guess: a text
  color against an undeclared (assumed white) page background, SVG paint that may not show, SVG text
  placed off its drawing, or CSS it cannot evaluate.
- `possible_watchlist_lookalike`: a native word that only resembles a watched name.

Every other flag is `certain: true`. A browser flag that confirms a static suspicion is `certain: true`.

## A suspicion the browser clears

When a browser shows text a static suspicion was about, that flag becomes a `suspicion_cleared` flag:
`cleared_category` holds the suspicion's category, with `severity: "low"`, `certain: true`,
`action: "none"` and `found_by: "browser"`. Its sentence states what the browser saw, e.g. "in a browser
{where} shows the extra words '{text}', which no title has". Rules matching the suspicion's category never
fire on it, and the verdict needs no special case.

## Flag categories

### Look-alike and invisible characters (static; any field)

| category | severity | extra fields | action | detail template |
|---|---|---|---|---|
| `watchlist_homoglyph` | high | `looks_like`, `tickers`, `characters` | replaced | '{text}' in {where} looks like '{looks_like}' ({tickers}) but uses {characters} |
| `accented_watchlist_name` | medium | `looks_like`, `tickers`, `characters` | replaced | '{text}' in {where} looks like '{looks_like}' ({tickers}) with added marks: {characters} |
| `possible_watchlist_lookalike` | low, `certain: false` | `looks_like`, `tickers`, `script` | none | '{text}' in {where} is a native {script} word, possibly imitating '{looks_like}' ({tickers}) |
| `mixed_script_word` | high or medium | `script`, `characters` | replaced (Latin words) or none | '{text}' in {where} is a {script} word containing {characters} |
| `whole_script_lookalike` | medium | `script`, `looks_like` | replaced | '{text}' in {where} is a {script} word among Latin words that reads as '{looks_like}' |
| `compatibility_lookalike` | low, medium; high inside a watched name | `looks_like`, `characters`, [`watched_name`, `tickers`] | replaced | '{text}' in {where} uses {characters}, which read as '{looks_like}' [inside the watched name '{watched_name}'] |
| `hidden_tag_characters` | high | `decoded_text`, `characters` | removed | {where} holds invisible Unicode tag characters that a model reads as '{decoded_text}' |
| `invisible_character` | low, medium; high inside a watched name | `characters`, [`watched_name`, `tickers`] | removed | {where} holds the invisible character {characters} [inside the watched name '{watched_name}'] |
| `bidi_control` | medium; high inside a watched name | `characters`, [`watched_name`, `tickers`] | removed | {where} holds the text-direction control {characters} [inside the watched name '{watched_name}'] |
| `excessive_combining_marks` | medium; high inside a watched name | `characters`, `mark_count`, [`watched_name`, `tickers`] | removed | '{text}' in {where} carries {mark_count} stacked marks: {characters} |

`{characters}` is written as "U+0410 CYRILLIC CAPITAL LETTER A, U+0435 CYRILLIC SMALL LETTER IE".
In JSON each one is `{"code_point": "U+0410", "name": "CYRILLIC CAPITAL LETTER A"}`.

### Hidden or added text in the headline

| category | severity | found_by | extra fields | action | detail template |
|---|---|---|---|---|---|
| `hidden_html_text` | high; medium when `certain` is false | static | `cause`, `css`, [`on_enclosing_element`] | removed | {where} has text a reader cannot see: '{text}', hidden by {css or cause} [on an enclosing element]. Uncertain: {where} has '{text}', possibly hidden by {css or cause} |
| `hidden_html_text` | high | browser | `cause: not_shown_in_browser`, `confirms` | removed | in a browser {where} shows without the extra words '{text}'; they are hidden by a script or an element drawn over them |
| `hidden_html_text` | high | browser | `cause: svg_off_drawing`, `confirms` | removed | in a browser {where} does not show '{text}', SVG text placed outside its drawing |
| `headline_adds_words` | medium (low for a kicker or a single plain word) | static | `compared_with`, [`kicker`] | removed (medium) or none (low) | compared with the {compared_with}, {where} has extra words: '{text}'; possibly hidden by a script or an overlay [; they are a label in their own element before the headline] |
| `script_generated_text` | medium | browser | | none | in a browser {where} shows '{text}', which the page's HTML does not contain |
| `css_generated_text` | medium | static | [`conditions_unchecked`] | none | readers see '{text}' in {where}, added by CSS (::before/::after); the page's HTML does not contain it [; CSS may add other text here under conditions that were not checked] |
| `html_comment_text` | medium | static | | none (never in the headline) | {where} has text inside an HTML comment: '{text}' |
| `reordered_text` | high | static | `css` | none | '{text}' in {where} is shown to readers in reverse order ({css}) |
| `embedded_font` | medium | static | `font_family` | none | {where} is drawn with '{font_family}', a font embedded in the page's CSS |
| `headline_not_found_in_browser` | high | browser | | none | in a browser no heading on the page matches {where} '{text}' |

### Choosing the headline

| category | severity | extra fields | action | detail template |
|---|---|---|---|---|
| `headline_unconfirmed` | low | | none | the page has no title to compare {where} '{text}' with |
| `headline_from_metadata` | low | `found_in` (the title used) | none | no visible heading matches the page's titles; the headline is the text of the {found_in}, which is not checked for visibility |
| `headline_not_found` | medium | `xpath` | none | no element matches the headline_xpath '{xpath}' |

### Comparing with your own scraper's text

`scraped_text_differs` appears only when you pass `scraped_text` to `analyze_html`. `extract_article`
never produces it.

| category | severity | extra fields | action | detail template |
|---|---|---|---|---|
| `scraped_text_differs` | high, medium | `difference`, `added_text`, `dropped_text` | none | compared with the visible text, the scraped text adds '{added_text}' / drops '{dropped_text}' / adds '…' and drops '…' / has the same words in different characters (`difference`: added, dropped, added_and_dropped, same_words) |

`added_text` and `dropped_text` are lists of runs, written in the sentence as 'run one' / 'run two'.

### Body

| category | severity | found_by | extra fields | action | detail template |
|---|---|---|---|---|---|
| `hidden_text_in_article` | low | static | `cause`, `css`, [`on_enclosing_element`] | removed | the body has text a reader cannot see: '{text}', hidden by {css or cause} [on an enclosing element] |
| `hidden_text_in_article` | low | browser | `cause: not_shown_in_browser` | removed | in a browser the body does not show '{text}'; it is hidden by a script or an element drawn over it |
| `hidden_text_in_article` | low | static, `certain: false` | `cause: same_color_as_background`, `css` | none (kept until a browser check decides) | the body has '{text}' in {css}, possibly invisible on the page's background, which the page does not declare |
| `most_of_article_hidden` | medium | static | `passage_count` | set_aside | {passage_count} passages running to the end of the body, most of the article, are hidden from readers |
| `most_of_article_hidden` | medium | browser | `words_shown`, `words_total` | set_aside | in a browser only the first {words_shown} of the body's {words_total} words are shown to readers |
| `body_text_not_in_page_copy` | low | static | `compared_with`, `passage_count` | none | {passage_count} passages of the body are not in the {compared_with}: '{text}'; possibly hidden by a script |
| `text_behind_preview_window` | low | browser | `paragraph_count` | none | in a browser {paragraph_count} paragraphs of the body are cut off by a preview window |
| `article_body_not_found` | medium (raised from low: an empty body must not pass) | static | | none | no article text was found on the page |

### The page and the check itself

| category | severity | found_by | extra fields | action | detail template |
|---|---|---|---|---|---|
| `page_too_complex_to_read` | medium | static | `reader_message` | none | the page was not read: {reader_message} |
| `browser_check_incomplete` | low | browser | | none | the page did not finish loading in the browser |
| `browser_check_inconclusive` | medium | browser | `words_shown`, `words_total` | none | the browser showed {words_shown} of the body's {words_total} words, too few to conclude |

`reader_message` is the one free-text field: the reader's own explanation of why the page was too
complex. It is not to be parsed.

### Category notes (what used to be repeated in every sentence)

- **Hidden text** (`hidden_html_text`, `hidden_text_in_article`, `html_comment_text`): HTML-based scrapers
  pass it to the model although readers never see it.
- **`hidden_text_in_article`** is low because most hidden body text is harmless (screen-reader labels,
  menus). It is removed from the body either way.
- **`reordered_text`:** the model reads the letters in the page's order and the reader in reverse, so the
  two read different words.
- **`embedded_font`:** an embedded font can draw letters other than the ones the text contains.
- **`script_generated_text`:** the opposite risk to hidden text. Readers see words the model never gets.
- **`body_text_not_in_page_copy`:** usually subheadings or captions, but text hidden by a script would
  look the same.
- **`headline_not_found_in_browser`:** usually a script that removed or replaced the heading.
- **`browser_check_incomplete`:** the check used whatever had rendered.
- **`most_of_article_hidden`:** usually a "Read more" collapse or a paywall, but it could be a hidden ending.
- **`text_behind_preview_window`:** the publisher's own text behind a metered paywall or a collapsed
  section. It is kept.

## `cause`: how text was hidden

The reader recognises 48 hiding methods, grouped into these values. `css` keeps the exact rule. Comments
and reversed text carry no `cause`, because their category already says it.

| cause | what it covers |
|---|---|
| `display_none` | display:none |
| `content_visibility_hidden` | content-visibility:hidden |
| `visibility_hidden` | visibility:hidden or collapse |
| `transparent` | near-zero opacity, filter:opacity(), a transparent text color |
| `blurred` | filter:blur() too strong to read |
| `tiny_font` | font-size, or the font shorthand, too small to read |
| `letters_stacked` | letter-spacing that draws the letters on top of each other |
| `same_color_as_background` | a text color nearly matching its background (`css` holds the color) |
| `clipped` | clip:rect(0 0 0 0), clip-path, a tiny box or collapsed line-height with overflow:hidden |
| `scaled_to_zero` | transform:scale(0), scale:0 |
| `off_screen` | positioned or translated off-screen, or text-indent off-screen |
| `screen_reader_only` | the "visually hidden" accessibility pattern (a 1px clipped box) |
| `covered` | an opaque overlay, or its own ::before/::after, drawn over it |
| `behind_background` | a negative z-index under an opaque background |
| `closed_details` | inside a closed `<details>` |
| `not_rendered_element` | inside `<template>`, `<noscript>`, `<datalist>` or `<title>` |
| `hidden_attribute` | the HTML `hidden` attribute |
| `hidden_input` | `<input type=hidden>` |
| `svg_not_drawn` | SVG that draws no text: tooltips, definitions, unchosen `<switch>` children, failing conditions, a zero-size `<svg>` or `<foreignObject>` |
| `svg_not_painted` | SVG text with no visible fill or stroke, or a fill matching the background |
| `svg_off_drawing` | SVG text placed outside its drawing (from the static reading or the browser) |
| `unknown` | the method is not known: CSS this reader cannot evaluate, so hiding cannot be ruled out (always with `certain: false`; the sentence says "possibly hidden by CSS this reader cannot evaluate") |
| `not_shown_in_browser` | found by a browser, which sees only that the text is not shown |

"An enclosing element is hidden" becomes the inner cause plus `on_enclosing_element: true`.

## `browser_check.needed` and `ran`

- `needed` is true while a browser check is still outstanding: there are reasons, and no conclusive run has
  settled them. After a conclusive run it is false, although `reasons` are kept as a record. (A pipeline
  that retries pages while `needed` is true must not loop on checked pages.)
- When `ran` is false, `milliseconds` and both parts of `outcome` are null.

## `browser_check.outcome`

The browser renders the page once and compares two parts with the static reading, so the outcome is per
part: `{"headline": ..., "body": ...}`. Each part is one of:

- `differs`: the browser shows different text (hidden words, script-added words, a replaced heading); the
  flags say what.
- `matches`: the same text, so suspicions on that part are cleared.
- `inconclusive`: too little was shown to compare (a consent wall, a redirect).
- `null`: that part was not compared, or the check did not run.

## `browser_check.reasons[].reason`

Where a reason means the same as a flag category, it uses the same string. Each reason carries no
sentence of its own: `flag` links to the flag's `detail`, and `target` is shown as is.

| reason | when | target |
|---|---|---|
| `svg_off_drawing` | headline SVG text placed outside its drawing | |
| `headline_adds_words` | {where} has words no title has | the title compared with |
| `embedded_font` | the headline uses a font embedded in the page | |
| `script_in_headline` | a `<script>` inside the headline | |
| `event_handler_in_headline` | an `on...` attribute inside the headline | |
| `script_changes_headline` | an inline script finds an id or class used in the headline and changes it | the id or class |
| `script_changes_headline_tag` | an inline script finds the heading by its tag and changes it | the tag |
| `script_changes_body` | an inline script finds an element holding article text and changes it | the id or class |
| `body_text_not_in_page_copy` | body passages missing from the feed's or JSON-LD article text | the reference |
| `hidden_text_in_article` | body text whose color may match an undeclared page background | |
| `page_too_complex_to_read` | the page was too complex to read statically | |

## Tickers

The report's top-level `tickers` are the watched tickers named in the **cleaned** text
(`headline_cleaned` and `body_cleaned`, or `text_cleaned`), never in removed text: hidden words naming
AAPL must not route a story to AAPL.

A watched name may map to several tickers (Alphabet: GOOGL, GOOG). Flags carry `tickers`, a list, and
the sentence writes them comma-separated: "looks like 'Alphabet' (GOOGL, GOOG)".

## Offsets

`start` and `end` appear only in text reports, always together. They are offsets into `text_as_written`,
in Unicode code points, and `end` is exclusive.
JavaScript strings count UTF-16 units, which differ for characters outside the Basic Multilingual Plane,
such as the tag characters this guard catches.

## Changes from today's behaviour that the report needs

1. `browser_check_reasons` are emptied after a successful browser run (browser_check.py:301). The report
   keeps them.
2. The browser check's "headline words missing from the page's HTML" leaves `scraper_text_differs` for
   the new `script_generated_text`, and `scraper_text_differs` is renamed `scraped_text_differs`.
3. A suspicion the browser clears is kept as a low flag (today it is deleted, browser_check.py:162-174 and
   197-208).
4. `possibly_hidden_text` becomes `hidden_text_in_article` with `certain: false`.
5. A name listed under several tickers maps to all of them. Today only the first ticker registered is
   kept (text_guard.py:217-222), so GOOG is never reported when GOOGL also lists "Alphabet".
6. `needs_browser_check` means "still outstanding", not "has reasons": today it is
   `bool(browser_check_reasons)` (article.py:139), which would stay true once reasons are kept.
7. Values the report promises that the code loses today (Codex, from the code):
   - a low kicker in `headline_adds_words` can still be removed from the headline (article.py:574), so
     its `action` must be computed, not assumed;
   - `clip-path` evidence keeps only the property name (html_visibility.py:189), not its value;
   - scraper differences are joined into one run (text_guard.py:435) instead of kept as runs;
   - top-level tickers can survive the removal of their only mention by the browser check
     (browser_check.py:338); they must be recomputed from the cleaned text.
8. `article_body_not_found` is raised from low to medium (article.py:911), so a page with no article
   text gets `review`, not `pass`.
9. Offsets appear only in text reports. In an article they point into the static reading's text, which is
   neither `headline_as_written` nor `headline_cleaned`.
