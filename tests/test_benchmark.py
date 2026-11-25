"""The benchmark runs: how each reading of an attack page is scored."""

import importlib.util
import re
import unittest

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST
from headline_antidote.browser_visibility import RenderedPage

HAS_SCRAPERS = all(importlib.util.find_spec(name) is not None
                   for name in ("bs4", "newspaper", "trafilatura", "playwright"))


def example_page(name):
    from scraper_comparison.pages import TEST_PAGES

    for page in TEST_PAGES:
        if page.name == name:
            return page
    raise KeyError(name)


class StubVerifier:
    """Renders every page as showing the given headline above the example article's body."""

    def __init__(self, headline):
        self.headline = headline

    def render(self, url, html, headline_xpath=None, heading_text=None, expected_words=None):
        from scraper_comparison.pages import ARTICLE_BODY

        body_text = re.sub(r"<[^>]+>", " ", ARTICLE_BODY)
        return RenderedPage(self.headline, self.headline + " " + body_text, "", 5.0, True)


@unittest.skipUnless(HAS_SCRAPERS, "bs4, newspaper4k, trafilatura or playwright not installed")
class ExamplePageReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = HeadlineAntidote(PAPER_WATCHLIST)

    def reading(self, name, verifier=None):
        from scraper_comparison.run_comparison import antidote_reading

        return antidote_reading(example_page(name), self.guard, verifier)

    def test_display_none_page_does_not_get_through(self):
        reading = self.reading("display_none")
        self.assertIs(reading["reached"], False)
        self.assertIs(reading["got_through"], False)

    def test_clean_page_passes(self):
        reading = self.reading("clean_english")
        self.assertEqual(reading["verdict"], "pass")
        self.assertIs(reading["got_through"], False)

    def test_homoglyph_page_is_flagged(self):
        reading = self.reading("homoglyph_name")
        self.assertEqual(reading["verdict"], "quarantine")
        self.assertIs(reading["got_through"], False)

    def test_browser_verdict_is_used(self):
        # Statically the model gets the <title>'s wording; a browser that shows the payload decides.
        from scraper_comparison.pages import HIDDEN_PAYLOAD, VISIBLE_HEADLINE

        static = self.reading("javascript_hidden")
        self.assertIs(static["browser_checked"], False)
        self.assertIs(static["reached"], False)
        reading = self.reading("javascript_hidden", StubVerifier(VISIBLE_HEADLINE + " " + HIDDEN_PAYLOAD))
        self.assertIs(reading["browser_checked"], True)
        self.assertIs(reading["reached"], True)
        self.assertIs(reading["got_through"], True)


if __name__ == "__main__":
    unittest.main()
