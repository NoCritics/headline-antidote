# Real-world test

Text mode on 907 real feed headlines: 1 flagged, 159.8 µs each.

## Pages (56)

| Mode | Verdicts |
|---|---|
| HTML mode (raw HTML + BeautifulSoup text) | pass: 56 |
| Browser mode, live page | error: 5, pass: 47, quarantine: 4 |
| Browser mode, fetched HTML + live assets | error: 3, pass: 49, quarantine: 4 |

## Timings (milliseconds, p50 / p95)

| Step | p50 | p95 | n |
|---|---|---|---|
| HTTP fetch of the article | 1199.7 | 2688.6 | 56 |
| BeautifulSoup h1 extraction | 67.2 | 153.5 | 56 |
| Guard, HTML mode (whole page) | 14.9 | 183.6 | 56 |
| Browser: live page load | 1720.2 | 6888.9 | 52 |
| Browser: fetched HTML + live assets | 1442.5 | 6341.5 | 55 |
| Browser: visibility walker + page.content() | 175.1 | 1070.5 | 51 |
| Guard, browser mode | 43.6 | 395.8 | 51 |

## Every flag, for manual review

- feed title, Kommersant: `mixed_script_word` (high) in 'Оператор «Турецкого потока» подал иск к голландской Gаsuniе и «Нафтогазу»': Latin word containing U+0430 CYRILLIC SMALL LETTER A, U+0435 CYRILLIC SMALL LETTER IE
- page_053.html Yahoo Japan Business [browser_live]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_053.html Yahoo Japan Business [browser_prefetched]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_054.html Yahoo Japan Business [browser_live]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_054.html Yahoo Japan Business [browser_prefetched]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_055.html Yahoo Japan Business [browser_live]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_055.html Yahoo Japan Business [browser_prefetched]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_056.html Yahoo Japan Business [browser_live]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on
- page_056.html Yahoo Japan Business [browser_prefetched]: `hidden_html_text` (high) 'Yahoo!ニュース': text the rendered page hides from readers (CSS or JavaScript this parser cannot evaluate) but HTML-based scrapers would pass on

## Pages without a usable headline

- page_005.html BBC Business https://www.bbc.co.uk/news/articles/c35ynnpzdq51o?at_medium=RSS&at_campaign=rss: browser_live: error: Error: Page.content: Unable to retrieve content because the page is navigating and changing the content.
- page_006.html BBC Business https://www.bbc.co.uk/news/articles/crlykkzwwpydo?at_medium=RSS&at_campaign=rss: browser_prefetched: error: Error: Locator.evaluate: Execution context was destroyed, most likely because of a navigation
- page_007.html BBC Business https://www.bbc.co.uk/news/articles/c33zdz2m1e2o?at_medium=RSS&at_campaign=rss: browser_prefetched: error: Error: Locator.evaluate: Execution context was destroyed, most likely because of a navigation
- page_013.html NPR Business https://www.npr.org/2026/11/06/nx-s1-6032607/the-cybertrucks-cause-of-death-insufficient-demand: browser_live: error: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://www.npr.org/2026/11/06/nx-s1-6032607/the-cybertrucks-cause-of-death-insuffic
- page_029.html Al Jazeera https://www.aljazeera.com/news/2026/11/7/pope-leo-hold-first-mass-in-uruguay-urges-crowd-to-be-bridge-builders?traffic_source=rss: browser_live: error: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://www.aljazeera.com/news/2026/11/7/pope-leo-hold-first-mass-in-uruguay-urges-c; browser_prefetched: error: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://www.aljazeera.com/news/2026/11/7/pope-leo-hold-first-mass-in-uruguay-urges-c
- page_033.html Nikkei Asia https://asia.nikkei.com/business/finance/credit-saison-adb-to-partner-on-loans-for-asia-s-small-businesses: browser_live: error: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://asia.nikkei.com/business/finance/credit-saison-adb-to-partner-on-loans-for-a
- page_037.html Economic Times https://economictimes.indiatimes.com/markets/stocks/news/dalal-street-week-ahead-nifty-bulls-come-back-to-life-but-2500025200-zone-poses-next-test/articleshow/135634291.cms: browser_live: error: TimeoutError: Page.goto: Timeout 30000ms exceeded.
Call log:
  - navigating to "https://economictimes.indiatimes.com/markets/stocks/news/dalal-street-week-ahead-nif