"""Hidden-text injection: only what a reader sees should reach the model."""

import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST

GUARD = HeadlineGuard(PAPER_WATCHLIST)
VISIBLE_HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"


def hidden_text_flags(result):
    found_flags = []
    for flag in result.flags:
        if flag.kind == "hidden_html_text":
            found_flags.append(flag)
    return found_flags


class HiddenTextTests(unittest.TestCase):
    def assert_hidden_text_caught(self, html, expected_reason_fragment):
        result = GUARD.analyze_html(html)
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(result.verdict, "quarantine")
        flags = hidden_text_flags(result)
        self.assertEqual(len(flags), 1, result.flags)
        self.assertEqual(flags[0].original, "losses and layoffs")
        self.assertIn(expected_reason_fragment, flags[0].detail)

    def test_paper_display_none(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="display:none"> losses and layoffs</span></h1>',
            "display:none",
        )

    def test_paper_zero_font_size(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="font-size: 0pt"> losses and layoffs</span></h1>',
            "font-size",
        )

    def test_text_color_matches_background(self):
        self.assert_hidden_text_caught(
            f'<h1 style="background-color:#fff">{VISIBLE_HEADLINE}'
            f'<span style="color: white"> losses and layoffs</span></h1>',
            "nearly matches its background",
        )

    def test_near_background_color(self):
        self.assert_hidden_text_caught(
            f'<h1 style="background:#ffffff">{VISIBLE_HEADLINE}'
            f'<span style="color:#fefefe">losses and layoffs</span></h1>',
            "nearly matches its background",
        )

    def test_tiny_font_size(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="font-size:1px">losses and layoffs</span></h1>',
            "font-size:1px",
        )

    def test_near_zero_opacity(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="opacity:0.01">losses and layoffs</span></h1>',
            "opacity",
        )

    def test_near_transparent_rgba_text(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="color:rgba(0,0,0,0.02)">losses and layoffs</span></h1>',
            "transparent",
        )

    def test_white_text_without_declared_background_is_medium(self):
        # The page's background usually lives in an external stylesheet, so white is assumed.
        result = GUARD.analyze_html(
            f'<h1>{VISIBLE_HEADLINE}<span style="color:#fff">losses and layoffs</span></h1>'
        )
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(result.verdict, "review")
        flags = hidden_text_flags(result)
        self.assertEqual(len(flags), 1)
        self.assertIn("guess", flags[0].detail)

    def test_visibility_hidden_with_important(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<b style="visibility: hidden !important">losses and layoffs</b></h1>',
            "visibility:hidden",
        )

    def test_zero_opacity(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="opacity:0">losses and layoffs</span></h1>',
            "opacity",
        )

    def test_off_screen_position(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="position:absolute;left:-9999px">losses and layoffs</span></h1>',
            "off-screen",
        )

    def test_hidden_attribute(self):
        self.assert_hidden_text_caught(
            f"<h1>{VISIBLE_HEADLINE}<span hidden>losses and layoffs</span></h1>",
            "hidden attribute",
        )

    def test_class_rule_in_style_block(self):
        self.assert_hidden_text_caught(
            "<style>.note { display: none }</style>"
            f'<h1>{VISIBLE_HEADLINE}<span class="note">losses and layoffs</span></h1>',
            "display:none",
        )

    def test_screen_reader_only_clip_pattern(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="position:absolute;width:1px;height:1px;'
            f'overflow:hidden;clip:rect(0,0,0,0)">losses and layoffs</span></h1>',
            "clip",
        )

    def test_noscript_content(self):
        self.assert_hidden_text_caught(
            f"<h1>{VISIBLE_HEADLINE}<noscript>losses and layoffs</noscript></h1>",
            "noscript",
        )

    def test_comment_is_reported_as_medium(self):
        result = GUARD.analyze_html(f"<h1>{VISIBLE_HEADLINE}<!-- losses and layoffs --></h1>")
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(result.verdict, "review")

    def test_homoglyph_inside_visible_html_is_still_caught(self):
        result = GUARD.analyze_html("<h1><a href='/x'>Теsla</a> shares surge</h1>")
        self.assertEqual(result.clean_text, "Tesla shares surge")
        self.assertEqual(result.verdict, "quarantine")


ARTICLE_PAGE = (
    "<!doctype html><html><head><title>t</title><style>.note { display: none }</style></head>"
    "<body><nav>Markets | Tech</nav><article><h1>{headline}</h1><p>Body text.</p></article></body></html>"
)


class HeadlineElementTests(unittest.TestCase):
    def test_reads_only_the_headline_element_with_page_styles(self):
        page = ARTICLE_PAGE.replace(
            "{headline}", f'{VISIBLE_HEADLINE}<span class="note"> losses and layoffs</span>'
        )
        result = GUARD.analyze_html(page, headline_xpath="//h1")
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(len(hidden_text_flags(result)), 1)

    def test_headline_inside_hidden_container_is_all_hidden(self):
        page = (
            '<html><body><div style="display:none"><h1>Apple slumps on weak guidance</h1></div>'
            "<h2>Apple beats estimates</h2></body></html>"
        )
        result = GUARD.analyze_html(page, headline_xpath="//h1")
        self.assertEqual(result.clean_text, "")
        self.assertEqual(result.verdict, "quarantine")

    def test_missing_headline_element_is_flagged(self):
        result = GUARD.analyze_html("<html><body><p>No headline</p></body></html>", headline_xpath="//h1")
        self.assertEqual(result.flags[0].kind, "headline_not_found")


