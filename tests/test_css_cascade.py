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



# Rules inside at-rules and nested style rules, with Chrome's answer: True when the span is hidden.
# AtRuleChromeTests in test_browser_check.py checks every answer against the installed Chrome.
# Each case: (css, the span's inline style, hidden in Chrome).
CHROME_DECIDED_CASES = (
    # Chrome never applies @document.
    (".x{display:none} @document url-prefix(){.x{display:inline}}", "", True),
    # Cascade layers: unlayered rules beat layered ones, later layers beat earlier ones, and
    # !important reverses both. Layer order comes before specificity.
    (".x{display:none} @layer a{.x{display:inline}}", "", True),
    (".x{display:inline} @layer a{.x{display:none}}", "", False),
    ("@layer a{.x{display:none}} .x{display:inline}", "", False),
    ("@layer a{#x{display:inline}} .x{display:none}", "", True),
    ("@layer a{.x{display:none}} @layer b{.x{display:inline}}", "", False),
    ("@layer b, a; @layer a{.x{display:none}} @layer b{.x{display:inline}}", "", True),
    ("@layer a{.x{display:none !important}} .x{display:inline !important}", "", True),
    ("@layer a{.x{display:inline !important}} .x{display:none !important}", "", False),
    ("@layer a{.x{display:none !important}}", "display:inline !important", False),
    ("@layer a{.x{display:inline}} @layer b{.x{display:none}} @layer a{#x{display:inline}}", "", True),
    ("@layer a{.x{display:inline} @layer b{#x{display:none}}}", "", False),
    ("@layer a{@layer b{.x{display:none}} .x{display:inline}}", "", False),
    ("@layer a{@layer b{.x{display:none !important}} .x{display:inline !important}}", "", True),
    ("@layer a.b{.x{display:none}} @layer a{.x{display:inline}}", "", False),
    ("@layer{.x{display:inline}} .x{display:none}", "", True),
    ("@media screen{@layer a{.x{display:inline}}} .x{display:none}", "", True),
    # A layer named only inside a block that does not apply takes no place in the order.
    ("@media print{@layer a{.y{color:red}}} @layer b{.x{display:none}} @layer a{.x{display:inline}}", "", False),
    # revert-layer takes the value the layers below give.
    ("@layer a{.x{display:none}} .x{display:revert-layer}", "", True),
    ("@layer a{.x{display:none}} @layer b{.x{display:revert-layer}}", "", True),
    # Variables defined in a layer lose to unlayered definitions, like any declaration.
    (":root{--d:none} @layer b{:root{--d:inline}} .x{display:var(--d)}", "", True),
    (":root{--d:none} @supports (bogus:1){@layer b{}} @layer b{:root{--d:inline}} .x{display:var(--d)}", "", True),
    # A scope root that matches nothing.
    ("@scope (.b){.x{display:none}}", "", False),
    # Nested style rules: a nested selector without & is a descendant of its parent.
    (".a{.x{display:none}}", "", True),
    (".a{& .x{display:none}}", "", True),
    ("h1{> .x{display:none}}", "", True),
    (".b{.x{display:none}}", "", False),
    (".x{display:none} .a{.x{display:inline}}", "", False),
    (".a{@media screen{.x{display:none}}}", "", True),
    (".a{@media print{.x{display:none}}}", "", False),
    (".x{display:none; .q{color:red} display:inline}", "", False),
    (".a{.x{display:none} #x{display:inline}}", "", False),
    # Math functions and the parentheses inside them nest at most 100 deep: deeper, Chrome drops
    # the declaration.
    (".x{opacity:" + "calc(" * 100 + "0" + ")" * 100 + "}", "", True),
    (".x{opacity:" + "calc(" * 101 + "0" + ")" * 101 + "}", "", False),
    (".x{opacity:calc(" + "(" * 99 + "0" + ")" * 99 + ")}", "", True),
    (".x{opacity:calc(" + "(" * 100 + "0" + ")" * 100 + ")}", "", False),
    (".x{opacity:" + "min(" * 3000 + "0" + ")" * 3000 + "}", "", False),
)

