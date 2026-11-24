# headline_guard report format

`ArticleResult.to_dict()` and `GuardResult.to_dict()` return the guard's results as plain JSON-ready
dicts. The schema is [headline_guard/report_schema.json](../headline_guard/report_schema.json)
(JSON Schema draft 2020-12). The report holds the answers the guard already gives, nothing more.

## Versioning

`schema_version` is "major.minor"; `report_type` is `article` (from `extract_article`) or `text`
(from `analyze` or `analyze_html`).

- **Minor change:** a new field, or a new `category`.
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
| `tickers` | list of strings | watched tickers named in the result |
| `metadata_titles` | object | the page's titles by name (`<title>`, `og:title`, ...) |
| `browser_check` | object | `needed`, `reasons` (sentences), `ran`, `milliseconds` (null unless it ran) |
| `flags` | list | see below |

## Text report

| field | type | meaning |
|---|---|---|
| `verdict` | pass, review, quarantine | as above |
| `text_as_written` | string | the text as given (for `analyze_html`, the visible text it read) |
| `text_cleaned` | string | the text to give the model |
| `tickers` | list of strings | watched tickers named in the text |
| `flags` | list | see below |

## A flag

| field | meaning |
|---|---|
| `category` | what was found, e.g. `watchlist_homoglyph`, `hidden_html_text` (open list) |
| `severity` | high, medium or low |
| `field` | article reports: `headline`, `body`, `metadata` or `page`; text reports: null |
| `flagged_text` | the page text the flag is about; "" when it is not about a piece of text |
| `detail` | a sentence for people; not meant to be parsed |
| `start`, `end` | text reports only: code-point offsets into `text_as_written` (`end` exclusive), or null for flags without a position (hidden HTML text, scraper differences) |

Offsets count Unicode code points. JavaScript strings count UTF-16 units, which differ for characters
outside the Basic Multilingual Plane, such as the tag characters the guard catches.

## Strings from the page are untrusted

`flagged_text`, `detail`, the titles, `hidden_ending` and the texts come from a page an
attacker may control. Give the model only `headline` and `body` (or `text_cleaned`), after checking
`verdict`. Never pass the report to an LLM as instructions, and escape its strings when displaying them.
