# headline_guard

A guard for the news-headline step of an LLM trading pipeline. It answers one question: **is the text the model will read the same text a human reader sees?**

It is a defence against the attacks in Rizvani, Apruzzese and Laskov, *Adversarial News and Lost Profits: Manipulating Headlines in LLM-Driven Algorithmic Trading* (arXiv:2601.13082, IEEE SaTML 2026):

- **Homoglyphs:** Cyrillic or Greek look-alike letters in a company name ("Теsla"). The headline is never linked to its stock.
- **Hidden text:** `<span style="display:none">losses and layoffs</span>`. The headline's sentiment flips.

## What it is, and what it isn't

NFKC normalization and the Unicode confusables data already exist. This project reuses them and adds the policy layer that is missing on top:

| | Plain NFKC | Map Cyrillic to Latin | `headline_guard` |
|---|---|---|---|
| Catches "Теsla" | no | yes | yes |
| Leaves real Russian ("сахар", "орех") alone | yes | **no, corrupts it** | yes |
| Knows "МЕТА" is a word in Ukrainian but an attack in an English headline | n/a | no | yes |
| Tells you an attack happened | no | no | **yes, every change comes with a flag** |
| Hidden HTML text, invisible Unicode tag characters | no | no | yes |

## Usage

```python
from headline_guard import HeadlineGuard, PAPER_WATCHLIST

guard = HeadlineGuard({"TSLA": ["Tesla"], "GOOGL": ["Alphabet", "Google"]})  # build once

# 0. Recommended for scraped pages: the text your LLM should receive
article = guard.extract_article(page_html, feed_title=rss_title)  # feed_title is optional
article.headline   # the visible headline, found by matching <h1>s against og:title / JSON-LD / feed title
article.body       # the visible article text: hidden elements removed, nav/sidebars/comments left out
article.verdict    # "pass" | "review" | "quarantine"
article.flags      # each with .field: "headline", "body", "metadata" or "page"
article.hidden_ending  # usually "": hidden text that is most of the article, set aside (see below)
article.needs_browser_check   # True for the pages a static reading can't settle (15% of 228 real pages)
# optional, for those pages only: a warm Chrome renders the HTML you already fetched
#   with BrowserVerifier() as verifier:          # from headline_guard.browser_visibility
#       article = guard.verify_article_in_browser(article, page_html, page_url, verifier)
# then: your_llm(article.headline, article.body) -> sentiment, unless the verdict says otherwise
# Give the model only headline and body. hidden_ending is text readers can't see: append it only
# for publishers you trust to collapse articles behind "Read more", never for every page.

# 1. Plain-text feeds
result = guard.analyze("Теsla shares surge")

# 2. HTML scrapers (BeautifulSoup, Scrapy, trafilatura, newspaper4k...)
result = guard.analyze_html(
    raw_page_html,                 # the HTML the scraper downloaded
    headline_xpath="//h1",         # the element the scraper reads
    scraped_text=scraper_output,   # what the scraper extracted from it
)

# 3. Browser scraping (recommended where you can afford it)
from headline_guard.browser_visibility import rendered_visible_text
page.goto(url)                                        # Playwright page
visible = rendered_visible_text(page.locator("h1").first)
result = guard.analyze_html(page.content(), "//h1", scraped_text=visible, rendered_by_browser=True)

result.verdict      # "pass" | "review" | "quarantine"
result.clean_text   # "Tesla shares surge", what to give the model if you trade on it at all
result.tickers      # ["TSLA"]
result.flags        # [Flag(kind="watchlist_homoglyph", severity="high", start=0, end=5, ...)]
```

The guard decides nothing about trading. A suggested policy:

- `quarantine`: don't let this headline move the signal, and alert.
- `review`: reduce its weight or require another source to confirm it.
- `pass`: use it normally.

## Where to put it: beside the scraper, not after it

The scraper is the first stage between a poisoned page and the model. Whatever it throws away cannot be recovered later. After `get_text()`, the words "losses and layoffs" from a hidden span are plain words in the headline, and nothing downstream can tell they were hidden. So:

1. Give the guard **the same document the scraper parsed**: the raw HTML for HTML parsers, or the rendered page (`page.content()`) for a browser. Pages that insert their headline with JavaScript have an empty `<h1>` in the raw HTML.
2. Also pass **the scraper's text** as `scraped_text`. The guard compares it with what a reader sees:
   - Text the scraper *adds* is flagged `high` (the model would read words no human saw), unless the guard's only reason to think it hidden was a guess, in which case the flag keeps the guess's `medium`.
   - Text the scraper *drops* is flagged `medium`.
3. **Browser mode** (`rendered_by_browser=True`) is for text from `rendered_visible_text()`. That function asks Chrome for the computed style and geometry of every piece of text, using the guard's thresholds, so it covers external stylesheets, complex selectors and JavaScript. The browser's view is treated as the truth: the model gets only what a reader sees, and anything the page hides is flagged `high`.

`scraper_comparison/` measures this on 22 pages (17 attacks, 5 clean controls, including a JavaScript-rendered page and a dark-theme page) with BeautifulSoup, lxml (Scrapy-style), trafilatura, newspaper4k and Playwright driving the installed Chrome. Full table: [scraper_comparison/results.md](scraper_comparison/results.md).

| Extractor | Attacks reaching the model (of 17) | Missed, guard after scraper | Missed, guard beside scraper | False alarms beside (of 5) |
|---|---|---|---|---|
| BeautifulSoup `get_text()` | 16 | 13 | 2 | 0 |
| lxml `text_content()` (Scrapy-style) | 16 | 13 | 2 | 0 |
| trafilatura title | 14 | 13 | 2 | 1 |
| trafilatura body text | 13 | 12 | 2 | 0 |
| newspaper4k title | 3 | 0 | 0 | 1 |
| newspaper4k body text | 13 | 13 | 2 | 0 |
| Chrome `inner_text()` | 13 | 9 | 0 | 0 |
| Chrome `text_content()` | 17 | 13 | 0 | 0 |
| **Chrome visibility walker, browser mode** | **4** | 0 | **0** | **0** |

(With the CSS engine. `analyze_html()` checks one element, so it can't compare the headline with the page's titles; `extract_article()` does, and also catches the 2 JavaScript attacks that the "beside" column still misses.)

