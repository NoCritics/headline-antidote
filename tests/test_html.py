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
    def assert_hidden_text_caught(self, html, cause, css=None):
        result = GUARD.analyze_html(html)
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(result.verdict, "quarantine")
        flags = hidden_text_flags(result)
        self.assertEqual(len(flags), 1, result.flags)
        self.assertEqual(flags[0].original, "losses and layoffs")
        self.assertEqual(flags[0].evidence, {"cause": cause} if css is None else {"cause": cause, "css": css})

    def test_paper_display_none(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="display:none"> losses and layoffs</span></h1>',
            "display_none", "display:none",
        )

    def test_paper_zero_font_size(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="font-size: 0pt"> losses and layoffs</span></h1>',
            "tiny_font", "font-size:0pt",
        )

    def test_text_color_matches_background(self):
        self.assert_hidden_text_caught(
            f'<h1 style="background-color:#fff">{VISIBLE_HEADLINE}'
            f'<span style="color: white"> losses and layoffs</span></h1>',
            "same_color_as_background", "color:white",
        )

    def test_near_background_color(self):
        self.assert_hidden_text_caught(
            f'<h1 style="background:#ffffff">{VISIBLE_HEADLINE}'
            f'<span style="color:#fefefe">losses and layoffs</span></h1>',
            "same_color_as_background", "color:#fefefe",
        )

    def test_tiny_font_size(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="font-size:1px">losses and layoffs</span></h1>',
            "tiny_font", "font-size:1px",
        )

    def test_near_zero_opacity(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="opacity:0.01">losses and layoffs</span></h1>',
            "transparent", "opacity:0.01",
        )

    def test_near_transparent_rgba_text(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="color:rgba(0,0,0,0.02)">losses and layoffs</span></h1>',
            "transparent", "color:rgba(0,0,0,0.02)",
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
        self.assertEqual(flags[0].severity, "medium")
        self.assertEqual(flags[0].evidence, {"cause": "same_color_as_background", "css": "color:#fff"})

    def test_visibility_hidden_with_important(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<b style="visibility: hidden !important">losses and layoffs</b></h1>',
            "visibility_hidden", "visibility:hidden",
        )

    def test_zero_opacity(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="opacity:0">losses and layoffs</span></h1>',
            "transparent", "opacity:0",
        )

    def test_off_screen_position(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="position:absolute;left:-9999px">losses and layoffs</span></h1>',
            "off_screen", "left:-9999px",
        )

    def test_hidden_attribute(self):
        self.assert_hidden_text_caught(
            f"<h1>{VISIBLE_HEADLINE}<span hidden>losses and layoffs</span></h1>",
            "hidden_attribute",
        )

    def test_class_rule_in_style_block(self):
        self.assert_hidden_text_caught(
            "<style>.note { display: none }</style>"
            f'<h1>{VISIBLE_HEADLINE}<span class="note">losses and layoffs</span></h1>',
            "display_none", "display:none",
        )

    def test_screen_reader_only_clip_pattern(self):
        self.assert_hidden_text_caught(
            f'<h1>{VISIBLE_HEADLINE}<span style="position:absolute;width:1px;height:1px;'
            f'overflow:hidden;clip:rect(0,0,0,0)">losses and layoffs</span></h1>',
            "clipped", "clip:rect(0,0,0,0)",
        )

    def test_noscript_content(self):
        self.assert_hidden_text_caught(
            f"<h1>{VISIBLE_HEADLINE}<noscript>losses and layoffs</noscript></h1>",
            "not_rendered_element",
        )

    def test_comment_is_reported_as_medium(self):
        result = GUARD.analyze_html(f"<h1>{VISIBLE_HEADLINE}<!-- losses and layoffs --></h1>")
        self.assertEqual(result.clean_text, VISIBLE_HEADLINE)
        self.assertEqual(result.verdict, "review")

    def test_homoglyph_inside_visible_html_is_still_caught(self):
        result = GUARD.analyze_html("<h1><a href='/x'>Теsla</a> shares surge</h1>")
        self.assertEqual(result.clean_text, "Tesla shares surge")
        self.assertEqual(result.verdict, "quarantine")


HIDING_CAUSES = (
    # (html around the payload, cause, css); every hiding method in the spec's Causes table.
    ('<span style="display:none">{p}</span>', "display_none", "display:none"),
    ('<span style="content-visibility:hidden">{p}</span>', "content_visibility_hidden", "content-visibility:hidden"),
    ('<span style="visibility:collapse">{p}</span>', "visibility_hidden", "visibility:collapse"),
    ('<span style="opacity:0">{p}</span>', "transparent", "opacity:0"),
    ('<span style="filter:opacity(0)">{p}</span>', "transparent", "filter:opacity(0)"),
    ('<span style="color:rgb(0 0 0 / 0)">{p}</span>', "transparent", "color:rgb(0 0 0 / 0)"),
    ('<span style="filter:blur(20px)">{p}</span>', "blurred", "filter:blur(20px)"),
    ('<span style="font-size:0">{p}</span>', "tiny_font", "font-size:0"),
    ('<span style="font:0/0 a">{p}</span>', "tiny_font", "font:0/0 a"),
    ('<span style="letter-spacing:-1em">{p}</span>', "letters_stacked", "letter-spacing:-1em"),
    ('<span style="color:#fff;background:#fff">{p}</span>', "same_color_as_background", "color:#fff"),
    ('<span style="clip:rect(0 0 0 0)">{p}</span>', "clipped", "clip:rect(0 0 0 0)"),
    ('<span style="clip-path:inset(50%)">{p}</span>', "clipped", "clip-path:inset(50%)"),
    ('<span style="display:inline-block;line-height:0;overflow:hidden">{p}</span>', "clipped",
     "line-height:0; overflow:hidden"),
    ('<span style="width:0;overflow:hidden">{p}</span>', "clipped", "width:0; overflow:hidden"),
    ('<span style="transform:scale(0)">{p}</span>', "scaled_to_zero", "transform:scale(0)"),
    ('<span style="scale:0">{p}</span>', "scaled_to_zero", "scale:0"),
    ('<span style="position:absolute;left:-9999px">{p}</span>', "off_screen", "left:-9999px"),
    ('<span style="display:inline-block;transform:translateX(-9999px)">{p}</span>', "off_screen",
     "transform:translatex(-9999px)"),
    ('<span style="display:inline-block;translate:-9999px">{p}</span>', "off_screen", "translate:-9999px"),
    ('<span style="text-indent:-9999px">{p}</span>', "off_screen", "text-indent:-9999px"),
    ('<span style="display:inline-block;width:1px;height:1px;overflow:hidden">{p}</span>', "screen_reader_only",
     "width:1px; overflow:hidden"),
    ('<span style="position:relative">{p}<i style="position:absolute;inset:0;background:#fff"></i></span>',
     "covered", None),
    ('<span style="background:#fff"><span style="position:relative;z-index:-1">{p}</span></span>',
     "behind_background", "z-index:-1"),
    ('<details><summary></summary>{p}</details>', "closed_details", None),
    ('<template>{p}</template>', "not_rendered_element", None),
    ('<span hidden>{p}</span>', "hidden_attribute", None),
    ('<svg><title>{p}</title></svg>', "svg_not_drawn", None),
    ('<svg width="0" height="50"><text x="0" y="20">{p}</text></svg>', "svg_not_drawn", None),
    ('<svg width="300" height="50"><text x="0" y="20" fill="none">{p}</text></svg>', "svg_not_painted", None),
    ('<svg width="300" height="50"><text x="10" y="0">{p}</text></svg>', "svg_off_drawing", None),
    # An enclosing element's cause, and its rule, belong to the text inside it.
    ('<div style="display:none"><span>{p}</span></div>', "display_none", "display:none"),
)


class HidingCauseTests(unittest.TestCase):
    """Each hiding method reports its cause and, when a CSS rule hides the text, the rule."""

    def test_each_method_names_its_cause_and_rule(self):
        for template, cause, css in HIDING_CAUSES:
            with self.subTest(template=template):
                html = f"<h1>{VISIBLE_HEADLINE}{template.format(p=' losses and layoffs')}</h1>"
                flags = hidden_text_flags(GUARD.analyze_html(html))
                self.assertEqual(len(flags), 1, html)
                self.assertEqual(flags[0].evidence, {"cause": cause} if css is None else {"cause": cause, "css": css})

    def test_an_enclosing_element_gives_its_cause_to_a_whole_headline(self):
        html = '<html><body><div style="display:none"><h1>Apple slumps</h1></div></body></html>'
        [flag] = hidden_text_flags(GUARD.analyze_html(html, headline_xpath="//h1"))
        self.assertEqual(flag.evidence, {"cause": "display_none", "css": "display:none"})

    def test_css_this_reader_cannot_evaluate_is_its_own_cause(self):
        # Too many @supports rules for the reader to try each combination.
        rules = " ".join(f"@supports (x{number}: 1) {{ .k {{ display: block }} }}" for number in range(12))
        html = f'<style>{rules}</style><h1>{VISIBLE_HEADLINE}<span class="k"> losses and layoffs</span></h1>'
        flags = hidden_text_flags(GUARD.analyze_html(html))
        self.assertEqual([flag.evidence for flag in flags], [{"cause": "css_not_evaluated"}])


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
        self.assertEqual(flags[0].evidence, {"added_text": "losses and layoffs"})

    def test_browser_dropping_text_the_guard_thought_visible_is_medium(self):
        # A browser that hid the span through a rule the guard cannot parse.
        result = GUARD.analyze_html(self.PAGE, "//h1", scraped_text=VISIBLE_HEADLINE)
        flags = self.scraper_flags(result)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].severity, "medium")
        self.assertEqual(flags[0].evidence, {"dropped_text": "losses and layoffs"})
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
