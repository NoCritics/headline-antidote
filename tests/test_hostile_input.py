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


if __name__ == "__main__":
    unittest.main()
