"""The browser check: Chrome renders the HTML the scraper fetched and settles what the
static reading could not (needs playwright and Google Chrome; skipped otherwise)."""

import importlib.util
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST

GUARD = HeadlineGuard(PAPER_WATCHLIST)
HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
PAYLOAD = "losses and layoffs"
URL = "https://guard-test.invalid/markets/article"
BODY = (
    "<p>Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
    "a breakup of the company, a ruling analysts said removes a major overhang.</p>"
    "<p>The decision lifted other large technology stocks as investors bet that regulators "
    "would struggle to force structural remedies on the sector.</p>"
)
AVAILABLE = (importlib.util.find_spec("playwright") is not None
             and importlib.util.find_spec("trafilatura") is not None)


def page(headline_html, head_extra="", body_extra="", title=HEADLINE, article_extra=""):
    return (
        f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{title}</title>{head_extra}</head>"
        f"<body><article><h1>{headline_html}</h1>{BODY}{article_extra}</article>{body_extra}</body></html>"
    )


@unittest.skipUnless(importlib.util.find_spec("trafilatura") is not None, "trafilatura not installed")
class RenderedPageComparisonTests(unittest.TestCase):
    """compare_with_rendered_page on a constructed render (no Chrome needed)."""

    def test_long_hidden_ending_is_set_aside_not_kept_in_the_body(self):
        # Review finding 2: hidden text running to the end that is most of the article was kept in
        # the body. It now goes to hidden_ending, which a pipeline uses only by choice.
        from headline_guard.browser_check import compare_with_rendered_page
        from headline_guard.browser_visibility import RenderedPage

        visible_paragraph = ("Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
                             "a breakup of the company, a ruling analysts said removes a major overhang.")
        hidden_lines = ""
        for number in range(6):
            hidden_lines += (f"<p>Insiders say restructuring wave {number} will bring mass layoffs, a profit "
                             "warning and a regulatory probe that analysts expect to hit the shares.</p>")
        html = (f"<!doctype html><html><head><title>{HEADLINE}</title></head><body><article>"
                f"<h1>{HEADLINE}</h1><p>{visible_paragraph}</p>{hidden_lines}</article></body></html>")
        article = GUARD.extract_article(html)
        self.assertIn("layoffs", article.body)
        rendered = RenderedPage(HEADLINE, f"{HEADLINE}\n{visible_paragraph}", "", 5.0, True)
        verified = compare_with_rendered_page(GUARD, article, rendered)
        self.assertNotIn("layoffs", verified.body)
        self.assertIn("Shares of Alphabet rose sharply", verified.body)
        self.assertIn("restructuring wave 0", verified.hidden_ending)
        self.assertIn("restructuring wave 5", verified.hidden_ending)
        self.assertIn("most_of_article_hidden", [flag.kind for flag in verified.flags])
        self.assertEqual(verified.verdict, "review")

    def test_almost_fully_hidden_body_is_reviewed_not_passed(self):
        # Hole A: a script hiding nearly all of the body made the render "inconclusive", which kept
        # the static body (payload included) with a low flag, so the page passed. A render showing
        # almost none of the article now always sends the page to review.
        from headline_guard.browser_check import compare_with_rendered_page
        from headline_guard.browser_visibility import RenderedPage

        visible_paragraph = ("Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
                             "a breakup of the company, a ruling analysts said removes a major overhang.")
        hidden_lines = ""
        for number in range(30):
            hidden_lines += (f"<p>Insiders say restructuring wave {number} will bring mass layoffs, a profit "
                             "warning and a regulatory probe that analysts expect to hit the shares.</p>")
        html = (f"<!doctype html><html><head><title>{HEADLINE}</title></head><body><article>"
                f"<h1>{HEADLINE}</h1><p>{visible_paragraph}</p>{hidden_lines}</article></body></html>")
        article = GUARD.extract_article(html)
        self.assertEqual(article.verdict, "pass")
        rendered = RenderedPage(HEADLINE, f"{HEADLINE}\n{visible_paragraph}", "", 5.0, True)
        verified = compare_with_rendered_page(GUARD, article, rendered)
        self.assertIn("browser_check_inconclusive", [flag.kind for flag in verified.flags])
        self.assertEqual(verified.verdict, "review")
        self.assertFalse(verified.browser_verified)


