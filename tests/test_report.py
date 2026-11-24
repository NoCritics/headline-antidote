"""The JSON report: to_dict() output, checked against the published schema."""

import dataclasses
import importlib.resources
import importlib.util
import json
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST
from tests.test_article import HEADLINE, build_page

GUARD = HeadlineGuard(PAPER_WATCHLIST)
HOMOGLYPH_TESLA = "Т" + "esla"  # Cyrillic capital Te


def load_validator():
    import jsonschema

    schema_text = importlib.resources.files("headline_guard").joinpath("report_schema.json").read_text(
        encoding="utf-8")
    return jsonschema.Draft202012Validator(json.loads(schema_text))


@unittest.skipIf(importlib.util.find_spec("jsonschema") is None, "jsonschema not installed (the [test] extra)")
class ReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()

    def assert_valid(self, report):
        errors = [error.message for error in self.validator.iter_errors(report)]
        self.assertEqual(errors, [], json.dumps(report, ensure_ascii=False, indent=1))
        json.dumps(report)  # plain JSON types only

    def test_text_report_holds_the_answers(self):
        report = GUARD.analyze(f"{HOMOGLYPH_TESLA} shares surge").to_dict()
        self.assert_valid(report)
        self.assertEqual(report["report_type"], "text")
        self.assertEqual(report["verdict"], "quarantine")
        self.assertEqual(report["text_as_written"], f"{HOMOGLYPH_TESLA} shares surge")
        self.assertEqual(report["text_cleaned"], "Tesla shares surge")
        self.assertEqual(report["tickers"], ["TSLA"])
        [flag] = report["flags"]
        self.assertEqual(flag["category"], "watchlist_homoglyph")
        self.assertEqual(flag["severity"], "high")
        self.assertIsNone(flag["field"])
        self.assertEqual(flag["flagged_text"], HOMOGLYPH_TESLA)
        self.assertEqual((flag["start"], flag["end"]), (0, 5))
        self.assertTrue(flag["detail"])

    def test_offsets_count_code_points(self):
        tag_characters = "".join(chr(0xE0000 + ord(letter)) for letter in "buy")
        report = GUARD.analyze(f"Tesla{tag_characters} shares surge").to_dict()
        self.assert_valid(report)
        [flag] = report["flags"]
        self.assertEqual((flag["start"], flag["end"]), (5, 8))

    def test_html_text_report_flags_have_no_offsets(self):
        result = GUARD.analyze_html('<h1>Tesla shares <span style="display:none">plunge</span> surge</h1>')
        report = result.to_dict()
        self.assert_valid(report)
        [flag] = report["flags"]
        self.assertEqual(flag["category"], "hidden_html_text")
        self.assertEqual(flag["flagged_text"], "plunge")
        self.assertEqual((flag["start"], flag["end"]), (None, None))

    @unittest.skipIf(importlib.util.find_spec("trafilatura") is None, "trafilatura not installed")
    def test_article_report_holds_the_answers(self):
        page = build_page(headline_html=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA))
        report = GUARD.extract_article(page).to_dict()
        self.assert_valid(report)
        self.assertEqual(report["report_type"], "article")
        self.assertEqual(report["verdict"], "quarantine")
        self.assertEqual(report["headline"], HEADLINE)
        self.assertIn("og:title", report["metadata_titles"])
        self.assertEqual(report["tickers"], ["TSLA"])
        self.assertEqual(report["browser_check"], {"needed": False, "reasons": [], "ran": False,
                                                   "verified": False, "milliseconds": None})
        headline_flags = [flag for flag in report["flags"] if flag["field"] == "headline"]
        self.assertEqual([flag["category"] for flag in headline_flags], ["watchlist_homoglyph"])
        self.assertEqual(headline_flags[0]["flagged_text"], HOMOGLYPH_TESLA)
        for flag in report["flags"]:
            self.assertNotIn("start", flag)

    @unittest.skipIf(importlib.util.find_spec("trafilatura") is None, "trafilatura not installed")
    def test_article_report_records_browser_reasons(self):
        page = build_page(headline_html=f"{HEADLINE}<script>document.title='x'</script>")
        report = GUARD.extract_article(page).to_dict()
        self.assert_valid(report)
        self.assertTrue(report["browser_check"]["needed"])
        self.assertEqual(len(report["browser_check"]["reasons"]), 1)

    @unittest.skipIf(importlib.util.find_spec("trafilatura") is None, "trafilatura not installed")
    def test_a_browser_run_that_confirms_nothing_still_ran(self):
        # As browser_check.py returns a page the browser rendered but could not settle (a consent
        # wall) or whose headline it did not find: a render time, browser_verified left False.
        page = build_page(headline_html=f"{HEADLINE}<script>document.title='x'</script>")
        article = dataclasses.replace(GUARD.extract_article(page), browser_milliseconds=812.5)
        report = article.to_dict()
        self.assert_valid(report)
        self.assertTrue(report["browser_check"]["ran"])
        self.assertFalse(report["browser_check"]["verified"])
        self.assertEqual(report["browser_check"]["milliseconds"], 812.5)

    def test_schema_rejects_a_report_without_a_verdict(self):
        report = GUARD.analyze("Tesla shares surge").to_dict()
        del report["verdict"]
        self.assertFalse(self.validator.is_valid(report))

    def test_schema_rejects_a_verdict_the_flags_do_not_give(self):
        report = GUARD.analyze(f"{HOMOGLYPH_TESLA} shares surge").to_dict()
        self.assertTrue(self.validator.is_valid(report))
        report["verdict"] = "pass"
        self.assertFalse(self.validator.is_valid(report))
        report["flags"] = []
        self.assertTrue(self.validator.is_valid(report))

    def test_schema_rejects_half_known_offsets(self):
        report = GUARD.analyze(f"{HOMOGLYPH_TESLA} shares surge").to_dict()
        report["flags"][0]["end"] = None
        self.assertFalse(self.validator.is_valid(report))
        report["flags"][0]["start"] = None
        self.assertTrue(self.validator.is_valid(report))

    def test_offsets_lie_inside_the_text(self):
        zero_width_space, right_to_left_override = "\u200b", "\u202e"
        for text in (f"{HOMOGLYPH_TESLA} shares surge", f"Tes{zero_width_space}la shares{right_to_left_override} surge",
                     "\uff34\uff45\uff53\uff4c\uff41 rally"):  # the last is full-width "Tesla"
            report = GUARD.analyze(text).to_dict()
            self.assertTrue(report["flags"], text)
            for flag in report["flags"]:
                self.assertLessEqual(0, flag["start"])
                self.assertLessEqual(flag["start"], flag["end"])
                self.assertLessEqual(flag["end"], len(report["text_as_written"]))
                self.assertEqual(report["text_as_written"][flag["start"]:flag["end"]], flag["flagged_text"])

    @unittest.skipIf(importlib.util.find_spec("trafilatura") is None, "trafilatura not installed")
    def test_schema_rejects_offsets_in_an_article_flag(self):
        page = build_page(headline_html=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA))
        report = GUARD.extract_article(page).to_dict()
        self.assertTrue(self.validator.is_valid(report))
        report["flags"][0].update(start=0, end=5)
        self.assertFalse(self.validator.is_valid(report))


if __name__ == "__main__":
    unittest.main()