The guard placed after the scraper never raised a false alarm, but it missed most attacks. Findings:

- **Losses at the scraping stage can't be undone.** Placed after the scraper, the guard misses 9–13 of 17 attacks with every extractor except newspaper4k's title (which ignores the `<h1>`). Placed beside the scraper, it misses 0–2.
- **A browser alone is not enough.** Chrome's `inner_text()` drops `display:none` text but passes on text hidden by a zero or tiny font, near-zero opacity, white-on-white or off-screen positioning: 13 of 17 attacks.
- **The same tool behaves differently per field.** trafilatura strips hidden text from the body but keeps it in the title; newspaper4k does the opposite. trafilatura also takes its title from the `<h1>` on some pages and from `<title>` on others, so its output can't always be compared with one element (its 2 false alarms).
- **With HTML scrapers, the guard beside them misses 2 attacks:** the ones hidden by JavaScript. The CSS engine closed the 3 complex-selector attacks and the dark-theme false alarm (it now reads the page's real background). trafilatura's and newspaper4k's title false alarms come from comparing a `<title>` with the `<h1>`.
- **Only the browser walker in browser mode had zero misses and zero false alarms.** The 4 attacks that reach its text are homoglyphs, invisible characters and tag characters, which are visible-text attacks, and the guard quarantined all 4.

Run it (needs the project virtual environment):

```
.venv\Scripts\python -X utf8 -m scraper_comparison.run_comparison
```

Playwright is set to drive the **installed Google Chrome** (`channel="chrome"`), which is signed by Google, instead of downloading its own unsigned browser build.

## Real-world test

`real_world_test/` runs the guard on 907 live feed headlines and 56 live article pages from 14 sources (English, Russian, Hebrew, German, Japanese). Report: [real_world_test/report.md](real_world_test/report.md).

- **Text mode:** 1 flag in 907 headlines. It was correct: Kommersant wrote "Gаsuniе" with Cyrillic а and е, a natural keyboard-layout slip that would also break ticker matching.
- **HTML mode:** 0 false alarms on 56 pages. It adds about 15 ms (p50) and 184 ms (p95) to a page fetch that takes about 1.2 s (p50).
- **Browser mode:** adds about 1.4–1.7 s (p50) and 6 s (p95), almost all of it the page's own assets. 3–5 of 56 pages failed (timeouts, redirects).
- **Headline selection is the biggest practical problem.** On 8 of 56 pages, the first `<h1>` isn't the headline: a "Trending now" widget on Fortune, and the site logo on Yahoo Japan. All 4 browser-mode flags came from the Yahoo logo, whose text is hidden by an ordinary image-replacement technique. Every page had `og:title`, and 53 had a JSON-LD `headline`. Choosing the `<h1>` that matches those finds the real headline on 52 of 56 pages.

## The visible-article extractor

`guard.extract_article()` sits where a page is turned into text, in front of whatever LLM the trader already runs (summarize, then score). It needs trafilatura.

1. **Headline.** It picks the `<h1>` (or `<h2>`) whose *visible* text matches the page's JSON-LD headline, `og:title`, `twitter:title` or `<title>` (site-name suffixes ignored), or the feed title if one is passed. It does not trust the first `<h1>`. Hidden text in the headline is flagged `high`. Metadata titles get the Unicode checks too, because some scrapers use them as the headline.
2. **Body.** Every hidden element is removed from the page before trafilatura's main-content detection runs, so the model gets only visible article text. The headline element is removed too, since it's returned separately.
3. **Flags.** Hidden body text is flagged `low`, and only when a standard extractor would actually have passed it to the model (and it isn't a link, button or form label). The Unicode checks run on the whole body.

Why hidden *body* text is only `low`: it is removed, so the model never sees it, and real articles hide their own text all the time. A quarter of the first 56 pages did, with duplicate captions, promotions, paywall and print notices, collapsed author bios and hidden *related headlines*. Removing it is useful in its own right, since a hidden unrelated headline would otherwise skew the sentiment. `review` is kept for cases where the model's input may still be wrong: kept text, headline doubts and unresolved browser checks. The flag still tells the caller the page carried hidden text. Hidden text in the *headline* stays `high`, because no correctly located real headline had any.

Results ([real_world_test/article_report.md](real_world_test/article_report.md)):

| | Result |
|---|---|
| Correct headline, 56 live pages, no feed title | **55 / 56** (the first `<h1>` was correct on 48 / 56) |
| Correct headline with the feed title | **56 / 56** |
| Verdicts on the 56 live (presumably clean) pages | 56 `pass` (a hidden search-box label is removed with a `low` flag) |
| Attack pages (17) | 16 flagged, and no hidden payload reaches the output. The 2 hidden by JavaScript get `review`, the title's wording and a browser check (see below). The 17th puts its homoglyph headline in only with JavaScript, so a static reader never receives it |
| Pages sent to the browser check | 4 / 56 with the feed title, 5 / 56 without (one single-word difference from the metadata title) |
| Time per page | with the CSS engine and the site's stylesheets cached: p50 233–257 ms, p95 710–820 ms. Against the code before these additions, measured back to back: median +30–50 ms, p95 about +100 ms. The page fetch itself takes about 1,200 ms p50 |

Body quality depends on trafilatura. The occasional "Published" label, a related-story line at the end, or a list of stock-price links still gets through.

## HTML parsed as Chrome parses it

Pages are parsed by lexbor (`selectolax`, pinned 1.0.2), which follows the HTML standard's parsing algorithm, and copied into the lxml tree the rest of the reader uses (`html_tree.py`). libxml2, the parser under lxml, split some markup differently, and each difference let a page hide text from Chrome while this reader showed it: a doctype with an unclosed quote (`<!doctype html public "x>`) ran on to the next quote and swallowed a `display:none` wrapper, an escaped `<script><!--<script>` ended at its first `</script>`, `<!--` inside `<textarea>` opened a comment, and elements nested deeper than 255 were dropped.

- Scripting is on, as in Chrome: `<noscript>` content is not part of the page. Its markup, and a `<template>`'s content, are still reported as hidden text, since a scraper passes them on.
- An element whose parent is more than 512 deep is attached to the grandparent, as Chrome attaches it.
- Comments keep their text as written.
- lexbor's tree building is quadratic in nesting depth, so a page with more than 20,000 `<` is not read statically: it gets a `page_too_large_to_read` flag (medium) and a browser check. The saved test pages have at most 9,230; at the limit the slowest shape found takes 1.7 s.
- Checked against Chrome 157: 29 parser cases (`tests/test_html_parsing.py`) and the 568 test readings, where the only changes were 6 headline paths, each now Chrome's. Reading takes about 3% longer (80 readings, 5 alternating runs: median 7.21 s against 6.98 s), the cost of copying the tree into lxml.

## The CSS engine

With `tinycss2` and `cssselect2` installed (pinned: 1.5.1 and 0.10.1; 0.10.1 fixes CVE-2026-55073), the visibility check uses a real CSS cascade instead of the simple rule reader:

- any selector: child and descendant combinators, attributes, `:not()`, `:nth-child()`;
- specificity, source order, `!important` and inline styles, so a later rule can show text again;
- invalid declarations are dropped, as Chrome drops them, so `opacity: 0; opacity: banana` stays hidden (`css_validity.py`).
  - Each value of a hiding property is checked against that property's grammar, from the CSS specs.
  - Every answer was checked against Chrome 157 style sheets: the 21,965 distinct values on the test pages, and about 840,000 generated and fuzzed values. None was wrong.
  - Quirks mode matters: unitless lengths and hex colours without `#` are valid only on pages without a standards doctype (`document_mode.py`, the HTML parser's rules, checked against Chrome's `compatMode`).
  - A value the grammar can't decide (3 of the 21,965, such as `calc-size()` and `anchor()`) counts both ways, like an `@supports` block below.
  - A value that is invalid only once `var()` is substituted makes the property unset, not the earlier declaration, as in Chrome.
  - Invalid custom properties (`--o: 1 ]`) are dropped too, as Chrome drops them.
  - `env()` gets the values Chrome gives at the browser check's desktop viewport: safe-area and keyboard insets are `0px`, and any other name takes its fallback.
  - Chrome 157 also evaluates `if()`, typed `attr()` and custom functions (`@function`), which this reader cannot. A hiding value that uses one counts as hidden. None of the 284 test pages uses them outside `content`;
- `@media` rules and `media` attributes, answered as the browser check's Chrome answers them: a 1366×900 desktop screen in light mode, pixel ratio 1, scripting on (`media_queries.py`, Media Queries level 4 with `not`, `or`, range syntax and every feature Chrome supports; a feature Chrome doesn't know matches nothing, as in Chrome). Mobile-only, print-only, dark-mode and `:hover` rules don't apply. The 36 test queries were checked against Chrome's `matchMedia`;
- cascade layers (`@layer`, including `revert-layer`) in Chrome's order, and nested style rules (`&`). `@document` never applies, as in Chrome;
- `@supports`, `@container` and `@scope` blocks, whose answer depends on what Chrome supports, on layout, or on how close the scope root is. Chrome may apply any subset of them, so text that any subset hides counts as hidden. This errs towards hiding, so a page can lose visible text this way. On the 284 test pages it changed no reading: 3,128 of 376,402 checked elements fall under such blocks (at most 49 combinations each, against a cap of 64 past which an element counts as hidden), and 9 elements are hidden only by this rule (Business Insider's "Search" button, outside the article). It costs about 5% per page (median of single paired runs; not yet the five-run measurement), so the speed figures below predate it. The expected answers of the test cases were checked against the installed Chrome (`AtRuleChromeTests`);
- CSS math as Chrome computes it (`css_values.py`). Every math function is evaluated wherever it appears, including inside `translateX()`, `scale()`, `opacity()`, `blur()`, color alpha, `inset()`, `rect()` and the `font` shorthand:
  - the functions are `calc()`, `min()`, `max()`, `clamp()`, `abs()`, `sign()`, `round()`, `mod()`, `rem()`, the trigonometric functions, `pow()`, `sqrt()`, `log()`, `exp()`, `hypot()` and `progress()`, along with the constants `pi`, `e`, `infinity` and `nan`;
  - as in Chrome, NaN becomes 0, an infinite length becomes -33,554,400px, and dividing by zero gives an infinity;
  - the value is checked as written, then its math is replaced by the result, so `left: calc(0px - 9999px)` is read as `-9999px`;
  - a percentage added to a length (`left: calc(-100% - 10px)`) is off-screen at -100% or beyond, or when it stays far off-screen at any containing-block width up to the viewport's;
  - in an offset, `min()` is off-screen when any argument is, and `max()` when all are. Every side of `inset` counts;
  - z-index is rounded like an integer: `calc(-0.4)` is 0;
  - all of this was checked against Chrome 157 (`AtRuleChromeTests`).
- CSS nested any depth reads without crashing. `calc()` and the parentheses in it are evaluated up to 100 levels deep, which is Chrome 157's limit. Deeper, the declaration is invalid and dropped, as in Chrome. A selector nested more than 32 deep, counting the rules it is nested in, is read as `*` (with `::before` and `::after`) in an undecided block, so it may hide anything or add text anywhere. Real selectors nest at most 6 deep;
- CSS variables, including fallbacks (`display: var(--gone, none)`), as Chrome resolves them:
  - chains and nested fallbacks of any length;
  - each variable resolved on the element that declares it and inherited from there;
  - a variable in a cycle is invalid, so a `var()` of it takes its fallback, and a declaration with nothing usable is unset.

  - `:root` outranks `html`, `body` is a separate element, and `VAR()` is `var()`, as in Chrome.

  An element counts as hidden when one of its values would resolve to more than 100,000 characters (each variable repeating the one before can double it), or when the page's resolved values pass 1,000,000 characters together. Real pages reach at most 20,529.

  To pick which elements need the full cascade, each `var()` takes every value any stylesheet or inline style on the page gives the variable. So `left: var(--x)` is caught wherever `--x: -9999px` is set. This examines about 16% more elements than the old rule, which examined only `display`, `visibility`, `opacity` and `font-size` values using `var()`;
- contrast against the real background, including backgrounds set by stylesheets;
- **external stylesheets**, if you pass their CSS text. The guard never fetches anything itself:

```python
from headline_guard.html_visibility import linked_stylesheet_urls
urls = linked_stylesheet_urls(page_html, page_url)   # fetch these once per site and cache them
guard.prepare_stylesheets([css_text_1, css_text_2])  # optional: compile them now, when fetched
article = guard.extract_article(page_html, stylesheets=[css_text_1, css_text_2])
```

Compiling a big site's CSS takes 0.5–3 s. The result is cached either way, but without `prepare_stylesheets` the site's first article waits for it. Call it from the same thread as `extract_article`.

Without the two libraries, the guard falls back to the simple reader (inline styles plus `.class`/`#id`/`tag` rules in `<style>`), and everything else works as before.

Real sites ship hundreds of kilobytes of CSS. To keep the cost down:
- **Compiled stylesheets are cached, so a site's later pages reuse its external CSS.** The caches are limited by the CSS source they hold, because compiled CSS takes about 13 times its source size in memory (7–26 times on real sites):
  - a site's external stylesheets: 24 million characters, about 300 MB. That is room for every site of a pipeline: the 47 fresh-set sites need 19.5 million.
  - pages' own `<style>` blocks: 8 million characters, about 100 MB. These are kept apart, so the many one-off page blocks (one Il Sole 24 Ore page carries 834,000 characters) never push out a site's CSS.

  The limits are `EXTERNAL_CSS_CACHE_CHARACTERS` and `PAGE_CSS_CACHE_CHARACTERS` in `css_cascade.py`; with the 2 million for page rule sets, the caches stop at about 450 MB. After the 228-page stream they held 387 MB of live objects. The old caches held 396 MB at that point, but they counted entries, not size, so in a longer run they could keep growing.
- **Only properties that can hide text are kept.** Whether a rule could hide text is decided once, when its stylesheet is compiled, unless its values use `var()`.
- **Matching runs in two steps.** An element is checked against the few rules whose values could hide text when the visibility check first asks about it. The full cascade runs only for the elements those rules touch.
- **cssselect2's element wrappers are built once per page.** cssselect2 normally re-wraps every sibling for each `:has()`, `:nth-last-child()` or sibling test: 205,000 wrappers for one 1,468-element Euronews page.

The first page from a site costs 0.5–3 s more while its CSS is compiled (see `prepare_stylesheets` above).

Results on the 56 live pages ([real_world_test/article_report.md](real_world_test/article_report.md)):

| | Page `<style>` only | With external stylesheets |
|---|---|---|
| Correct headline | 55 / 56 | 55 / 56 |
| Verdicts | 55 `pass`, 1 `review` | 55 `pass`, 1 `review` |
| Time per page, cached (p50 / p95), when the engine was added | 225 / 500 ms | 237 / 547 ms |

The engine added no false alarms. With external CSS, one page's article text got better: on Economic Times, trafilatura found the full stock analysis instead of a fragment.

Two rules came from real pages:
- Hidden text that only **repeats** visible text (NPR hides a copy of its own article) adds nothing for the model, so it is removed but not flagged. Injected text is new, so it is still flagged.
- Comparisons ignore punctuation, so "what’s" and "what's" match.

## Closing the remaining gaps

After the CSS engine, three kinds of hiding still got through: text hidden by JavaScript, text covered by another element, and CSS variables defined on narrow selectors. Codex, AGY and a Fable agent were consulted. They agreed that only the last can be fully closed without a browser, and suggested cross-checking the headline against channels that never go through CSS or JavaScript. What was built:

**1. More hiding the static reading understands.** CSS variables defined on any selector (`.article { --d: none }`, looked up through a small matcher of only the rules that define variables). Also `-webkit-text-fill-color`, `filter: opacity()` and `blur()`, `content-visibility: hidden`, the `font: 0/0 a` shorthand, sizes written as `calc()`, `min()`, `max()` or `clamp()`, `line-height: 0` with clipped overflow, letters pulled on top of each other (`letter-spacing`), `translate` off-screen, every color syntax (`rgb(0 0 0 / 0)`, `hsl()`, `hwb()`, `oklch()`, all 148 named colors), old `<font color>` and `bgcolor` attributes, closed `<details>`, SVG tooltip text and `<datalist>`. Gradient text (`background-clip: text`) and transparent text with a shadow count as visible. Text in a 1px "visually hidden" box is removed. Short labels in such a box ("Published") are not flagged, because they are screen-reader text.

**2. Overlays and stacking, where they can be judged without layout.**
- An opaque box stretched over its parent (`position: absolute; inset: 0`, or top/left 0 with 100% size), as a child element or a `::before`/`::after`, covers the parent's text.
- Text with a negative `z-index` is drawn under the background of an enclosing box, unless that box starts its own stacking context.
- Overlays sized by the whole page (paywalls, cookie banners) are not counted.

**3. The headline is compared with the feed and metadata titles.** The RSS title, `og:title`, `twitter:title`, the JSON-LD headline and `<title>` are plain text that never goes through CSS or JavaScript. When a title is the visible heading with words left out, and no title has those words, the words may be hidden from readers. Then:
- **Flag:** `headline_adds_words` at `medium` for 2 or more words, or for a single negation or number.
- **The model gets the title's wording**, so the hidden payload never reaches it.
- **The page is marked** `needs_browser_check`.

Differently worded SEO titles are not compared, because only insertions count. On the 56 real pages this gave no false alarms, with or without the feed title. One single-word difference from a metadata title is reported as `low` and sent to the browser check, because one hidden word ("surge <span>fraud</span>") can flip a headline. This catches both JavaScript attack pages without running JavaScript.

The threat model favours this check. Hidden text is the tool of an attacker who controls *part* of a page, such as a third-party script, an ad or a contributor's HTML, and cannot change the server-built titles and feed. An attacker who controls the whole server could simply change the visible headline. Against that, only corroboration across sources helps (see the last known limit).

**4. Readers and the model reading different letters.**
- `reordered_text`: `<bdo dir="rtl">` or `unicode-bidi: bidi-override` on Latin letters, which readers see reversed.
- `css_generated_text`: words a `::before`/`::after` adds to the headline. Readers see them, the model never gets them.
- `embedded_font`: a headline drawn with a font embedded in the CSS as a `data:` URI, which could draw other letters than the text holds.

**5. Triage, and the browser check.** `article.browser_check_reasons` lists what the static reading couldn't rule out:
- the heading adds words to the titles;
- an inline script finds a distinctive headline element and changes it (an id, or a class used on at most two elements, with the lookup and the change within 200 characters);
- a script or an event-handler attribute inside the headline;
- body passages missing from the page's JSON-LD `articleBody` (or the feed's full text, `feed_body=`), flagged `low`.

On the 56 real pages, 4 are sent on, all for the last reason: subheadings and promotions that the JSON-LD copy lacks.

`BrowserVerifier` keeps one Chrome running. For each page it serves the HTML the scraper already fetched under the page's real address, so relative CSS and scripts load as they do for readers and Chrome checks exactly what the scraper saw. Images, media and fonts are blocked. Scripts and stylesheets load from any site, because a third-party script is one way to hide text; `same_site_only=True` is faster but blind to that. The visibility walker now also hit-tests each piece of text: text with an opaque element drawn over it counts as hidden, except under page-sized layers (consent dialogs, paywalls) and bars stuck to the bottom of the screen. Contrast isn't judged over pictures, because images aren't downloaded. The heading is found in the rendered page by its text, because scripts rebuild pages. Then:

- headline words the browser hides: `high`, and the model gets the browser's headline;
- headline words the static reading doubted but the browser shows: the doubt is cleared and the full heading comes back;
- body text the browser hides: removed, `low`. When the browser hides most of the body as one block running to its end (a paywall script), nothing is removed and the page gets `review`;
- text cut off by a preview window (a metered paywall, a collapsed section) is the publisher's own text, so it is kept, with a `low` flag.

Browser check on all 56 real pages, to measure its false alarms ([real_world_test/browser_check_report.md](real_world_test/browser_check_report.md), [same-site only](real_world_test/browser_check_report_same_site.md)):

| | All sites' scripts | Same-site scripts only |
|---|---|---|
| Render time, warm Chrome (p50 / p95) | 1.30 / 2.61 s | 1.08 / 2.02 s |
| Verdicts if every page were checked | 49 `pass`, 7 `review`, 0 `quarantine` | 49 `pass`, 7 `review`, 0 `quarantine` |
| **End to end** (static reading, then the browser for the 4 triaged pages) | **53 `pass`, 3 `review`**: the 2 Economic Times pages, plus the Seeking Alpha label | same |

The 7 reviews if every page were checked: CNBC's metered paywall (4 pages, most of the body hidden by script), Economic Times promotions (2), and the Seeking Alpha search label that was already `review`.

**It is not fast.** Serving the saved HTML saves the second download, but the page's own scripts and stylesheets still load, so a check costs about as much as a full navigation (1.1–1.3 s p50). Loading same-site scripts only saves about 0.1–0.2 s. The 80–150 ms one consultant estimated did not hold on real pages. That is why the check runs only on triaged pages.

Building it on real pages turned up five cases that were fixed:
- **CNBC's paywall** clips the article in a 260px box. Clipped text is now kept, not removed. When a script hides most of the body as one block running to its end, the text is kept and the page reviewed. Hidden text anywhere else is still removed, so a payload bigger than the article can't use this rule.
- **Guardian's consent dialog** is a full-screen iframe drawn over the headline, so page-sized layers are now ignored.
- **Scripts rebuild headings**, so a path from the static HTML pointed at the wrong element. Headings are now found by text, and the visible text is read in the same browser call.
- **BBC's script redirects** bbc.co.uk to bbc.com. The redirect now gets the same saved page (at most 3 times), and a read cut off by the navigation is retried once.
- **A render that shows almost none of the article** (under 5% of its words: a consent wall, an error) proves nothing. The page is read once more after 3.5 s. If it still shows nothing, the static result stands and the page gets `review`: a script hiding nearly all of the body looks the same, and its text would otherwise pass in the static body.

Tests: [tests/test_remaining_gaps.py](tests/test_remaining_gaps.py) (64) and [tests/test_browser_check.py](tests/test_browser_check.py) (14, real Chrome). Each attack has a matching clean case.

## Testing on a fresh page set (2026-11-09)

The 56 pages above were too few to trust the rates, and detection had only been measured on small synthetic attack pages. So two things were added:
- **A fresh set:** 228 pages from 47 sites in 9 languages ([real_world_test/data_2026-11-09](real_world_test/data_2026-11-09)). It was collected with `collect.py --data DIR --feeds fresh`, which never repeats a baseline page.
- **An attack harness:** [real_world_test/evaluate_injections.py](real_world_test/evaluate_injections.py) splices 11 known attacks into every real page and reads each variant again. The variants keep the page's own stylesheets, scripts and layout. The press-release wires (PR Newswire, GlobeNewswire, Business Wire) refuse automated clients, so the fresh set has no press releases.

**Clean pages, end to end** (stylesheets and the feed title, then the browser check for triaged pages):

| | Baseline (56 pages) | Fresh (228 pages) |
|---|---|---|
| Correct headline | 56 / 56 | 220 / 228 (the 8 misses are TASS, whose pages are built by JavaScript, and sites whose feed title differs from the page's) |
| Static verdicts | 56 `pass` | 223 `pass`, 5 `review` |
| Sent to the browser check | 4 | 34 (15%) |
| After the browser check | all 4 `pass` | all 34 `pass` |
| **End to end** | **56 `pass`** | **223 `pass`, 5 `review`** (Hindu BusinessLine's "Read more" collapse: the hidden rest of the article is set aside in `hidden_ending`, so the body is incomplete and the page is reviewed) |

At the start of the testing phase the fresh set gave 27 `review` and 52 browser checks.

**Attacks spliced into the fresh pages, static reading** ([injection_report.md](real_world_test/data_2026-11-09/injection_report.md)). "Sent to browser" means the payload reaches the model unless the browser check runs:

| Attack | removed, flagged | removed silently | leaked, flagged | leaked, sent to browser | LEAKED, MISSED |
|---|---|---|---|---|---|
| headline: display:none span | 189 | 0 | 0 | 0 | 0 |
| headline: class hidden by external CSS (font-size:0) | 189 | 0 | 0 | 0 | 0 |
| headline: span hidden by JavaScript | 187 | 0 | 0 | 2 | 0 |
| headline: bidi-reversed span | 187 | 0 | 2 | 0 | 0 |
| body: class hidden by external CSS (opacity:0) | 172 | 2 | 0 | 4 | 0 |
| body: screen-reader box from a <style> block | 172 | 2 | 0 | 4 | 0 |
| body: off-screen paragraph | 172 | 2 | 0 | 4 | 0 |
| body: white text | 117 | 2 | 0 | 54 | 5 |
| body: paragraph covered by a white box | 174 | 2 | 0 | 2 | 0 |
| body: paragraph removed by JavaScript (by id) | 0 | 1 | 0 | 177 | 0 |
| body: paragraph removed by JavaScript (no name) | 0 | 1 | 0 | 62 | 115 |

**The same variants after the browser check** (only those the static reading sends to it). Variants with injected CSS are served to Chrome with that CSS in a `<style>` block:

| Attack | Results |
|---|---|
| headline: display:none span | removed, verdict quarantine: 34 |
| headline: class hidden by external CSS (font-size:0) | leaked, verdict pass: 1, removed, verdict quarantine: 34 |
| headline: span hidden by JavaScript | removed, verdict quarantine: 187, removed, verdict review: 2 |
| headline: bidi-reversed span | removed, verdict quarantine: 187 |
| body: class hidden by external CSS (opacity:0) | leaked, verdict review: 4, removed, verdict pass: 27, removed, verdict review: 2 |
| body: screen-reader box from a <style> block | leaked, verdict review: 4, removed, verdict pass: 29 |
| body: off-screen paragraph | leaked, verdict review: 4, removed, verdict pass: 29 |
| body: white text | leaked, verdict review: 12, removed, verdict pass: 65, removed, verdict quarantine: 1 |
| body: paragraph covered by a white box | leaked, verdict review: 2, removed, verdict pass: 29 |
| body: paragraph removed by JavaScript (by id) | leaked, verdict review: 11, removed, verdict pass: 162, removed, verdict quarantine: 1, removed, verdict review: 3 |
| body: paragraph removed by JavaScript (no name) | leaked, verdict review: 2, removed, verdict pass: 57, removed, verdict review: 3 |

Reading the browser table:
- **"removed, verdict pass"**: the browser found the payload hidden and removed it. Under the policy above, removed body text doesn't change the verdict.
- **"leaked, verdict review"**: the payload reaches the model, but the page goes to `review`. On the Hindu BusinessLine pages, for example, the payload sits inside the collapsed article, which is kept.
- **The one "leaked, verdict pass"** (Economic Times) isn't a miss. The site's own CSS overrides the injected `font-size: 0` in Chrome, so readers see the word at 11px. The static reading applied the injected rule last and judged the word hidden, which errs on the safe side.
- **The "no name" rows count only variants already on triaged pages.** The 115 that are never sent to the browser are in the static table.
- **A headline script that finds its element by tag** (`querySelector('h1')`, `getElementsByTagName('h1')`, `$('main h1')`) and writes to it sends the page to the browser. Reading it, or counting the `<h1>`s, does not. A selector built at run time, or a script loaded from a file, is still invisible to the static reading; only the browser check sees those.

On the baseline pages ([injection_report.md](real_world_test/injection_report.md)):

| Attack | removed, flagged | removed silently | leaked, flagged | leaked, sent to browser | LEAKED, MISSED |
|---|---|---|---|---|---|
| headline: display:none span | 45 | 0 | 0 | 0 | 0 |
| headline: class hidden by external CSS (font-size:0) | 45 | 0 | 0 | 0 | 0 |
| headline: span hidden by JavaScript | 45 | 0 | 0 | 0 | 0 |
| headline: bidi-reversed span | 45 | 0 | 0 | 0 | 0 |
| body: class hidden by external CSS (opacity:0) | 44 | 1 | 0 | 0 | 0 |
| body: screen-reader box from a <style> block | 44 | 1 | 0 | 0 | 0 |
| body: off-screen paragraph | 44 | 1 | 0 | 0 | 0 |
| body: white text | 37 | 1 | 0 | 7 | 0 |
| body: paragraph covered by a white box | 44 | 1 | 0 | 0 | 0 |
| body: paragraph removed by JavaScript (by id) | 0 | 0 | 0 | 45 | 0 |
| body: paragraph removed by JavaScript (no name) | 0 | 0 | 0 | 10 | 35 |

Bugs and false alarms found this way, each fixed with a test:
- **Detection gaps:**
  - A body paragraph that an inline script finds by id or class and removes was never sent to the browser. The page's scripts are now read first, and only the names they look up and change are checked against the article, at about 1 ms per page.
  - White text on an undeclared background was kept with no flag. It now gets a `possibly_hidden_text` (`low`) flag and a browser check.
  - ASP.NET sites wrap the whole page in a `<form>`, so every hidden-text flag was suppressed as "form text". Ancestors of the headline now count as page wrappers.
- **Corrupted text:** the Italian word "metà" ("half") was matched to the watched name Meta, flagged and rewritten to "Meta" in the model's text. All-lowercase accented words are now ordinary words, as plain "meta" always was.
- **False alarms:**
  - A topic label in its own element before the headline (Tagesschau's "Handel mit Wertpapieren") is a kicker: `low` and a browser check. The model still gets the title's wording.
  - Short hidden labels ("Advertisement", "Share options") are removed with a `low` flag.
  - Standfirsts that a page's JSON-LD copy lacks but its description holds no longer go to the browser.
  - Articles collapsed behind "Read more" (Hindu BusinessLine) lost 80% of their text. Hidden passages that are most of the article and run as one block to its end now get one `most_of_article_hidden` (`medium`) flag instead of a `low` flag each, and their text goes to `hidden_ending`, the same rule in the static reading and the browser check.
  - They are not put back into the body. An earlier version did, and the 2026-11-13 review showed the hole: an attacker's long hidden ending looks the same, and with only a `medium` flag it reached any pipeline that holds back just `quarantine`. Codex, agy and Fable each recommended setting it aside. On the five BusinessLine pages the body keeps the visible lead (106-216 words), and `hidden_ending` has the rest (166-919 words).
- **Browser check:**
  - It put bidi-reversed headline words back into the headline, because a browser's text gives the letters in source order.
  - The Guardian's consent dialog locks scrolling by fixing `<body>` with `overflow: hidden`. The walker then judged the whole article clipped or off the page. `<body>` and `<html>` no longer count as clipping boxes, and the page's extent includes `<body>`'s.
  - ABC fades its article in and CNBC's paywall decides late, so a near-empty first read is repeated after 3.5 s.
  - An inconclusive render of a triaged page passed it. It now gives `review`.
- **Character decoding:** one Interfax page is windows-1251. The evaluators now decode each page with its declared charset, not UTF-8.

**What still gets through:**
- **Text removed by a script that never names it** (it counts paragraphs, or finds text by its content). The static reading can't tie that script to the article, so the payload reaches the model unless the page goes to the browser for another reason. Only a browser check on every page closes this, at about 1–1.5 s per page.
- **CSS the test couldn't fetch:** Deutsche Welle's main stylesheet is blocked by its robots.txt, so white text there was judged against the dark page root. A scraper that loads the stylesheets a browser loads wouldn't hit this.

## What it checks

| Flag | Severity | Example |
|---|---|---|
| `watchlist_homoglyph` | high | "Теsla", "nvіdіа", "$ТSLA", "TesIa" (I for l) |
| `hidden_tag_characters` | high | invisible U+E00xx characters that models read as ASCII (decoded into the flag) |
| `hidden_html_text` | high | `display:none`, font smaller than 2px or 1.5pt, opacity or alpha below 0.1, text with contrast below 1.5:1 against its declared background, off-screen, `clip`, `hidden`, `<noscript>`, `.class` rules in `<style>` |
| `hidden_html_text` | medium | near-white text with no declared background (assumed white, because the real one is usually in an external stylesheet) |
| `mixed_script_word` | high | "ѕurge" (Cyrillic ѕ in a Latin word) |
| `whole_script_lookalike` | medium | "ТОР" written entirely in Cyrillic inside an English headline |
| `accented_watchlist_name` | medium | "Tésla": a watched name with marks added, still linked to its ticker |
| `compatibility_lookalike` | medium | math bold "𝐍𝐕𝐈𝐃𝐈𝐀", full-width "Ｔｅｓｌａ" in a non-CJK headline |
| `invisible_character` | medium / low | zero-width space or joiner inside a word (medium) or between words (low), stray variation selectors |
| `bidi_control` | medium | direction overrides in a headline without right-to-left text |
| `excessive_combining_marks` | medium | more than two marks stacked on one Latin, Greek or Cyrillic letter |
| `html_comment_text` | medium | text inside `<!-- -->`, which some scrapers pass on |
| `scraper_text_differs` | high / medium | the scraper's output contains words a reader can't see (high), or is missing visible words (medium) |
| `headline_not_found` | medium | `headline_xpath` matched nothing |
| `page_too_large_to_read` | medium | more than 20,000 `<` in the page, too many to parse quickly; it is not read statically, and the browser check is asked for |
| `hidden_text_in_article` | low | hidden body text a standard extractor would pass to the model, or that a browser hides (removed, so the model never sees it) |
| `possibly_hidden_text` | low | body text whose color may match an undeclared page background (kept; asks for a browser check) |
| `headline_adds_words` | medium / low | the visible heading adds words no feed or metadata title has (medium for 2+ words, a negation or a number: the model gets the title's wording; low for one ordinary word or a kicker label) |
| `reordered_text` | high / medium | letters readers see in reverse order (`<bdo dir="rtl">`, `unicode-bidi: bidi-override`); high in the headline |
| `css_generated_text` | medium | words `::before`/`::after` add to the headline, which the model never receives |
| `embedded_font` | medium | the headline is drawn with a font embedded in the CSS (`data:` URI) |
| `most_of_article_hidden` | medium | most of the body is hidden as one block running to its end, statically or in a browser (a "Read more" collapse, a paywall, or a hidden ending): the body is incomplete, and the hidden text is in `hidden_ending`, not the body |
| `browser_check_inconclusive` | medium | the browser showed almost none of the article (a consent wall, a redirect, or a script hiding nearly all of the body); the static result stands, for review |
| `headline_not_found_in_browser` | high | in a browser no heading matches the static headline (a script removed or rewrote it): readers see another headline, or none, so the page stays unverified and keeps its reasons for the check |
| `body_text_not_in_page_copy` | low | body passages missing from the page's JSON-LD copy (asks for a browser check) |
| `text_behind_preview_window` | low | in a browser, paragraphs cut off by a paywall preview or collapsed section (kept) |
| `browser_check_incomplete` | low | the page didn't finish loading in the browser |
| `headline_from_metadata` | low | no visible heading matches the page's titles; the metadata headline is used, unchecked for visibility |
| `headline_unconfirmed` | low | no metadata or feed title to confirm the chosen `<h1>` |
| `article_body_not_found` | low | trafilatura found no article text |
| `possible_watchlist_lookalike` | low | "МЕТА" inside a Cyrillic headline (a real word) |

Invisible characters, compatibility forms and combining marks found **inside a watched name** are raised to high.

**Respecting real language:**

- ZWJ/ZWNJ are allowed in Arabic, Persian, Indic and similar scripts, and in emoji sequences. Tag characters are allowed only in the three real subdivision-flag emoji (England, Scotland, Wales).
- Bidi marks are allowed when the headline contains right-to-left text.
- Full-width forms are allowed in CJK headlines.
- Japanese words that mix Han, Hiragana and Katakana are allowed.
- Words written in a script are left alone when that script dominates the headline.
- Legitimate compatibility characters ("CO₂", "1º", "™") are kept as written.

**Closing the exemptions to attackers:** a script counts as disguised Latin when 90% or more of its letters in the headline have a Latin look-alike. Real Russian or Greek always includes letters such as б, д, и, л or Δ, Π. Without this rule, an attacker could write a whole English headline in Cyrillic look-alikes ("МЕТА ТОР РІСК") so that Cyrillic "dominates" and the checks switch off.

## Speed

About 65–80 µs per headline on this machine (pure Python). The Unicode tables load once. Reading HTML needs lxml and selectolax.

**Article reading** (`extract_article` with the site's stylesheets, on the 228 fresh pages; the optimization of 2026-11-13). The code before and after was run in one process, page by page and back to back. Garbage collection was kept out of the timed reads and is reported separately. These are wall-clock times on a busy 16 GB laptop whose CPU clock varies widely (runs minutes apart differed up to 3×), so only pairs are compared. Medians of 5 paired runs, with the range of the after/before ratio:

| | Before (p50 / p95) | After (p50 / p95) | p95 change [range] |
|---|---|---|---|
| Mixed stream of all pages | 393 / 1,937 ms | 332 / 1,635 ms | −15% [−14…−19%] |
| Pages whose site CSS is already cached | 319 / 1,186 ms | 276 / 735 ms | −35% [−30…−46%] |
| First page of a site, compiling its CSS | 932 / 2,494 ms | 880 / 2,218 ms | −13% [−8…−14%] |

The gain is concentrated on sites whose CSS uses `:has()`, `:nth-last-child()` and sibling selectors: Euronews pages went from about 600 to about 150 ms. On the median page it is about 6%. The first page of a site still pays for compiling its CSS, unless the pipeline calls `prepare_stylesheets` when it fetches the stylesheets. The separate caches cost no speed on this page set, and in this 228-page stream they hold about the same memory as the old ones: 387 against 396 MB of live objects. What they add is the size limit, about 450 MB in all.

Where the time goes now, on pages whose site CSS is cached (final code, one run):
- trafilatura: 35%;
- compiling the page's own one-off `<style>` blocks: 24%;
- the visibility walk, including matching elements against hiding rules on demand: 23% (eager matching took 14% before);
- the text checks: 6%.

trafilatura runs twice on pages with hidden text, once without the hidden elements and once with them. Both runs are needed: the second shows whether a standard extractor would have passed the hidden text on, and the collapse rule depends on it. Codex measured that skipping it safely would skip 0 of 213 runs.

**Garbage collection is a pipeline setting.** A full collection has to scan the millions of objects that compiled CSS creates. With Python's default thresholds this takes 0.4–1 s each, about once every four pages, and lands on whatever page is being read: in one run of the final code, 52 full collections took 22.8 s of a 143 s stream. With `gc.set_threshold(10000, 10, 10)` at the start of the pipeline, there were 5 full collections taking 5.1 s, and the stream took 124 s. The library leaves the setting alone, because it applies to the whole process.

Tools for this, in [real_world_test](real_world_test):
- [snapshot_outputs.py](real_world_test/snapshot_outputs.py) records every field of every reading, 568 readings over both page sets, and compares two records. It is the old-versus-new check for any refactor. All of the changes above gave 0 differences.
- [benchmark_static.py](real_world_test/benchmark_static.py) times cold reads, a site already seen, and a mixed stream, without a profiler, which overstates the many small Python calls in cssselect2. It times one version. To compare versions, load both into one process and alternate them page by page, because separate runs on this machine differed up to 3× with the CPU clock.

## Running the tests

```
python -X utf8 -m unittest discover -s tests -t .
```

The tests cover the paper's attacks, their variants, and attacks shaped to slip through the language exemptions. They also include **39 real headlines** in English, Russian, Ukrainian, Serbian (both alphabets), Bulgarian, Greek, Persian, Arabic, Hebrew, Hindi, Japanese, Chinese, Korean, Spanish and German, plus emoji. Each of these must pass with no flags and come out unchanged.

## Data

`unicode_data/` holds three official Unicode files: `confusables.txt` (UTS #39), `Scripts.txt` and `DerivedCoreProperties.txt` (Unicode 18.0). They are parsed as data only. The loader refuses to start if any file's SHA-256 differs from `unicode_data/manifest.json`.

## Known limits

- **Without a browser, JavaScript isn't run.** In the headline, hidden words are caught by the title comparison, unless the attacker also controls every title and the feed. In the body, they are caught only when the page carries its own copy of the article (JSON-LD `articleBody`, 10 of 56 real pages) or the caller passes the feed's full text. Otherwise only the browser check sees them.
- **The CSS engine does no layout.** Overlays stretched over their own box and negative z-index are caught. A box positioned against some unrelated part of the page is caught only by the browser check.
- **CSS variables** used for colors are resolved only from inline styles and the site-wide `:root` values, because modern CSS writes almost every color as a variable and checking all of them would be slow. `display`, `visibility`, `opacity` and `font-size` variables are resolved from any rule.
- **The browser check sees one moment.** Text hidden later (timers, scrolling, clicks) isn't seen. Hit-testing misses covers with `pointer-events: none`.
- **The browser check matches words, not positions.** A hidden passage whose words all appear elsewhere on the page counts as seen. A payload with wording of its own is caught.
- **When the browser shows almost none of the article,** even after a second read, the static result stands (`review` for a triaged page).
- **Scripts that hide body text without naming it** are seen only by the browser check, which runs only on triaged pages (see the fresh-set test).
- **Script triage reads only inline scripts.** External bundles that change the headline go unnoticed until the title comparison or the browser check catches the effect.
- **Pages with more than 20,000 `<`** are not read statically (see "HTML parsed as Chrome parses it"); only the browser check reads them.
- **Without tinycss2/cssselect2,** only inline styles and simple `.class`/`#id`/`tag` rules in `<style>` are understood: no external stylesheets, complex selectors or media queries.
- **Cost of the browser check:** one Chrome kept running, and about 1.1–1.3 s (p50) per checked page, mostly the page's own scripts.
- **`scraped_text` must come from the same element as `headline_xpath`.** A `<title>` with a " - Reuters" suffix compared against the `<h1>` will be flagged as different.
- **Encoding errors** (a scraper decoding UTF-8 bytes with the wrong charset, producing mojibake) are not detected.
- **Colors:** `color-mix()`, relative colors and `lab()`/`lch()` hues are not evaluated (`lab()`/`lch()` lightness is). Unknown colors never hide text.
- **All-caps headlines in a non-Latin language** made only of Latin-looking letters (for example a two-word Russian headline like "РОСТ ТОРА") are treated as disguised Latin and get `review`. Real headlines rarely avoid every non-look-alike letter.
- **Substitutions that look visibly different** ("G00gle" with zeros) are not homoglyphs under UTS #39 and are not flagged.
- **Unwatched names** are protected only by the mixed-script and whole-script checks, not by name matching.
- **Language is judged per headline** by its dominant script. Very short headlines that mix languages can be misjudged.
- **Character categories:** Python 3.11's `unicodedata` is Unicode 14. Characters added since then are treated as non-letters.
- **Out of scope:** a rogue editor writing a genuinely negative but visible headline. That needs safeguards in the trading layer: cap any one headline's effect on the daily score, use medians rather than means, and require confirmation from more than one source.