@unittest.skipUnless(AVAILABLE, "playwright or trafilatura not installed")
class MediaFeatureTableTests(unittest.TestCase):
    """media_queries' feature tables against the installed Chrome: a feature or value Chrome knows
    and the tables don't would let '@media not (...)' rules apply in Chrome but not here."""

    FEATURE_NAMES = (
        "width", "height", "aspect-ratio", "orientation", "resolution", "scan", "grid", "update",
        "overflow-block", "overflow-inline", "color", "color-index", "monochrome", "color-gamut", "pointer",
        "hover", "any-pointer", "any-hover", "prefers-reduced-motion", "prefers-reduced-transparency",
        "prefers-contrast", "forced-colors", "prefers-color-scheme", "scripting", "dynamic-range",
        "video-dynamic-range", "inverted-colors", "display-mode", "device-width", "device-height",
        "device-aspect-ratio", "-webkit-device-pixel-ratio", "-webkit-transform-3d", "prefers-reduced-data",
        "device-posture", "horizontal-viewport-segments", "vertical-viewport-segments", "shape",
        "navigation-controls", "environment-blending", "video-color-gamut", "light-level",
    )
    EXTRA_VALUES = ("blue", "auto", "true", "borderless", "optional-paged", "inverted", "high", "2")

    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright

        from headline_guard.browser_visibility import VIEWPORT

        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch(channel="chrome")
        except Exception as error:  # Chrome missing or not launchable here
            cls.playwright.stop()
            raise unittest.SkipTest(f"Chrome not available: {error}")
        cls.page = cls.browser.new_context(viewport=VIEWPORT).new_page()
        cls.page.set_content("<html><body></body></html>")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def matches(self, query):
        return self.page.evaluate("query => matchMedia(query).matches", query)

    def chrome_knows(self, condition):
        # A known feature or value makes the condition or its negation match; an unknown one neither.
        return self.matches(condition) or self.matches(f"not {condition}")

    def test_feature_names(self):
        from headline_guard.media_queries import DISCRETE_FEATURES, RANGE_FEATURES

        for name in self.FEATURE_NAMES:
            with self.subTest(feature=name):
                in_tables = name in RANGE_FEATURES or name in DISCRETE_FEATURES
                self.assertEqual(self.chrome_knows(f"({name})"), in_tables)

    def test_discrete_feature_values(self):
        from headline_guard.media_queries import DISCRETE_FEATURES, media_query_applies

        all_values = set(self.EXTRA_VALUES)
        for _, known_values in DISCRETE_FEATURES.values():
            for value in known_values:
                all_values.add(value)
        for name, (screen_value, known_values) in DISCRETE_FEATURES.items():
            for value in sorted(all_values):
                condition = f"({name}: {value})"
                with self.subTest(condition=condition):
                    self.assertEqual(self.chrome_knows(condition), value in known_values)
                    self.assertEqual(media_query_applies(condition), self.matches(condition))
                    self.assertEqual(media_query_applies(f"not {condition}"), self.matches(f"not {condition}"))



@unittest.skipUnless(importlib.util.find_spec("playwright") is not None, "playwright not installed")
class AtRuleChromeTests(unittest.TestCase):
    """The answers in test_css_cascade.CHROME_DECIDED_CASES, checked against the installed Chrome."""

    def test_answers_match_chrome(self):
        from playwright.sync_api import sync_playwright

        from headline_guard.browser_visibility import VIEWPORT
        from tests.test_css_cascade import CHROME_DECIDED_CASES, at_rule_page

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:  # Chrome missing or not launchable here
                self.skipTest(f"Chrome not available: {error}")
            tab = browser.new_context(viewport=VIEWPORT).new_page()
            for css, inline_style, hidden in CHROME_DECIDED_CASES:
                with self.subTest(css=css, inline_style=inline_style):
                    tab.set_content(at_rule_page(css, inline_style))
                    chrome_hidden = tab.evaluate("getComputedStyle(document.getElementById('x')).display === 'none'")
                    self.assertEqual(chrome_hidden, hidden)
            browser.close()


