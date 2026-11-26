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


ARTICLE_TEXT = " ".join(["Tesla delivered more cars than analysts expected this quarter, the company said on Tuesday."] * 6)


def news_page(headline_html, title="Tesla shares surge", body=ARTICLE_TEXT):
    return (f"<html><head><title>{title}</title></head><body><article><h1>{headline_html}</h1>"
            f"<p>{body}</p></article></body></html>")


@unittest.skipUnless(HAS_SCRAPERS, "bs4, newspaper4k, trafilatura or playwright not installed")
class RealPageScoringTests(unittest.TestCase):
    def test_static_readings_on_hidden_headline(self):
        from real_world_test.scraper_readings import static_readings

        readings = static_readings(news_page('Tesla shares <span style="display:none">amid fraud probe</span> surge'))
        self.assertIn("fraud probe", readings["BeautifulSoup h1"])
        self.assertIn("fraud probe", readings["lxml h1 (Scrapy)"])

    def test_reader_error_is_recorded(self):
        from unittest import mock

        from real_world_test import scraper_readings

        with mock.patch.object(scraper_readings, "_newspaper", side_effect=ValueError("bad")):
            readings = scraper_readings.static_readings(news_page("Tesla shares surge"))
        self.assertTrue(readings["newspaper4k title"].startswith("<error: ValueError"))
        self.assertIn("Tesla", readings["BeautifulSoup h1"])

    def test_got_through_is_leaked_and_pass(self):
        from real_world_test.evaluate_injections import HEADLINE_PAYLOAD_CHECK, got_through

        guard = HeadlineAntidote(PAPER_WATCHLIST)
        visible = guard.extract_article(news_page("Tesla shares surge amid fraud probe",
                                                  title="Tesla shares surge amid fraud probe"))
        self.assertIs(got_through(visible, HEADLINE_PAYLOAD_CHECK), True)
        hidden = guard.extract_article(news_page('Tesla shares surge<span style="display:none"> amid fraud probe</span>'))
        self.assertIs(got_through(hidden, HEADLINE_PAYLOAD_CHECK), False)

    def test_failed_reading_is_not_counted(self):
        from real_world_test.evaluate_injections import BODY_PAYLOAD_CHECK, count_reading

        counts = {"variants": 0, "reached": 0, "errors": 0, "ambiguous": 0}
        count_reading(counts, "<error: ValueError: bad>", BODY_PAYLOAD_CHECK, ambiguous=False)
        count_reading(counts, "Regulators opened a fraud probe into the company today.", BODY_PAYLOAD_CHECK,
                      ambiguous=False)
        self.assertEqual(counts, {"variants": 1, "reached": 1, "errors": 1, "ambiguous": 0})

    def test_ambiguous_pair_is_left_out(self):
        from real_world_test.evaluate_injections import BODY_PAYLOAD_CHECK, ambiguous_readers
        from real_world_test.scraper_readings import BODY_READERS, static_readings

        clean = static_readings(news_page("Tesla shares surge",
                                          body=ARTICLE_TEXT + " A fraud probe into the company ended last year."))
        ambiguous = ambiguous_readers(clean, BODY_READERS, BODY_PAYLOAD_CHECK)
        self.assertIn("trafilatura body", ambiguous)
        self.assertNotIn("BeautifulSoup h1", ambiguous)

    def test_merge_sums_and_checks_slices(self):
        from real_world_test.evaluate_injections import empty_results, merged_results

        def part(first, last):
            results = empty_results(last - first, True)
            results["slice"] = [first, last]
            results["scraper_counts"]["headline: display:none span"]["BeautifulSoup h1"] = {
                "variants": 1, "reached": 1, "errors": 0, "ambiguous": 0}
            return results

        merged = merged_results([part(60, 120), part(0, 60)], total_pages=120)
        self.assertEqual(merged["scraper_counts"]["headline: display:none span"]["BeautifulSoup h1"]["variants"], 2)
        with self.assertRaises(ValueError):
            merged_results([part(0, 60), part(50, 120)], total_pages=120)
        with self.assertRaises(ValueError):
            merged_results([part(0, 60)], total_pages=120)


class SavedSliceTests(unittest.TestCase):
    def test_overlapping_slice_is_refused_and_saved_slices_kept(self):
        import os
        import tempfile

        from real_world_test.evaluate_injections import check_slice_is_free

        with tempfile.TemporaryDirectory() as parts_directory:
            for name in ("part_0000_0020.json", "part_0020_0040.json"):
                open(os.path.join(parts_directory, name), "w").close()
            with self.assertRaises(ValueError):
                check_slice_is_free(parts_directory, 0, 3)
            check_slice_is_free(parts_directory, 0, 20)
            check_slice_is_free(parts_directory, 40, 60)
            self.assertEqual(sorted(os.listdir(parts_directory)), ["part_0000_0020.json", "part_0020_0040.json"])


class CleanRunTests(unittest.TestCase):
    def test_verdict_counts_fill_zeros(self):
        from benchmark.run_clean import verdict_counts

        self.assertEqual(verdict_counts(["pass", "pass", "review"]), {"pass": 2, "review": 1, "quarantine": 0})


if __name__ == "__main__":
    unittest.main()