# Blocks whose condition this reader cannot answer the way Chrome does (@supports, @container,
# @scope, whose rules Chrome ranks by the scope root's nearness): Chrome may apply any of them, so
# text that some combination of them hides counts as hidden. Each of these is hidden under at least
# one combination of the blocks' conditions (most of them in Chrome itself, which this does not check).
UNDECIDED_BLOCK_CASES = (
    "@scope (.a){.x{display:none}}",
    "@scope (.a){:scope .x{display:none}}",
    "@scope (h1){:scope > .x{display:none}}",
    "@scope (.a){.x{display:none}} .x{display:inline}",
    "@scope (h1){.x{display:none}} @scope (.a){.x{display:inline}}",
    "@scope (.a){:scope .x{display:none}} .a .x{display:inline}",
    "@supports (display:block){.x{display:none}} @supports (bogus:1){.x{display:inline}}",
    ".x{height:0} @supports (display:block){.x{overflow:hidden}} @supports (bogus:1){.x{height:auto}}",
    ":root{--d:none} @supports (bogus:1){:root{--d:inline}} .x{display:var(--d)}",
    "@supports (bogus:1){@layer b{}} @layer a{.x{display:inline}} @layer b{.x{display:none}}",
    "@supports (display:block){:root{--d:none}} @supports (bogus:1){:root{--d:inline}} .x{display:var(--d)}",
    ":root{--d:inline} @supports (display:block){:root{--d:none}} .x{display:var(--d)}",
    # Two variables, each set by its own pair of blocks: only the mixed combination hides.
    ":root{--a:8px;--b:8px} @supports (display:block){:root{--a:0px}} @supports (bogus:1){:root{--a:8px}} "
    "@supports (display:block){:root{--b:0px}} @supports (bogus:1){:root{--b:8px}} "
    ".x{font-size:calc(var(--a) + var(--b))}",
    # A decided variable that refers to one an undecided block sets.
    ":root{--b:16px} @supports (display:block){:root{--b:0px}} @supports (bogus:1){:root{--b:16px}} "
    ":root{--a:var(--b)} .x{font-size:var(--a)}",
    ".x{display:none} @supports (bogus:1){.x{display:inline}}",
    ".x{display:none} @supports not (display:block){.x{display:inline}}",
    ".x{display:none} @supports (display:bogus){.x{display:inline}}",
    ".x{display:none} @container (min-width:1px){.x{display:inline}}",
    ".x{display:none} @scope (.a) to (h1){.x{display:inline}}",
    ".x{display:none} @supports (bogus:1){@layer a{.x{display:inline}}}",
    "@supports (display:block){.x{display:none}}",
    "@container (min-width:0px){.x{display:none}}",
)


