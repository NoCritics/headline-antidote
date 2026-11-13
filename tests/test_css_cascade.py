"""The real CSS cascade (needs tinycss2 and cssselect2, installed in the project virtual environment)."""

import importlib.util
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST

GUARD = HeadlineGuard(PAPER_WATCHLIST)
HEADLINE = "Alphabet shares surge after dodging antitrust breakup bullet"
CASCADE_AVAILABLE = (
    importlib.util.find_spec("tinycss2") is not None and importlib.util.find_spec("cssselect2") is not None
)


def page(css, span_attributes='class="x"', external_css=None):
    return (
        f"<html><head><style>{css}</style></head><body><article>"
        f"<h1>{HEADLINE}<span {span_attributes}> losses and layoffs</span></h1></article></body></html>"
    )


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class CascadeHidingTests(unittest.TestCase):
    def assert_hidden(self, html, stylesheets=None):
        result = GUARD.analyze_html(html, "//h1", stylesheets=stylesheets)
        self.assertEqual(result.clean_text, HEADLINE)
        self.assertEqual(result.verdict, "quarantine")

    def assert_visible(self, html, stylesheets=None):
        result = GUARD.analyze_html(html, "//h1", stylesheets=stylesheets)
        self.assertEqual(result.clean_text, HEADLINE + " losses and layoffs")
        self.assertEqual(result.verdict, "pass", result.flags)

    def test_child_combinator(self):
        self.assert_hidden(page("h1 > span.x { display: none }"))

    def test_descendant_selector_with_font_size(self):
        self.assert_hidden(page("article h1 span.x { font-size: 0 }"))

    def test_attribute_selector(self):
        self.assert_hidden(page('span[data-role="note"] { opacity: 0 }', 'data-role="note"'))

    def test_nth_child_selector(self):
        self.assert_hidden(page("h1 span:nth-child(1) { visibility: hidden }"))

    def test_css_variable(self):
        self.assert_hidden(page(":root { --gone: none } .x { display: var(--gone) }"))

    def test_css_variable_fallback(self):
        self.assert_hidden(page(".x { display: var(--undefined, none) }"))

    def test_media_query_for_desktop_screens(self):
        self.assert_hidden(page("@media screen and (min-width: 1024px) { .x { display: none } }"))

    def test_external_stylesheet_supplied_by_caller(self):
        self.assert_hidden(page(""), stylesheets=["h1 .x { position: absolute; left: -9999px }"])

    def test_important_beats_inline_style(self):
        self.assert_hidden(page(".x { display: none !important }", 'class="x" style="display:inline"'))

    def test_more_specific_rule_can_show_the_text_again(self):
        self.assert_visible(page(".x { display: none } h1 span.x { display: inline }"))

    def test_later_rule_of_equal_specificity_wins(self):
        self.assert_visible(page(".x { display: none } .x { display: inline }"))

    def test_inline_style_beats_stylesheet(self):
        self.assert_visible(page(".x { display: none }", 'class="x" style="display:inline"'))

    def test_mobile_only_rule_does_not_apply(self):
        self.assert_visible(page("@media (max-width: 600px) { .x { display: none } }"))

    def test_print_only_rule_does_not_apply(self):
        self.assert_visible(page("@media print { .x { display: none } }"))

    def test_dark_mode_rule_does_not_apply(self):
        self.assert_visible(page("@media (prefers-color-scheme: dark) { .x { display: none } }"))

    def test_hover_rule_does_not_apply(self):
        self.assert_visible(page("h1:hover .x { display: none }"))

    def test_white_on_white_from_stylesheets(self):
        self.assert_hidden(page("article { background: #ffffff } h1 .x { color: #fefefe }"))

    def test_white_text_on_dark_stylesheet_background_is_visible(self):
        self.assert_visible(page("body > article { background-color: #111827 } h1 .x { color: #ffffff }"))

    def test_unrelated_selector_does_not_hide(self):
        self.assert_visible(page("h2 > span.x { display: none }"))

    def test_has_selector(self):
        self.assert_hidden(page("h1:has(> span.x) > span { display: none }"))
        self.assert_visible(page("article:has(h2) span.x { display: none }"))

    def test_nth_last_child(self):
        self.assert_hidden(page("h1 > span:nth-last-child(1) { display: none }"))
        self.assert_visible(page("h1 > span:nth-last-child(2) { display: none }"))

    def test_sibling_combinators_skip_comments(self):
        def sibling_page(css):
            return (f"<html><head><style>{css}</style></head><body><article><h1>{HEADLINE}<i></i><!---->"
                    '<span class="x"> losses and layoffs</span></h1></article></body></html>')

        self.assert_hidden(sibling_page("i + span.x { display: none }"))
        self.assert_hidden(sibling_page("i ~ span { display: none }"))
        self.assert_hidden(sibling_page("h1 > span:nth-child(2):last-child { display: none }"))
        self.assert_visible(sibling_page("span + i { display: none } b ~ span { display: none }"))


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class StylesheetCacheTests(unittest.TestCase):
    """Compiled CSS is cached within a budget of source characters, with a site's external
    stylesheets kept apart from the pages' own <style> blocks."""

    def setUp(self):
        from headline_guard import css_cascade

        self.css_cascade = css_cascade
        self.saved_budgets = {}
        for cache in (css_cascade._external_stylesheets, css_cascade._external_rule_sets,
                      css_cascade._page_stylesheets, css_cascade._page_rule_sets):
            self.saved_budgets[id(cache)] = (cache, cache.budget)
            cache.clear()

    def tearDown(self):
        for cache, budget in self.saved_budgets.values():
            cache.budget = budget
            cache.clear()

    def test_oldest_entries_are_dropped_past_the_budget(self):
        cache = self.css_cascade._SizeBoundedCache(100)
        cache.store("a", "first", 60)
        cache.store("b", "second", 30)
        self.assertEqual(cache.lookup("a"), "first")  # now the most recently used
        cache.store("c", "third", 30)
        self.assertIsNone(cache.lookup("b"))
        self.assertEqual(cache.lookup("a"), "first")
        self.assertEqual(cache.lookup("c"), "third")
        self.assertEqual(cache.total_size, 90)

    def test_an_entry_larger_than_the_budget_is_still_kept(self):
        cache = self.css_cascade._SizeBoundedCache(100)
        cache.store("a", "small", 10)
        cache.store("b", "big", 500)
        self.assertIsNone(cache.lookup("a"))
        self.assertEqual(cache.lookup("b"), "big")

    def test_page_style_blocks_never_push_out_a_site_stylesheet(self):
        external_css = ["article h1 span.x { display: none }"]
        site_rules = self.css_cascade.external_rule_set(external_css)
        self.css_cascade._page_stylesheets.budget = 500
        self.css_cascade._page_rule_sets.budget = 500
        for page_number in range(70):  # more than the 64 entries the old shared cache had
            GUARD.analyze_html(page(f".unrelated-{page_number} {{ color: red; margin: {page_number}px }}" * 5),
                               "//h1", stylesheets=external_css)
        self.assertLessEqual(self.css_cascade._page_rule_sets.total_size, 500)
        self.assertIs(self.css_cascade.external_rule_set(external_css), site_rules)

    def test_prepared_stylesheets_are_used_by_the_next_article(self):
        external_css = ["article h1 span.x { display: none }"]
        unprepared = GUARD.analyze_html(page(""), "//h1", stylesheets=external_css)
        self.css_cascade._external_rule_sets.clear()
        GUARD.prepare_stylesheets(external_css)
        self.assertEqual(len(self.css_cascade._external_rule_sets), 1)
        prepared_rules = next(iter(self.css_cascade._external_rule_sets.values()))[0]
        prepared = GUARD.analyze_html(page(""), "//h1", stylesheets=external_css)
        self.assertEqual(len(self.css_cascade._external_rule_sets), 1)
        self.assertIs(self.css_cascade.external_rule_set(external_css), prepared_rules)
        self.assertEqual(prepared.clean_text, HEADLINE)
        self.assertEqual(prepared.clean_text, unprepared.clean_text)
        self.assertEqual(prepared.verdict, unprepared.verdict)


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class MediaQueryTests(unittest.TestCase):
    """Media queries answered as the verifying Chrome answers them: a 1366x900 desktop screen,
    light mode, pixel ratio 1, scripting on, no reduced motion or forced colors."""
    assert_hidden = CascadeHidingTests.assert_hidden
    assert_visible = CascadeHidingTests.assert_visible

    def media_page(self, query):
        return page(f"@media {query} {{ .x {{ display: none }} }}")

    def test_queries_that_match_the_desktop_screen_hide_text(self):
        for query in (
            "not print",
            "not all and (max-width: 600px)",
            "only screen and (min-width: 768px)",
            "(width >= 1024px)",
            "(400px <= width <= 1400px)",
            "(min-resolution: 1dppx)",
            "(min-resolution: 96dpi)",
            "(-webkit-min-device-pixel-ratio: 1)",
            "(prefers-reduced-motion: no-preference)",
            "(scripting: enabled)",
            "(forced-colors: none)",
            "(color)",
            "(min-device-width: 1024px)",
            "(min-aspect-ratio: 4/3)",
            "(max-width: 600px), (min-width: 1200px)",
            "(max-width: 600px) or (min-width: 1200px)",
            "not (max-width: 600px)",
            "screen and ((min-width: 1000px) and (orientation: landscape))",
        ):
            with self.subTest(query=query):
                self.assert_hidden(self.media_page(query))

    def test_queries_that_miss_the_desktop_screen_leave_text_visible(self):
        for query in (
            "not all and (min-width: 768px)",
            "not screen",
            "(width < 768px)",
            "(400px <= width <= 700px)",
            "(-webkit-min-device-pixel-ratio: 2)",
            "(min-resolution: 192dpi)",
            "(prefers-reduced-motion: reduce)",
            "(scripting: none)",
            "(forced-colors: active)",
            "(-ms-high-contrast: active)",
            "(--mobile-only-viewport)",
            "(max-device-width: 1024px)",
            "handheld",
            "tv and (min-width: 100px)",
            "(max-width: 600px) and (min-width: 1200px)",
            "not (min-width: 600px)",
            "(color: 48842621)",
            "screen and (min-width: calc(100px + 2000px))",
        ):
            with self.subTest(query=query):
                self.assert_visible(self.media_page(query))

    def test_malformed_queries_are_read_as_chrome_reads_them(self):
        # Each expectation is Chrome's matchMedia answer at the browser check's viewport.
        from headline_guard.media_queries import media_query_applies

        for query, chrome_answer in (
            ("screen and(min-width: 1px)", False),
            ("not(max-width: 600px)", False),
            ("(min-width: 1px)and (orientation: landscape)", True),
            ("(min-width: 1px) and(orientation: landscape)", False),
            ("(400px <= width >= 100px)", False),
            ("(2000px >= width <= 3000px)", False),
            ("(100px < width < 2000px)", True),
            ("(min-width: 1px)), screen", True),
            ("screen, (min-width: 1px", True),
            ("((min-width: 1px)", True),
            ("(min-width: 1px)) and (orientation: landscape)", False),
            # CSS white space and case folding are ASCII only.
            ("not print", False),
            ("screen and (min-width: 1px)", False),
            ("(min-width: 1px )", False),
            ("not (prefers-color-scheme: darK)", False),
            ("SCREEN AND (MIN-WIDTH: 1PX)", True),
            ("screen\nand\n(min-width: 1px)", True),
            ("(min-width: 1px) or (é)", True),
            # A value a known feature can't take drops the whole query, even under 'not'.
            ("not (prefers-color-scheme: blue)", False),
            ("not (orientation: sideways)", False),
            ("not (scripting: initial-only)", True),
            ("not (-ms-high-contrast: active)", False),
            # A value Chrome doesn't know makes its condition unknown, not the query invalid.
            ("(min-width: 1px) or (prefers-color-scheme: blue)", True),
            ("not (display-mode: tabbed)", True),
            ("not (inverted-colors: none)", False),
            ("not (scan: progressive)", True),
            ("(horizontal-viewport-segments >= 1)", True),
            ("(min-horizontal-viewport-segments: 1)", False),
        ):
            with self.subTest(query=query):
                self.assertEqual(media_query_applies(query), chrome_answer)

    def test_deep_nesting_is_evaluated_like_chrome(self):
        from headline_guard.media_queries import media_query_applies

        for depth in (1000, 20000):
            self.assertTrue(media_query_applies("(" * depth + "min-width: 1px" + ")" * depth))
            self.assertFalse(media_query_applies("not (" * depth + "max-width: 1px" + ")" * depth))
            self.assertTrue(media_query_applies("not (" * (depth + 1) + "max-width: 1px" + ")" * (depth + 1)))

    def test_style_element_media_attribute(self):
        self.assert_hidden(page(".x { display: none }").replace("<style>", '<style media="not print">'))
        self.assert_visible(page(".x { display: none }").replace("<style>", '<style media="(width < 600px)">'))


if __name__ == "__main__":
    unittest.main()
