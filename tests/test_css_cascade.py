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


if __name__ == "__main__":
    unittest.main()