class ScrapedTextComparisonTests(unittest.TestCase):
    PAGE = ARTICLE_PAGE.replace("{headline}", f"{VISIBLE_HEADLINE}<span id='x'> losses and layoffs</span>")

    def scraper_flags(self, result):
        found_flags = []
        for flag in result.flags:
            if flag.kind == "scraper_text_differs":
                found_flags.append(flag)
        return found_flags

    def test_matching_scraper_output_adds_no_flag(self):
        page = ARTICLE_PAGE.replace("{headline}", "Apple <b>beats</b> estimates")
        result = GUARD.analyze_html(page, "//h1", scraped_text="Apple beats\n estimates")
        self.assertEqual(result.flags, [])

    def test_scraper_adding_text_the_guard_cannot_see_as_hidden_is_high(self):
        # The guard's own HTML check sees no hiding here (as with JavaScript or complex CSS),
        # but the scraper's text still differs from what the guard computed as visible.
        visible_page = ARTICLE_PAGE.replace("{headline}", "Apple beats estimates")
        result = GUARD.analyze_html(
            visible_page, "//h1", scraped_text="Apple beats estimates losses and layoffs"
        )
        flags = self.scraper_flags(result)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, "high")
        self.assertIn("losses and layoffs", flags[0].detail)

    def test_browser_dropping_text_the_guard_thought_visible_is_medium(self):
        # A browser that hid the span through a rule the guard cannot parse.
        result = GUARD.analyze_html(self.PAGE, "//h1", scraped_text=VISIBLE_HEADLINE)
        flags = self.scraper_flags(result)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, "medium")
        self.assertEqual(result.verdict, "review")


class ComparisonSeverityTests(unittest.TestCase):
    def test_guessed_background_is_not_escalated_by_the_comparison(self):
        # White headline, no declared background (often a dark theme in an external stylesheet).
        page = '<html><body><h1 style="color:#fff">Apple beats estimates</h1></body></html>'
        result = GUARD.analyze_html(page, "//h1", scraped_text="Apple beats estimates")
        self.assertEqual(result.verdict, "review")


class BrowserRenderedModeTests(unittest.TestCase):
    """Browser mode, with the browser's output supplied directly (no browser needed in unit tests)."""

    def test_browser_confirms_guessed_background_text_is_visible(self):
        page = '<html><body><h1 style="color:#fff">Apple beats estimates</h1></body></html>'
        result = GUARD.analyze_html(
            page, "//h1", scraped_text="Apple beats estimates", rendered_by_browser=True
        )
        self.assertEqual(result.flags, [])
        self.assertEqual(result.tickers, ["AAPL"])

    def test_text_hidden_by_rules_the_parser_cannot_read_is_high(self):
        page = (
            "<html><head><style>h1 > span.x { opacity: 0 }</style></head><body>"
            f'<h1>{VISIBLE_HEADLINE}<span class="x"> losses and layoffs</span></h1></body></html>'
        )
        result = GUARD.analyze_html(page, "//h1", scraped_text=VISIBLE_HEADLINE, rendered_by_browser=True)
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(hidden_text_flags(result)[0].original, "losses and layoffs")

    def test_homoglyph_in_browser_text_is_caught(self):
        page = "<html><body><h1>Теsla shares surge</h1></body></html>"
        result = GUARD.analyze_html(
            page, "//h1", scraped_text="Теsla shares surge", rendered_by_browser=True
        )
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.clean_text, "Tesla shares surge")

    def test_browser_mode_requires_browser_text(self):
        with self.assertRaises(ValueError):
            GUARD.analyze_html("<h1>x</h1>", "//h1", rendered_by_browser=True)


class VisibleMarkupTests(unittest.TestCase):
    def test_ordinary_styling_is_not_flagged(self):
        html = (
            '<div style="background:#ffffff"><h1 style="color:#111;font-size:28px">'
            '<span style="color:red">Tesla</span> shares <em>surge</em></h1>'
            '<p style="position:relative;left:-4px">after record deliveries</p></div>'
        )
        result = GUARD.analyze_html(html)
        self.assertEqual(result.flags, [])
        self.assertEqual(result.clean_text, "Tesla shares surge after record deliveries")
        self.assertEqual(result.tickers, ["TSLA"])

    def test_white_text_on_declared_dark_background_is_not_flagged(self):
        result = GUARD.analyze_html('<h1 style="background-color:#111827;color:#ffffff">Apple beats estimates</h1>')
        self.assertEqual(result.flags, [])

    def test_small_but_readable_text_is_not_flagged(self):
        result = GUARD.analyze_html('<h1>Apple beats estimates <small style="font-size:9px;opacity:0.6">Reuters</small></h1>')
        self.assertEqual(result.flags, [])

    def test_script_and_style_contents_are_ignored(self):
        html = (
            "<html><head><style>h1 { color: #222 }</style>"
            '<script type="application/ld+json">{"headline": "x"}</script></head>'
            "<body><h1>Apple beats estimates</h1></body></html>"
        )
        result = GUARD.analyze_html(html)
        self.assertEqual(result.flags, [])
        self.assertEqual(result.clean_text, "Apple beats estimates")


if __name__ == "__main__":
    unittest.main()