@unittest.skipUnless(AVAILABLE, "playwright or trafilatura not installed")
class BrowserCheckTests(unittest.TestCase):
    verifier = None

    @classmethod
    def setUpClass(cls):
        from headline_guard.browser_visibility import BrowserVerifier

        try:
            cls.verifier = BrowserVerifier().start()
        except Exception as error:  # Chrome missing or not launchable here
            raise unittest.SkipTest(f"Chrome not available: {error}")

    @classmethod
    def tearDownClass(cls):
        if cls.verifier is not None:
            cls.verifier.close()

    def check(self, html):
        article = GUARD.extract_article(html)
        return article, GUARD.verify_article_in_browser(article, html, URL, self.verifier)

    def test_text_hidden_by_javascript(self):
        article, verified = self.check(page(
            f'{HEADLINE}<span id="p"> {PAYLOAD}</span>',
            body_extra="<script>document.getElementById('p').style.display='none';</script>",
        ))
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(verified.verdict, "quarantine")
        self.assertEqual(verified.headline, HEADLINE)
        self.assertTrue(verified.browser_verified)

    def test_class_added_by_javascript(self):
        article, verified = self.check(page(
            f'{HEADLINE}<span id="p"> {PAYLOAD}</span>',
            head_extra="<style>article h1 span.gone { opacity: 0; }</style>",
            body_extra="<script>document.getElementById('p').className='gone';</script>",
        ))
        self.assertEqual(verified.verdict, "quarantine")
        self.assertEqual(verified.headline, HEADLINE)

    def test_element_drawn_over_the_words_from_elsewhere(self):
        # The cover is positioned against the whole page, which the static reading does not lay out.
        css = ("<style>body { margin: 0 } h1 { margin: 0; font-size: 30px; line-height: 40px }"
               " .second { display: block } .cover { position: absolute; top: 40px; left: 0;"
               " width: 100%; height: 40px; background: #fff }</style>")
        article, verified = self.check(page(
            f'{HEADLINE}<span class="second">{PAYLOAD}</span>', head_extra=css,
            body_extra='<div class="cover"></div>',
        ))
        self.assertEqual(verified.verdict, "quarantine", verified.flags)
        self.assertEqual(verified.headline, HEADLINE)

    def test_one_word_hidden_by_javascript(self):
        article, verified = self.check(page(
            f'Alphabet shares surge <span id="p">fraud</span> after dodging antitrust breakup bullet',
            body_extra="<script>document.getElementById('p').style.display='none';</script>",
        ))
        self.assertTrue(article.needs_browser_check)
        self.assertEqual(verified.verdict, "quarantine")
        self.assertEqual(verified.headline, HEADLINE)

    def test_payload_longer_than_the_article_is_still_removed(self):
        # Hidden text bigger than the visible article, but not at its end: not a paywall.
        hidden_lines = ""
        for number in range(6):
            hidden_lines += (f'<p class="x">Insiders say restructuring wave {number} will bring mass layoffs, '
                             "a profit warning and a regulatory probe that analysts expect to hit the shares.</p>")
        html = (f"<!doctype html><html><head><title>{HEADLINE}</title></head><body><article>"
                f"<h1>{HEADLINE}</h1>{hidden_lines}{BODY}</article>"
                "<script>for (const p of document.querySelectorAll('.x')) p.style.display='none';</script>"
                "</body></html>")
        article, verified = self.check(html)
        self.assertIn("layoffs", article.body)
        self.assertNotIn("layoffs", verified.body)
        self.assertNotIn("most_of_article_hidden", [flag.kind for flag in verified.flags])

    def test_headline_removed_by_javascript_is_not_verified(self):
        # Review finding 3: when the browser finds no visible heading matching the static one, the
        # check returned the static headline as verified, with the reasons for the check cleared.
        hidden_headline = f"{HEADLINE} as insiders dump {PAYLOAD}"
        article, verified = self.check(page(
            f'<span id="lead">{hidden_headline}</span>', title=hidden_headline,
            body_extra="<script>document.getElementById('lead').remove();</script>",
        ))
        self.assertTrue(article.needs_browser_check, article.browser_check_reasons)
        self.assertNotEqual(verified.verdict, "pass", verified.flags)
        self.assertFalse(verified.browser_verified)
        self.assertTrue(verified.needs_browser_check)

    def test_headline_replaced_by_javascript_is_not_verified(self):
        hidden_headline = f"{HEADLINE} as insiders dump {PAYLOAD}"
        article, verified = self.check(page(
            f'<span id="lead">{hidden_headline}</span>', title=hidden_headline,
            body_extra="<script>document.getElementById('lead').textContent='Markets wrap: stocks mixed';</script>",
        ))
        self.assertNotEqual(verified.verdict, "pass", verified.flags)
        self.assertFalse(verified.browser_verified)

    def test_visible_extra_words_are_cleared(self):
        # The heading has words the title lacks, but readers do see them.
        article, verified = self.check(page(f"{HEADLINE} with {PAYLOAD}"))
        self.assertEqual(article.verdict, "review")
        self.assertEqual(article.headline, HEADLINE)
        self.assertEqual(verified.verdict, "pass", verified.flags)
        self.assertEqual(verified.headline, f"{HEADLINE} with {PAYLOAD}")

    def test_body_paragraph_hidden_by_javascript_is_removed(self):
        injected = ('<p id="x">Insiders say the company is preparing mass layoffs and a profit warning '
                    "that will shock investors next week.</p>")
        html = (f"<!doctype html><html><head><title>{HEADLINE}</title></head><body><article>"
                f"<h1>{HEADLINE}</h1>{BODY}{injected}</article>"
                "<script>document.getElementById('x').style.visibility='hidden';</script></body></html>")
        article, verified = self.check(html)
        self.assertTrue(article.needs_browser_check)  # the script names the paragraph and changes it
        self.assertIn("layoffs", article.body)
        self.assertNotIn("layoffs", verified.body)
        self.assertIn("hidden_text_in_article", [flag.kind for flag in verified.flags])

    def test_white_text_on_an_undeclared_background_is_settled_by_the_browser(self):
        injected = ('<p style="color:#fff">Insiders say the company is preparing mass layoffs and a profit '
                    "warning that will shock investors next week.</p>")
        article, verified = self.check(page(HEADLINE, article_extra=injected))
        self.assertTrue(article.needs_browser_check)
        self.assertIn("layoffs", article.body)
        self.assertNotIn("layoffs", verified.body)

    def test_white_text_on_a_dark_box_stays(self):
        injected = ('<div style="background:#123"><p style="color:#fff">Insiders say the company is preparing '
                    "mass layoffs and a profit warning that will shock investors next week.</p></div>")
        article, verified = self.check(page(HEADLINE, article_extra=injected))
        self.assertIn("layoffs", verified.body)
        self.assertEqual(verified.verdict, "pass", verified.flags)

    def test_render_showing_nothing_is_inconclusive(self):
        # A consent wall over everything: the browser sees none of the article, which proves nothing,
        # so the static body stands and the page goes to review (a script could have hidden it).
        wall = ('<div style="position:fixed;inset:0;background:#fff;z-index:9"></div>'
                "<script>document.querySelector('article').style.visibility='hidden';</script>")
        article, verified = self.check(page(HEADLINE, body_extra=wall))
        self.assertIn("browser_check_inconclusive", [flag.kind for flag in verified.flags])
        self.assertEqual(verified.verdict, "review")
        self.assertEqual(verified.body, article.body)
        self.assertFalse(verified.browser_verified)

    def test_inconclusive_render_of_a_triaged_page_is_reviewed(self):
        # The page was sent to the browser for a reason (a script changes article text); a render
        # that shows nothing can't settle it, so the page must not pass with the paragraph in it.
        injected = ('<p id="x">Insiders say the company is preparing mass layoffs and a profit warning '
                    "that will shock investors next week.</p>")
        wall = ("<script>document.getElementById('x').remove();"
                "document.querySelector('article').style.visibility='hidden';</script>")
        article, verified = self.check(page(HEADLINE, article_extra=injected, body_extra=wall))
        self.assertTrue(article.needs_browser_check)
        self.assertIn("browser_check_inconclusive", [flag.kind for flag in verified.flags])
        self.assertEqual(verified.verdict, "review")

    def test_reversed_headline_words_are_not_restored(self):
        # A browser's text gives reversed words in source order; it must not count them as seen.
        article, verified = self.check(page(
            f'{HEADLINE}<span style="unicode-bidi:bidi-override;direction:rtl"> {PAYLOAD}</span>'))
        self.assertNotIn(PAYLOAD, article.headline)
        self.assertNotIn(PAYLOAD, verified.headline)
        self.assertEqual(verified.verdict, "quarantine")

    def test_consent_scroll_lock_does_not_hide_the_article(self):
        # The Guardian's consent dialog fixes <body> with overflow hidden: the page is cut off at
        # one screen for scrolling, but nothing is hidden from readers.
        long_article = ""
        for number in range(40):
            # Words unique to each paragraph, so a hidden one can't be matched elsewhere on the page.
            long_article += (f"<p>Paragraph {number}: unit{number}a and unit{number}b rose while unit{number}c "
                             f"and unit{number}d fell, said desk{number}e.</p>")
        lock = ("<script>document.body.style.position='fixed';document.body.style.overflow='hidden';"
                "document.body.style.height='100vh';document.body.style.width='100%';</script>")
        article, verified = self.check(page(HEADLINE, article_extra=long_article, body_extra=lock))
        self.assertIn("Paragraph 39", verified.body)
        self.assertNotIn("browser_check_inconclusive", [flag.kind for flag in verified.flags])
        self.assertEqual(verified.verdict, "pass", verified.flags)

    def test_clean_page_passes(self):
        article, verified = self.check(page(HEADLINE))
        self.assertEqual(verified.verdict, "pass", verified.flags)
        self.assertEqual(verified.headline, HEADLINE)
        self.assertIn("federal judge", verified.body)


if __name__ == "__main__":
    unittest.main()