def at_rule_page(css, inline_style=""):
    style_attribute = f' style="{inline_style}"' if inline_style else ""
    return (
        f"<html><head><style>{css}</style></head><body><article class=\"a\">"
        f"<h1>{HEADLINE}<span class=\"x\" id=\"x\"{style_attribute}> losses and layoffs</span></h1>"
        "</article></body></html>"
    )


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class AtRuleTests(unittest.TestCase):
    assert_hidden = CascadeHidingTests.assert_hidden
    assert_visible = CascadeHidingTests.assert_visible

    def test_rules_read_as_chrome_reads_them(self):
        for css, inline_style, hidden in CHROME_DECIDED_CASES:
            with self.subTest(css=css, inline_style=inline_style):
                if hidden:
                    self.assert_hidden(at_rule_page(css, inline_style))
                else:
                    self.assert_visible(at_rule_page(css, inline_style))

    def test_undecided_blocks_never_show_hidden_text_again(self):
        for css in UNDECIDED_BLOCK_CASES:
            with self.subTest(css=css):
                self.assert_hidden(at_rule_page(css))

    def test_any_subset_of_undecided_blocks_may_apply(self):
        """For each way of hiding text: whether each declaration sits bare or inside a block that
        applies in Chrome, and whatever blocks Chrome skips try to cancel it, the text stays hidden
        whenever this reader hides the CSS Chrome really applies (true blocks unwrapped, false ones
        deleted)."""
        recipes = (
            (("display", "none", "inline"),),
            (("visibility", "hidden", "visible"),),
            (("opacity", "0", "1"),),
            (("font-size", "0", "16px"),),
            (("transform", "scale(0)", "none"),),
            (("height", "0", "auto"), ("overflow", "hidden", "visible")),
            (("position", "absolute", "static"), ("left", "-9999px", "0")),
            (("position", "absolute", "static"), ("clip", "rect(0 0 0 0)", "auto")),
        )
        true_block = "@supports (display:block)"
        false_blocks = ("@supports (bogus:1)", "@supports not (display:block)", "@container (min-width:1px)")
        for recipe in recipes:
            flattened = ".x{"
            for name, value, _ in recipe:
                flattened += f"{name}:{value};"
            flattened += "}"
            result = GUARD.analyze_html(at_rule_page(flattened), "//h1")
            self.assertEqual(result.clean_text, HEADLINE, flattened)
            for wrapped_mask in range(2 ** len(recipe)):
                for false_block in false_blocks:
                    css = ""
                    for position, (name, value, cancel) in enumerate(recipe):
                        if wrapped_mask & (1 << position):
                            css += f"{true_block}{{.x{{{name}:{value}}}}} "
                        else:
                            css += f".x{{{name}:{value}}} "
                        css += f"{false_block}{{.x{{{name}:{cancel}}}}} "
                    with self.subTest(css=css):
                        result = GUARD.analyze_html(at_rule_page(css), "//h1")
                        self.assertEqual(result.clean_text, HEADLINE)

    def test_overlay_cancelled_only_in_a_block_chrome_skips_still_covers(self):
        html = (
            "<html><head><style>.cover{position:absolute;inset:0;background:#fff} "
            "@supports (bogus:1){.cover{position:static}}</style></head><body><article>"
            f"<h1>{HEADLINE}<span style=\"position:relative\"> losses and layoffs"
            "<span class=\"cover\"></span></span></h1></article></body></html>"
        )
        self.assertEqual(GUARD.analyze_html(html, "//h1").clean_text, HEADLINE)

    def test_overlay_split_between_undecided_blocks_still_covers(self):
        html = (
            "<html><head><style>.cover{position:absolute;inset:0} "
            "@supports (display:block){.cover{background:#fff}} @supports (bogus:1){.cover{position:static}}"
            "</style></head><body><article>"
            f"<h1>{HEADLINE}<span style=\"position:relative\"> losses and layoffs"
            "<span class=\"cover\"></span></span></h1></article></body></html>"
        )
        self.assertEqual(GUARD.analyze_html(html, "//h1").clean_text, HEADLINE)

    def test_selector_lists_nested_many_levels_deep_are_read_quickly(self):
        import time

        css = ".a, .b, .c {" * 10 + ".x { display: none }" + "}" * 10
        started = time.perf_counter()
        GUARD.analyze_html(at_rule_page(css), "//h1")
        self.assertLess(time.perf_counter() - started, 2)

    def test_many_undecided_variables_are_read_quickly(self):
        import time

        definitions = ""
        uses = ""
        for number in range(40):
            definitions += f"@supports (display:block){{:root{{--v{number}:1}}}} @supports (bogus:1){{:root{{--v{number}:2}}}} "
            uses += f"var(--v{number}) "
        css = definitions + ".x{opacity:calc(" + "+".join(uses.split()) + ")}"
        started = time.perf_counter()
        GUARD.analyze_html(at_rule_page(css), "//h1")
        self.assertLess(time.perf_counter() - started, 5)

    def test_converging_variable_chains_are_read_quickly(self):
        import time

        css = ""
        for level in range(10):
            for variant in range(4):
                css += f"@supports (display:block){{:root{{--v{level}:var(--v{level + 1},{variant})}}}} "
        css += ":root{--v10:1} .x{opacity:var(--v0)}"
        started = time.perf_counter()
        GUARD.analyze_html(at_rule_page(css), "//h1")
        self.assertLess(time.perf_counter() - started, 1)

    def test_layers_order_across_external_and_page_stylesheets(self):
        external_css = "@layer b, a; @layer a{.x{display:none}}"
        self.assert_hidden(at_rule_page("@layer b{.x{display:inline}}"), stylesheets=[external_css])
        self.assert_visible(at_rule_page("@layer a{.x{display:inline}}"), stylesheets=["@layer a{.x{display:none}}"])

    def test_layer_order_of_one_page_does_not_leak_into_the_next(self):
        page_css = "@layer a{.x{display:none}} @layer b{.x{display:inline}}"
        self.assert_hidden(at_rule_page(page_css), stylesheets=["@layer b, a;"])
        self.assert_visible(at_rule_page(page_css), stylesheets=["@layer a, b;"])

    def test_body_paragraph_shown_again_from_an_undecided_block_stays_out_of_the_body(self):
        if importlib.util.find_spec("trafilatura") is None:
            self.skipTest("trafilatura not installed")
        css = ".tip{display:none} @supports (bogus:1){.tip{display:block}}"
        paragraphs = ""
        for sentence in (
            "Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order a breakup.",
            "The decision lifted other large technology stocks as investors bet regulators would struggle.",
            "Analysts said the ruling removes a major overhang that had weighed on the shares all year.",
        ):
            paragraphs += f"<p>{sentence} {sentence}</p>"
        html = (
            f"<!doctype html><html><head><title>{HEADLINE}</title><style>{css}</style></head><body><article>"
            f"<h1>{HEADLINE}</h1>{paragraphs}<p class=\"tip\">Insiders expect mass layoffs and a profit "
            "warning next quarter.</p></article></body></html>"
        )
        article = GUARD.extract_article(html)
        self.assertIn("Alphabet rose sharply", article.body)
        self.assertNotIn("mass layoffs", article.body)


