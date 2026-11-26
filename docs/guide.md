# Guide

## Where to call it

Call it next to the scraper, on the same HTML the scraper parsed. After `get_text()`, hidden words are ordinary words, and nothing later in the pipeline can tell. On 22 test pages with 17 attacks, the check after the scraper missed 9 to 13 attacks per extractor; next to it, 0 to 2 ([scraper_comparison/results.md](../scraper_comparison/results.md)).

Entry points:

- `extract_article(html, feed_title=None, stylesheets=None, feed_body=None)`: the headline and body as the model should get them. Use this one when you can.
- `analyze_html(html, headline_xpath, scraped_text=None)`: when your scraper picks the element itself. Pass its output as `scraped_text`. Words it adds that readers can't see are `high`; visible words it drops are `medium`.
- `analyze(text)`: plain text, such as feed titles.

With a browser scraper, read the text with `browser_visibility.rendered_visible_text(locator)` and pass `rendered_by_browser=True` to `analyze_html`. The browser's view is then taken as the truth.

`PAPER_WATCHLIST` holds the companies used in the paper.

## External stylesheets

The library never fetches anything. Fetch a site's stylesheets once and pass their text:

```python
from headline_antidote.html_visibility import linked_stylesheet_urls

urls = linked_stylesheet_urls(page_html, page_url)
guard.prepare_stylesheets([css_1, css_2])   # optional: compile now instead of on the first article
article = guard.extract_article(page_html, stylesheets=[css_1, css_2])
```

- Compiling a big site's CSS takes 0.5 to 3 s. It's cached after that, up to about 450 MB in total.
- Call `prepare_stylesheets` from the thread that calls `extract_article`, with the same list in the same order.

## The browser check

`article.needs_browser_check` is set when the static read can't rule something out, and `article.browser_check_reasons` says what. The reasons are:

- the heading has words the titles lack;
- an inline script changes the headline;
- the body has passages missing from the page's JSON-LD copy.

`BrowserVerifier` keeps one headless Chrome running:

- It serves the HTML you already fetched at the page's real URL, so Chrome checks what the scraper saw.
- Images, media and fonts are blocked.
- Scripts and stylesheets load from any site. `same_site_only=True` is faster, but misses hiding done by third-party scripts.
- A check takes about 1.1 to 1.3 s per page (median), mostly the page's own scripts.

After the check:

- headline words the browser hides are `high`, and the model gets the browser's headline;
- headline words the static read doubted but the browser shows come back;
- body text the browser hides is removed and flagged `low`.

## Text set aside

Hidden text that is most of the article, running as one block to its end ("Read more" collapses, paywalls), goes to `article.hidden_ending`, not `body`, with a `most_of_article_hidden` flag (medium). An attacker's long hidden ending looks the same, so append it only for publishers you trust.

## Pipeline settings

Compiled CSS creates millions of objects, and Python's default garbage collection keeps scanning them. In a 228-page run, `gc.set_threshold(10000, 10, 10)` at the start of the pipeline cut full collections from 22.8 s to 5.1 s. The library leaves this setting alone, because it applies to the whole process.

## Flags

| Flag | Severity | Example |
|---|---|---|
| `watchlist_homoglyph` | high | "Теsla", "$ТSLA", "TesIa" (capital I for l) |
| `hidden_tag_characters` | high | invisible U+E00xx characters that models read as ASCII |
| `hidden_html_text` | high / medium | text hidden by CSS or HTML (medium: near-white text with no declared background) |
| `mixed_script_word` | high | "ѕurge" (Cyrillic ѕ in a Latin word) |
| `reordered_text` | high / medium | letters shown in reverse (`<bdo dir="rtl">`, `unicode-bidi: bidi-override`) |
| `headline_not_found_in_browser` | high | no heading in the browser matches the static headline |
| `scraper_text_differs` | high / medium | the scraper added words readers can't see (high) or dropped visible ones (medium) |
| `whole_script_lookalike` | medium | "ТОР" written in Cyrillic inside an English headline |
| `accented_watchlist_name` | medium | "Tésla" |
| `compatibility_lookalike` | medium | math bold "𝐍𝐕𝐈𝐃𝐈𝐀", full-width "Ｔｅｓｌａ" outside CJK text |
| `invisible_character` | medium / low | zero-width characters inside a word (medium) or between words (low) |
| `bidi_control` | medium | direction overrides with no right-to-left text |
| `excessive_combining_marks` | medium | more than two marks on one letter |
| `html_comment_text` | medium | text in `<!-- -->`, which some scrapers keep |
| `script_generated_text` | medium | headline words a script adds, which the model never gets |
| `css_generated_text` | medium | headline words `::before` or `::after` adds |
| `embedded_font` | medium | the headline is drawn with a font embedded as a `data:` URI |
| `most_of_article_hidden` | medium | most of the body is hidden as one block at its end |
| `browser_check_inconclusive` | medium | the browser showed almost none of the article |
| `page_too_complex_to_read` | medium | over 20,000 `<`, or nesting near Chrome's depth limit; left to the browser check |
| `headline_not_found` | medium | `headline_xpath` matched nothing |
| `headline_adds_words` | medium / low | the heading has words no title has; the model gets the title's wording |
| `hidden_text_in_article` | low | hidden body text, removed |
| `possibly_hidden_text` | low | body text that may match an unknown background; kept, sent to the browser check |
| `body_text_not_in_page_copy` | low | body passages missing from the page's JSON-LD copy |
| `text_behind_preview_window` | low | text cut off by a paywall preview; kept |
| `browser_check_incomplete` | low | the page didn't finish loading in the browser |
| `headline_from_metadata` | low | no visible heading matches; the metadata headline is used |
| `headline_unconfirmed` | low | no title to confirm the chosen `<h1>` |
| `article_body_not_found` | low | no article text found |
| `possible_watchlist_lookalike` | low | "МЕТА" in a Cyrillic headline, where it's a real word |

