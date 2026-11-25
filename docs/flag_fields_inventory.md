# Flag sentences, broken into fields (inventory for decisions)

Every `detail` sentence the code writes today, split three ways:

- **new field**: a fact about this one flag that no other field holds.
- **already elsewhere**: repeats `flagged_text`, `field`, `severity`, `headline_source`, `hidden_ending`,
  `browser_check` or the top-level `headline`/`body`.
- **category-wide**: true of every flag in the category ("HTML-based scrapers would pass it on"). It goes
  once into the category's description in docs/report_format.md, not into each flag.

Today every flag already has `category`, `severity`, `field`, `flagged_text`.

## Look-alike and invisible characters (any text: headline, body, a title)

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `watchlist_homoglyph` | looks like 'Alphabet' (GOOGL) but uses U+0410 CYRILLIC CAPITAL LETTER A, … | `looks_like`, `tickers`, `characters` | |
| `accented_watchlist_name` | looks like 'Tesla' (TSLA) with added marks: U+0301 … | `looks_like`, `tickers`, `characters` | |
| `possible_watchlist_lookalike` | native Cyrillic word that looks like 'META' (META) | `looks_like`, `tickers`, `script` | |
| `mixed_script_word` | Latin word containing U+0430 … | `script`, `characters` | |
| `whole_script_lookalike` | Cyrillic word that reads as 'pop' inside a Latin headline | `script`, `looks_like` | "inside a Latin headline": category-wide |
| `compatibility_lookalike` | U+1D413 MATHEMATICAL BOLD CAPITAL T folded to 'T' | `characters`, `looks_like` | |
| `hidden_tag_characters` | invisible Unicode tag characters that models read as 'sell' | `decoded_text` | "invisible tag characters": category-wide |
| `invisible_character` | U+200B ZERO WIDTH SPACE | `characters` | |
| `bidi_control` | U+202E RIGHT-TO-LEFT OVERRIDE | `characters` | |
| `excessive_combining_marks` | 12 stacked marks removed: U+0300 … | `characters` | the count is the length of `characters`; "removed": see action |
| any of the last five, inside a watched name | … (inside watched name 'Tesla') | `inside_name` | |
| any of these in a title | prefix "in the <title>: " | `found_in` (which title) | `field: metadata` says only "a title" |

## Hidden or added text in the headline

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `hidden_html_text` (static) | hidden text in the headline (font-size:0); a standard scraper would pass it on | `cause` | "in the headline": `field`; "scraper would pass it on": category-wide |
| `hidden_html_text` (browser) | in a browser the headline shows without these words (hidden by a script or an element drawn over them); HTML-based scrapers would pass them on | `found_by`, `cause` | "these words": `flagged_text`; scrapers: category-wide |
| `hidden_html_text` (browser, SVG) | in a browser too these headline words are not shown (SVG text placed outside its drawing) | `found_by`, `cause` | |
| `headline_adds_words` | the page's heading adds '…' to the og:title, and no other title has these words; they may be hidden … by a script or an overlay [; they are a label … (a kicker)]; the model gets the title's wording | `compared_with` (the title it was compared with; usually but not always the one in `headline_source`), `kicker` | added words: `flagged_text`; "script or overlay": category-wide; "model gets the title's wording": the top-level `headline` |
| `html_comment_text` | text inside an HTML comment in the headline | | all of it: category + `field` |
| `reordered_text` | unicode-bidi:bidi-override with direction:rtl; the model would read … in reverse | `cause` | the explanation: category-wide |
| `css_generated_text` | readers see this text in the headline, added by CSS …[; CSS may also add other text … under conditions not checked] | `conditions_unchecked` | the rest: category-wide |
| `embedded_font` | the headline is drawn with a font embedded in the page's CSS … | | the font name is `flagged_text`; the rest category-wide |
| `scraper_text_differs` (browser) | the browser shows headline words missing from the page's HTML (added by a script): '…' | `found_by`, `added_text` | |
| `headline_not_found_in_browser` | in a browser no heading on the page matches this headline … | `found_by` | the rest category-wide |

## Choosing the headline

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `headline_unconfirmed` | no metadata or feed title to confirm this <h1> is the headline | | all |
| `headline_from_metadata` | no visible heading matches …; using the json-ld headline, which is not checked for visibility | | the title used is `headline_source` |
| `headline_not_found` (analyze_html) | no element matches '//h1' | | the xpath is what the caller passed in |

## Comparing with your own scraper's text (analyze_html with scraped_text)

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `scraper_text_differs` | the scraper adds text a reader cannot see: '…'; the scraper drops visible text: '…' / differs at the character level | `added_text`, `dropped_text` | `flagged_text` is the whole scraped text |

## Body

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `hidden_text_in_article` (static) | hidden from readers (display:none); a standard extractor would pass it to the model; removed from the body | `cause` | "removed": see action; the rest category-wide |
| `hidden_text_in_article` (browser) | a browser hides this from readers (a script or an element drawn over it); removed from the body | `found_by`, `cause` | |
| `possibly_hidden_text` | may be invisible (text color #fff against an undeclared background); kept in the body until a browser check decides | `cause` | "kept until a browser decides": category-wide |
| `most_of_article_hidden` (static) | 3 passage(s) running to the end of the article … are hidden …; the hidden text is in hidden_ending | | the passages are the lines of `hidden_ending` |
| `most_of_article_hidden` (browser) | a browser hides the last 412 of the body's 530 words … | `found_by` | the counts follow from `body` and `hidden_ending` |
| `body_text_not_in_page_copy` | 2 passage(s) of the body are missing from the page's JSON-LD articleBody; usually subheadings or captions … | `compared_with` | the passages are `flagged_text` (joined by " / "); "usually subheadings": category-wide |
| `text_behind_preview_window` | 4 paragraph(s) are cut off by a preview window … kept in the body | `paragraph_count` | the rest category-wide |
| `article_body_not_found` | no article text was found on the page | | all |

## The page and the check

| category | example sentence today | new field | already elsewhere / category-wide |
|---|---|---|---|
| `page_too_complex_to_read` | (the reader's own message, e.g. nesting too deep) | `message` | |
| `browser_check_incomplete` | the page did not finish loading in the browser; the check used what had rendered | `found_by` | the browser's note is `flagged_text` |
| `browser_check_inconclusive` | the browser showed 0 of the body's 79 words (a consent wall …)[, and the reason for the check is unresolved] | `found_by`, `words_shown`, `words_total` | "reason unresolved": `browser_check.needed` |

## What that adds up to

New fields across all categories: `looks_like`, `tickers`, `characters`, `script`, `decoded_text`,
`inside_name`, `found_in`, `cause`, `found_by`, `compared_with`, `kicker`, `conditions_unchecked`,
`added_text`, `dropped_text`, `paragraph_count`, `words_shown`, `words_total`, `message`: 18. A single
flag uses 0 to 3 of them; 8 categories need none.

## Points to decide (one at a time)

1. `detail`: keep a short sentence built from the fields, or drop it.
2. A browser flag that confirms a static one (the two flags in the Microsoft example): merge into one
   flag, or keep both and link them.
3. `cause`: the exact CSS ("font-size:0"), a grouped name (`tiny_font`), or both.
4. `found_by` (static or browser): needed as a field, or implied by the category.
5. What the guard did with the text (removed, replaced, kept, set aside): a field (`action`), or left out
   because `headline`/`body` show it.
6. The new fields flat on the flag, or nested in one object.
7. The rarely useful ones: `script`, `kicker`, `conditions_unchecked`, `paragraph_count`.
