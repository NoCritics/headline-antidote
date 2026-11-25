# headline_guard report format

`ArticleResult.to_dict()` and `GuardResult.to_dict()` return the guard's results as plain JSON-ready
dicts. The schema is [headline_guard/report_schema.json](../headline_guard/report_schema.json)
(JSON Schema draft 2020-12).

## Versioning

`schema_version` is "major.minor"; `report_type` is `article` (from `extract_article`) or `text`
(from `analyze` or `analyze_html`).

- **Minor change:** a new field or evidence key, or a new `category` or `cause`.
- **Major change:** a renamed or removed field, or a new value of `verdict`, `severity` or `field`.
- Consumers ignore fields they don't know. For a category they don't know, they branch on `severity`.

## Article report

| field | type | meaning |
|---|---|---|
| `verdict` | pass, review, quarantine | quarantine if any flag is high, review if any is medium |
| `headline` | string | the headline a reader sees, cleaned |
| `headline_source` | string | where the headline came from, e.g. "<h1> matching the og:title" |
| `body` | string | the article text a reader sees, cleaned |
| `hidden_ending` | string | hidden text that is most of the article and runs to its end; never part of `body` |
| `tickers` | list of strings | watched tickers named in the result, each once |
| `metadata_titles` | object | the page's titles by name (`<title>`, `og:title`, ...) |
| `browser_check` | object | `needed`; `reasons` (sentences, emptied once a browser run settles the page); `ran` (the browser rendered the page); `verified` (it found and confirmed the headline, or there was no heading to confirm); `milliseconds` (null unless it ran) |
| `flags` | list | see below |

## Text report

| field | type | meaning |
|---|---|---|
| `verdict` | pass, review, quarantine | as above; the schema checks it against the flags |
| `text_as_written` | string | the text as given (for `analyze_html`, the visible text it read) |
| `text_cleaned` | string | the text to give the model |
| `tickers` | list of strings | watched tickers named in the text, each once |
| `flags` | list | see below |

## A flag

Every flag has the same four fields, plus `evidence`:

| field | meaning |
|---|---|
| `category` | what was found (open list; see Categories) |
| `severity` | high, medium or low |
| `field` | article reports: which output it affects, `headline`, `body`, `metadata` (a title not used as the headline) or `page`; text reports: null |
| `flagged_text` | the page text the flag is about; "" when it is not about a piece of text |
| `evidence` | the facts of this one finding that no other field holds, by category; `{}` when there are none |
| `start`, `end` | text reports only: code-point offsets into `text_as_written` (`end` exclusive), or null for flags without a position (hidden HTML text, scraper differences) |

There is no sentence per flag: what a category means, why it matters and what the guard does with the
text are the same for every flag of that category, so they are written once, below. Evidence keys that
don't apply are left out, never null.

Offsets count Unicode code points. JavaScript strings count UTF-16 units, which differ for characters
outside the Basic Multilingual Plane, such as the tag characters the guard catches.

When a browser check confirms a suspicion of the static reading, the browser's flag replaces it: one
finding, one flag, at the browser's severity (`headline_adds_words` becomes `hidden_html_text`,
`possibly_hidden_text` becomes `hidden_text_in_article`). When the browser shows the suspected text, the
suspicion is removed.

## Evidence keys

| key | type | meaning |
|---|---|---|
| `looks_like` | string | the text a reader takes it for: the watched name, or the letters it reads as |
| `tickers` | list of strings | the watched tickers of the name it imitates or sits inside |
| `characters` | list of `{code_point, name}` | the characters at issue, e.g. `{"code_point": "U+0410", "name": "CYRILLIC CAPITAL LETTER A"}` |
| `decoded_text` | string | what invisible tag characters spell out to a model |
| `inside_name` | string | the watched name an invisible or look-alike character sits inside (which is why it is high) |
| `found_in` | string | which title a `metadata` flag was found in (`og:title`, `<title>`, ...) |
| `cause` | string | how text is hidden (see Causes) |
| `css` | string | the exact rule that hides or reorders it, e.g. `font-size:0`, `left:-9999px`, `unicode-bidi:bidi-override` |
| `compared_with` | string | the reference the text was compared with: a title (`og:title`, `feed title`, ...) or the article copy (`feed article text`, `JSON-LD articleBody`) |
| `kicker` | boolean | true when the added words are a label in their own element before the headline ("Exclusive:"), which is why the flag is low |
| `added_text`, `dropped_text` | string | the words your scraper adds to, or drops from, what a reader sees |
| `words_shown`, `words_total` | integer | how many of the body's words the browser showed, of how many |
| `message` | string | the reader's own explanation of why the page was too complex to read |

## Categories

What each one means, its evidence, and what the guard does with the text. Square brackets mark evidence
that appears only in some flags of the category.

### Look-alike and invisible characters (any text: headline, body, a title)

| category | severity | evidence | meaning; what the guard does |
|---|---|---|---|
| `watchlist_homoglyph` | high | `looks_like`, `tickers`, `characters` | a watched name spelled with look-alike letters: from another script, or ASCII ones such as I for l (then `characters` lists the ASCII stand-ins); replaced by the real name |
| `accented_watchlist_name` | medium | `looks_like`, `tickers`, `characters` | a watched name with accents added; replaced by the real name |
| `possible_watchlist_lookalike` | low | `looks_like`, `tickers` | a native word of another script that resembles a watched name (Russian "МЕТА"); kept |
| `mixed_script_word` | high, medium | `characters` | a word mixing scripts; in a Latin word, letters with a Latin look-alike are replaced, otherwise kept |
| `whole_script_lookalike` | medium | `looks_like` | a word of another script made only of Latin look-alikes, among Latin words; replaced by what it reads as |
| `compatibility_lookalike` | low, medium; high inside a watched name | `characters`, `looks_like`, [`inside_name`, `tickers`] | styled letters (math bold, full-width) that a model may read differently; replaced by plain letters |
| `hidden_tag_characters` | high | `decoded_text` | invisible Unicode tag characters: a model reads them as text, a reader sees nothing; removed |
| `invisible_character` | low, medium; high inside a watched name | `characters`, [`inside_name`, `tickers`] | a zero-width or other invisible character, which can split a name; removed |
| `bidi_control` | medium; high inside a watched name | `characters`, [`inside_name`, `tickers`] | a text-direction control, which can make the shown order differ from the read order; removed |
| `excessive_combining_marks` | medium; high inside a watched name | `characters`, [`inside_name`, `tickers`] | marks stacked far beyond any language's use; removed |

