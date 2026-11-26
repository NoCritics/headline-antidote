"""Hostile input: values and page shapes that must neither raise out of the public API nor hang it."""

import importlib.util
import unittest

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST

GUARD = HeadlineAntidote(PAPER_WATCHLIST)
CASCADE_AVAILABLE = (
    importlib.util.find_spec("tinycss2") is not None and importlib.util.find_spec("cssselect2") is not None
)


def white_page_headline(span_style):
    return (f'<html><body style="background:#fff"><article><h1>Tesla shares surge'
            f'<span style="{span_style}"> losses and layoffs</span></h1></article></body></html>')


class HugeColorNumberTests(unittest.TestCase):
    def test_huge_oklab_and_oklch_numbers_do_not_raise(self):
        for style in ("color:oklab(1e200 0 0)", "color:oklab(0.5 1e200 0)", "color:oklch(0 0 1e400)",
                      "color:oklch(0.5 1e200 1e200)", "color:oklch(0.5 0.1 1e400)"):
            with self.subTest(style=style):
                GUARD.analyze_html(white_page_headline(style), "//h1")
                GUARD.extract_article(white_page_headline(style))

    def test_a_huge_hue_is_hue_zero(self):
        # Measured in Chrome 158: each of these computes to the colour with hue 0.
        from headline_antidote.css_values import parse_color

        for function, rest in (("oklch", "0.7 0.2"), ("hsl", "100% 50%"), ("hwb", "10% 10%")):
            hue_zero = parse_color(f"{function}(0 {rest})" if function != "oklch" else f"oklch({rest} 0)")
            for hue in ("1e400", "1e200", "-1e400"):
                value = f"{function}({hue} {rest})" if function != "oklch" else f"oklch({rest} {hue})"
                with self.subTest(value=value):
                    self.assertEqual(parse_color(value), hue_zero)

    def test_oklab_lightness_past_100_percent_is_white(self):
        # CSS Color 4 clamps oklab()/oklch() lightness to 0-100% when the value is parsed.
        for style in ("color:oklab(1e200 0 0)", "color:oklch(1e200 0 0)", "color:oklch(1 0 1e400)"):
            with self.subTest(style=style):
                result = GUARD.analyze_html(white_page_headline(style), "//h1")
                self.assertNotIn("losses", result.clean_text)
                self.assertEqual(result.verdict, "quarantine")


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class TooLongNumberInStylesheetTests(unittest.TestCase):
    def test_prepare_stylesheets_does_not_raise_and_the_article_is_left_to_the_browser(self):
        stylesheets = [".x { width: " + "9" * 5000 + "px }"]
        GUARD.prepare_stylesheets(stylesheets)
        article = GUARD.extract_article(white_page_headline("color:red"), stylesheets=stylesheets)
        self.assertIn("page_too_complex_to_read", [flag.kind for flag in article.flags])
        self.assertTrue(article.needs_browser_check)


def nested_divs_page(css, depth):
    return (f"<html><head><style>{css}</style></head><body><article>" + "<div>" * depth
            + "<h1>Tesla shares surge<span> losses and layoffs</span></h1>" + "</div>" * depth
            + "</article></body></html>")


@unittest.skipUnless(CASCADE_AVAILABLE, "tinycss2 and cssselect2 not installed")
class NestedHasTests(unittest.TestCase):
    """Chrome drops a :has() inside :has() (measured in Chrome 158): the whole rule, or, inside a
    forgiving :is() or :where(), only that selector."""

    def test_deeply_nested_has_is_read_quickly(self):
        import time

        depth = 25
        selector = "div:" + "has(div:" * (depth - 1) + "has(b)" + ")" * (depth - 1)  # no <b>: every level is searched
        started = time.perf_counter()
        GUARD.extract_article(nested_divs_page(selector + " { display: none }", depth))
        self.assertLess(time.perf_counter() - started, 2)

    def test_a_rule_with_has_inside_has_is_dropped(self):
        for selector in ("h1:has(span:has(b)) span", "h1:has(span:not(:has(i))) span",
                         "h1:has(span), h1:has(span:has(b)) span"):
            with self.subTest(selector=selector):
                html = (f"<style>{selector} {{ display: none }}</style><article><h1>Tesla shares surge"
                        f"<span> losses <b>and</b> layoffs</span></h1></article>")
                self.assertIn("losses", GUARD.analyze_html(html, "//h1").clean_text)

    def test_inside_is_only_the_selector_with_has_is_dropped(self):
        html = ('<style>h1:has(span:is(.x, :has(b))) span.x { display: none }</style><article><h1>'
                'Tesla shares surge<span class="x"> losses <b>and</b> layoffs</span></h1></article>')
        result = GUARD.analyze_html(html, "//h1")
        self.assertNotIn("losses", result.clean_text)
        self.assertEqual(result.verdict, "quarantine")

    def test_a_dropped_selector_no_longer_counts_toward_specificity(self):
        # Chrome reads the second rule as h1 span:is(.x), which loses to h1 span.x.y.
        html = ("<style>h1 span.x.y { display: inline } h1 span:is(#zz:has(b:has(i)), .x) { display: none }"
                '</style><article><h1>Tesla shares surge<span class="x y"> losses <b>and</b> layoffs</span>'
                "</h1></article>")
        self.assertIn("losses", GUARD.analyze_html(html, "//h1").clean_text)

    def test_has_inside_nth_child_of_inside_has(self):
        dropped = ("<style>h1:has(span:nth-child(1 of :has(b))) span { display: none }</style><article><h1>"
                   "Tesla shares surge<span> losses <b>and</b> layoffs</span></h1></article>")
        self.assertIn("losses", GUARD.analyze_html(dropped, "//h1").clean_text)
        kept = ("<style>h1:has(span:nth-child(1 of :is(.x, :has(b)))) span { display: none }</style><article>"
                '<h1>Tesla shares surge<span class="x"> losses <b>and</b> layoffs</span></h1></article>')
        self.assertNotIn("losses", GUARD.analyze_html(kept, "//h1").clean_text)


class HeadlineMatchingTimeTests(unittest.TestCase):
    """Matching headings against titles stays fast whatever the page repeats. Real pages: at most
    4 title variants, 20 <h1> and <h2>, and a 146-character <h1> (284 saved news pages)."""

    def assert_quick(self, html, seconds=2):
        import time

        started = time.perf_counter()
        GUARD.extract_article(html)
        self.assertLess(time.perf_counter() - started, seconds)

    def test_a_title_with_thousands_of_segments(self):
        title = "Tesla shares surge" + " | a" * 2000
        headings = "".join(f"<h1>Tesla shares surge {number}</h1>" for number in range(100))
        self.assert_quick(f"<html><head><title>{title}</title></head><body>{headings}</body></html>")

    def test_thousands_of_identical_headings(self):
        title = "x" + " | a" * 200
        self.assert_quick(f"<html><head><title>{title}</title></head><body>{'<h1>x</h1>' * 5000}</body></html>")

    def test_a_long_repeated_title_and_heading(self):
        text = "Local news " * 2000
        self.assert_quick(f"<html><head><title>{text}</title></head><body><h1>{text}</h1></body></html>")

    def test_thousands_of_distinct_long_headings(self):
        title = "Tesla shares surge after strong deliveries"
        headings = "".join(f"<h1>{'Tesla shares surge after strong deliveries ' * 20}{number}</h1>"
                           for number in range(3000))
        self.assert_quick(f"<html><head><title>{title}</title></head><body>{headings}</body></html>")


if __name__ == "__main__":
    unittest.main()