def nested(opening, middle, closing, depth):
    return opening * depth + middle + closing * depth


# Selectors this deep are read as Chrome reads them; deeper ones are not (see DeepNestingTests).
SELECTOR_DEPTH_READ_EXACTLY = 32


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class DeepNestingTests(unittest.TestCase):
    """CSS nested thousands of levels deep must neither crash the reader nor let hidden text through."""

    assert_hidden = CascadeHidingTests.assert_hidden

    def assert_payload_not_passed(self, html):
        result = GUARD.analyze_html(html, "//h1")
        self.assertNotIn("losses and layoffs", result.clean_text)
        self.assertNotEqual(result.verdict, "pass")

    def test_a_selector_nested_too_deep_to_read_hides_the_payload(self):
        for depth in (300, 3000):
            with self.subTest(depth=depth):
                self.assert_payload_not_passed(at_rule_page(nested(":is(", ".x", ")", depth) + "{display:none}"))

    def test_a_selector_at_the_reading_depth_is_read_exactly(self):
        self.assert_hidden(at_rule_page(nested(":is(", ".x", ")", SELECTOR_DEPTH_READ_EXACTLY) + "{display:none}"))

    def test_nested_rules_whose_selectors_compose_too_deep_hide_the_payload(self):
        levels = 8
        css = nested(":is(", ".x", ")", 30) + "{"
        for _ in range(levels - 1):
            css += nested(":is(", "&", ")", 30) + "{"
        css += "display:none" + "}" * levels
        self.assert_payload_not_passed(at_rule_page(css))

    def test_a_scope_root_nested_too_deep_hides_the_payload(self):
        root = nested(":is(", "article", ")", 300)
        self.assert_payload_not_passed(at_rule_page("@scope (" + root + "){.x{display:none}}"))

    def test_values_and_preludes_nested_thousands_deep_are_read(self):
        deep_value = nested("f(", "1", ")", 3000)
        deep_parentheses = nested("(", "screen", ")", 3000)
        for css in (
            ".x{display:none;--a:" + deep_value + "}",
            ".x{display:none;transform:" + deep_value + "}",
            ".x{display:none} @media " + deep_parentheses + "{.y{color:red}}",
            ".x{display:none} @layer " + deep_parentheses + "{.y{color:red}}",
            ".x{display:none} @font-face{font-family:f;src:" + deep_value + "}",
        ):
            with self.subTest(css=css[:40]):
                self.assert_hidden(at_rule_page(css))

    def test_an_inline_style_nested_thousands_deep_is_read(self):
        self.assert_hidden(at_rule_page("", "display:none;--a:" + nested("f(", "1", ")", 3000)))

    def test_the_reader_writes_css_back_exactly_as_tinycss2_does(self):
        import tinycss2

        from headline_guard.css_cascade import _serialized

        for css in (
            "a/**/b", "a /**/ b", "#x/**/y", "1/**/px", "-/**/a", "@x/**/-", "a/**/-->", "./**/1",
            "f(", 'f("abc', 'f(g(h("abc', 'f(g("x"), "abc', 'f(g("x") h("abc', 'f(g(), "a', "f()",
            "calc(1px + (2px * 3))", "[data-a=b] (x) {y: z}", "{[(f(1))]}", "a\\", "a\\\nb", "\\",
            "url(x.png) url( 'y' )", "U+0-7F", "12px-a", "#id.cls:is(.a, .b)::before", "!important",
            "var(--a, var(--b, 0))", '"unterminated', "<!-- -->", "a,b;c:d", ")]",
        ):
            for skip_comments in (True, False):
                with self.subTest(css=css, skip_comments=skip_comments):
                    tokens = tinycss2.parse_component_value_list(css, skip_comments=skip_comments)
                    self.assertEqual(_serialized(tokens), tinycss2.serialize(tokens))


if __name__ == "__main__":
    unittest.main()