Invisible characters, compatibility forms and combining marks inside a watched name are raised to high. Hidden body text is only `low` because it's removed, and real articles hide text of their own all the time.

## Real language

- Zero-width joiners are allowed in Arabic, Persian, Indic scripts and emoji. Tag characters are allowed only in the England, Scotland and Wales flags.
- Bidi marks are allowed when the headline has right-to-left text. Full-width forms are allowed in CJK headlines.
- Words in the headline's main script are left alone, and so are characters like "CO₂", "1º" and "™".
- A script counts as disguised Latin when 90% or more of its letters have a Latin look-alike. So "МЕТА ТОР РІСК" can't switch the checks off by being all Cyrillic.

## Results

![Verdicts on clean news, no attacks](https://raw.githubusercontent.com/NoCritics/headline-antidote/master/benchmark/charts/false_alarms.png)

- **Feed headlines:** 3,242 live headlines (907 saved Nov 7, 2,335 saved Nov 9) gave 3 quarantines, each a real mixed-script word: Kommersant's "Gаsuniе" (Cyrillic а and е), "ХХI" (Latin I) and "cборная" (Latin c).
- **Article pages:** 284 saved pages, read with their stylesheets, the feed title and the browser check. 279 passed and 5 got `review`: Hindu BusinessLine pages whose "read more" collapse hides most of the article. 38 went to the browser check, and none failed. On the 228 pages from 47 sites in 9 languages saved Nov 9, the headline was right on 220.
- **Spliced attacks:** 11 attacks were spliced into each of 234 usable pages from 43 sites ([Nov 7](../real_world_test/injection_report.md), [Nov 9](../real_world_test/data_2026-11-09/injection_report.md)), and each variant was also read by BeautifulSoup, lxml, trafilatura, newspaper4k and Chrome. With the browser check, 1 of 936 headline attacks got through (a `font-size:0` class from an external stylesheet, on one Economic Times page) and 155 of 1,554 body attacks: 150 are body text removed by a script that never names it, and 5 are white text on Deutsche Welle pages whose main stylesheet the test couldn't fetch. Results per reader: [benchmark/results/](../benchmark/results/); each example attack: [benchmark/README.md](../benchmark/README.md).
- **CSS validity:** checked against Chrome on the 21,965 distinct values from the test pages, and about 840,000 generated ones.
- **Speed:** a headline takes 65 to 80 µs. `extract_article` takes 276 ms (median) and 735 ms (p95) when the site's CSS is cached, and 332 ms and 1.6 s on a mixed stream of all 228 pages.

Raw reports are in [real_world_test/](../real_world_test/).

## Known limits

- Without the browser check, JavaScript isn't run. Hidden headline words are still caught by the title comparison, unless the attacker controls every title and the feed. Hidden body text is caught only when the page has its own copy of the article (JSON-LD `articleBody`) or you pass `feed_body`.
- There is no layout. Overlays over their own box are caught; a box positioned over some unrelated part of the page is caught only by the browser check.
- The browser check sees one moment. Text hidden later (timers, scrolling, clicks) is missed, and so are covers with `pointer-events: none`.
- The browser check matches words, not positions. A hidden passage whose words all appear elsewhere on the page counts as seen.
- Script triage reads only inline scripts.
- Chrome 158 crashes on `inherit(var(--n))`. `verify_article_in_browser` then raises `TargetClosedError`, so catch its exceptions.
- A value using `if()`, typed `attr()`, `inherit()` or a custom CSS function counts as hidden, because this reader can't evaluate it.
- CSS colour variables are resolved only from inline styles and the site-wide `:root` values. `color-mix()`, relative colours and `lab()`/`lch()` hues aren't evaluated, and unknown colours never hide text.
- Mojibake from a wrong charset isn't detected.
- Substitutions that look different ("G00gle" with zeros) aren't homoglyphs and aren't flagged. Unwatched names get only the mixed-script and whole-script checks.
- An all-caps non-Latin headline made only of Latin-looking letters ("РОСТ ТОРА") gets `review`.
- Python 3.11's Unicode data is version 14, so newer characters count as non-letters.
- A rogue editor writing a visible negative headline is out of scope. Cap any one headline's effect on the score, and wait for more than one source.

## Data

`headline_antidote/unicode_data/` holds three Unicode 18.0 files: `confusables.txt`, `Scripts.txt` and `DerivedCoreProperties.txt`. The library refuses to start if a file's SHA-256 differs from `manifest.json`.

The HTML parser (selectolax), tinycss2 and cssselect2 are pinned, because a new release can change what counts as visible.