A `metadata` flag of any of these also has `found_in`. Each category's severities are the ones listed;
the schema rejects others.

### Hidden or added text in the headline

| category | severity | evidence | meaning; what the guard does |
|---|---|---|---|
| `hidden_html_text` | high; medium when hiding depends on a guess (an undeclared background, SVG paint) | `cause`, [`css`] | text readers can't see that HTML scrapers pass to the model; removed |
| `headline_adds_words` | medium; low for a kicker or one ordinary word | `compared_with`, [`kicker`] | the heading has words no title has, which a script or an overlay may hide; removed when medium or a kicker, kept when one ordinary word, until a browser check settles it |
| `script_generated_text` | medium | | words a browser shows in the headline that the page's HTML doesn't contain (added by a script): readers see them, the model never does; not added to the headline |
| `css_generated_text` | medium | | text CSS may add to the headline (::before/::after; some of it under @supports, @container or @scope conditions that are not checked): readers may see it, the model never does; not added to the headline |
| `html_comment_text` | medium | | text inside an HTML comment, which some scrapers pass on; never in the headline |
| `reordered_text` | high; medium in the body | `css` | text shown to readers in reverse order, so the model and the reader read different words; kept |
| `embedded_font` | medium | | the headline is drawn with a font embedded in the page (`flagged_text` is its name), which can draw other letters than the text holds; kept |
| `headline_not_found_in_browser` | high | | in a browser no heading matches the headline: a script removed or replaced it |

### Choosing the headline

| category | severity | evidence | meaning |
|---|---|---|---|
| `headline_unconfirmed` | low | | the page has no title to confirm the `<h1>` is the headline |
| `headline_from_metadata` | low | | no visible heading matches the titles; the headline is the title named in `headline_source`, which is not checked for visibility |
| `headline_not_found` | medium | | (`analyze_html`) no element matches the headline_xpath you passed |

### Comparing with your own scraper's text (`analyze_html` with `scraped_text`)

| category | severity | evidence | meaning |
|---|---|---|---|
| `scraper_text_differs` | high, medium | [`added_text`], [`dropped_text`] | your scraper's text (`flagged_text`) differs from what a reader sees; with neither key, the words are the same but some characters differ |

### Body

| category | severity | evidence | meaning; what the guard does |
|---|---|---|---|
| `hidden_text_in_article` | low | `cause`, [`css`] | body text readers can't see that a standard extractor would pass on; low because most of it is harmless (screen-reader labels, menus); removed |
| `possibly_hidden_text` | low | `cause`, `css` | body text whose color may match a page background the page doesn't declare; kept until a browser check decides |
| `most_of_article_hidden` | medium | | hidden text running to the end of the body is most of the article: usually a "Read more" collapse or a paywall, but it could be a hidden ending; set aside in `hidden_ending` |
| `body_text_not_in_page_copy` | low | `compared_with` | passages of the body (`flagged_text`, joined by " / ") missing from the article copy; usually subheadings or captions, but text hidden by a script looks the same; kept |
| `text_behind_preview_window` | low | | a browser shows body paragraphs cut off by a preview window (a metered paywall or a collapsed section); the publisher's text, kept |
| `article_body_not_found` | low | | no article text was found on the page |

### The page and the check

| category | severity | evidence | meaning |
|---|---|---|---|
| `page_too_complex_to_read` | medium | `message` | the page was not read |
| `browser_check_incomplete` | low | | the page did not finish loading in the browser (`flagged_text` is the browser's note); the check used what had rendered |
| `browser_check_inconclusive` | medium | `words_shown`, `words_total` | the browser showed too few of the body's words to conclude (a consent wall, a redirect, a script hiding the body); the static result stands |

## Causes

| cause | what it covers |
|---|---|
| `display_none` | display:none |
| `content_visibility_hidden` | content-visibility:hidden |
| `visibility_hidden` | visibility:hidden or collapse |
| `transparent` | near-zero opacity, filter:opacity(), a transparent text color |
| `blurred` | filter:blur() too strong to read |
| `tiny_font` | font-size, or the font shorthand, too small to read |
| `letters_stacked` | letter-spacing that draws the letters on top of each other |
| `same_color_as_background` | a text color nearly matching its background |
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
| `svg_off_drawing` | SVG text placed outside its drawing |
| `css_not_evaluated` | CSS this reader cannot evaluate, so hiding can't be ruled out |
| `script_or_overlay` | found by a browser, which sees only that the text is not shown: a script or an element drawn over it |

Hiding by an enclosing element gets that element's cause. `css` is absent when the cause is not a CSS rule
(`hidden_attribute`, `not_rendered_element`, `script_or_overlay`, ...).

## Strings from the page are untrusted

`flagged_text`, the evidence strings, the titles, `hidden_ending` and the texts come from a page an
attacker may control. Give the model only `headline` and `body` (or `text_cleaned`), after checking
`verdict`. Never pass the report to an LLM as instructions, and escape its strings when displaying them.
