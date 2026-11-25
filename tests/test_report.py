"""The JSON report: to_dict() output, checked against the published schema and docs/report_format.md."""

import copy
import dataclasses
import importlib.resources
import importlib.util
import json
import re
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST
from tests import test_remaining_gaps as gaps
from tests.test_article import HEADLINE, build_page

GUARD = HeadlineGuard(PAPER_WATCHLIST)
HOMOGLYPH_TESLA = "Т" + "esla"  # Cyrillic capital Te
CYRILLIC_TE = {"code_point": "U+0422", "name": "CYRILLIC CAPITAL LETTER TE"}
ZERO_WIDTH_SPACE = chr(0x200B)
RIGHT_TO_LEFT_OVERRIDE = chr(0x202E)
LEFT_TO_RIGHT_OVERRIDE = chr(0x202D)
FULL_WIDTH_BUY = "".join(chr(0xFF21 + ord(letter) - ord("A")) for letter in "BUY")
STACKED_MARKS = chr(0x0301) + chr(0x0302) + chr(0x0303)
HAS_TRAFILATURA = importlib.util.find_spec("trafilatura") is not None
HAS_JSONSCHEMA = importlib.util.find_spec("jsonschema") is not None

# docs/report_format.md, "Categories": category -> (severities, required evidence keys, optional ones).
SPEC_CATEGORIES = {
    "watchlist_homoglyph": ({"high"}, {"looks_like", "tickers", "characters"}, set()),
    "accented_watchlist_name": ({"medium"}, {"looks_like", "tickers", "characters"}, set()),
    "possible_watchlist_lookalike": ({"low"}, {"looks_like", "tickers"}, set()),
    "mixed_script_word": ({"high", "medium"}, {"characters"}, set()),
    "whole_script_lookalike": ({"medium"}, {"looks_like"}, set()),
    "compatibility_lookalike": ({"low", "medium", "high"}, {"characters", "looks_like"},
                                {"inside_name", "tickers"}),
    "hidden_tag_characters": ({"high"}, {"decoded_text"}, set()),
    "invisible_character": ({"low", "medium", "high"}, {"characters"}, {"inside_name", "tickers"}),
    "bidi_control": ({"medium", "high"}, {"characters"}, {"inside_name", "tickers"}),
    "excessive_combining_marks": ({"medium", "high"}, {"characters"}, {"inside_name", "tickers"}),
    "hidden_html_text": ({"high", "medium"}, {"cause"}, {"css"}),
    "headline_adds_words": ({"medium", "low"}, {"compared_with"}, {"kicker"}),
    "script_generated_text": ({"medium"}, set(), set()),
    "css_generated_text": ({"medium"}, set(), set()),
    "html_comment_text": ({"medium"}, set(), set()),
    "reordered_text": ({"high", "medium"}, {"css"}, set()),
    "embedded_font": ({"medium"}, set(), set()),
    "headline_not_found_in_browser": ({"high"}, set(), set()),
    "headline_unconfirmed": ({"low"}, set(), set()),
    "headline_from_metadata": ({"low"}, set(), set()),
    "headline_not_found": ({"medium"}, set(), set()),
    "scraper_text_differs": ({"high", "medium"}, set(), {"added_text", "dropped_text"}),
    "hidden_text_in_article": ({"low"}, {"cause"}, {"css"}),
    "possibly_hidden_text": ({"low"}, {"cause", "css"}, set()),
    "most_of_article_hidden": ({"medium"}, set(), set()),
    "body_text_not_in_page_copy": ({"low"}, {"compared_with"}, set()),
    "text_behind_preview_window": ({"low"}, set(), set()),
    "article_body_not_found": ({"low"}, set(), set()),
    "page_too_complex_to_read": ({"medium"}, {"message"}, set()),
    "browser_check_incomplete": ({"low"}, set(), set()),
    "browser_check_inconclusive": ({"medium"}, {"words_shown", "words_total"}, set()),
}
CHARACTER_CATEGORIES = {
    "watchlist_homoglyph", "accented_watchlist_name", "possible_watchlist_lookalike", "mixed_script_word",
    "whole_script_lookalike", "compatibility_lookalike", "hidden_tag_characters", "invisible_character",
    "bidi_control", "excessive_combining_marks",
}
RAISED_INSIDE_NAMES = {"compatibility_lookalike", "invisible_character", "bidi_control", "excessive_combining_marks"}


def load_schema():
    schema_text = importlib.resources.files("headline_guard").joinpath("report_schema.json").read_text(
        encoding="utf-8")
    return json.loads(schema_text)


def load_validator():
    import jsonschema

    return jsonschema.Draft202012Validator(load_schema())


def known_causes():
    return set(load_schema()["$defs"]["evidence"]["properties"]["cause"]["x-known-values"])


def assert_follows_the_spec(test, report):
    """What the schema leaves open: known categories only, each with only the evidence keys the spec lists."""
    known = known_causes()
    for flag in report["flags"]:
        category, evidence = flag["category"], flag["evidence"]
        test.assertIn(category, SPEC_CATEGORIES, flag)
        severities, required, optional = SPEC_CATEGORIES[category]
        test.assertIn(flag["severity"], severities, flag)
        allowed = required | optional | ({"found_in"} if flag["field"] == "metadata" else set())
        test.assertLessEqual(set(evidence), allowed, flag)
        test.assertGreaterEqual(set(evidence), required, flag)
        if "cause" in evidence:
            test.assertIn(evidence["cause"], known, flag)
        if category in RAISED_INSIDE_NAMES:
            test.assertEqual(flag["severity"] == "high", "inside_name" in evidence, flag)
        if flag["field"] == "metadata":
            test.assertIn("found_in", evidence, flag)
        for character in evidence.get("characters", []):
            test.assertEqual(set(character), {"code_point", "name"}, flag)


def flags_of(report, category):
    return [flag for flag in report["flags"] if flag["category"] == category]


class ReportCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = load_validator()

    def assert_valid(self, report):
        errors = [error.message for error in self.validator.iter_errors(report)]
        self.assertEqual(errors, [], json.dumps(report, ensure_ascii=False, indent=1))
        json.dumps(report)  # plain JSON types only
        assert_follows_the_spec(self, report)


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema not installed (the [test] extra)")
class ReportTests(ReportCase):
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
        self.assertEqual(flag["evidence"],
                         {"looks_like": "Tesla", "tickers": ["TSLA"], "characters": [CYRILLIC_TE]})
        self.assertNotIn("detail", flag)

    def test_offsets_count_code_points(self):
        tag_characters = "".join(chr(0xE0000 + ord(letter)) for letter in "buy")
        report = GUARD.analyze(f"Tesla{tag_characters} shares surge").to_dict()
        self.assert_valid(report)
        [flag] = report["flags"]
        self.assertEqual((flag["start"], flag["end"]), (5, 8))
        self.assertEqual(flag["evidence"], {"decoded_text": "buy"})

    def test_html_text_report_flags_have_no_offsets(self):
        result = GUARD.analyze_html('<h1>Tesla shares <span style="display:none">plunge</span> surge</h1>')
        report = result.to_dict()
        self.assert_valid(report)
        [flag] = report["flags"]
        self.assertEqual(flag["category"], "hidden_html_text")
        self.assertEqual(flag["flagged_text"], "plunge")
        self.assertEqual((flag["start"], flag["end"]), (None, None))
        self.assertEqual(flag["evidence"], {"cause": "display_none", "css": "display:none"})

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
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

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
    def test_article_report_records_browser_reasons(self):
        page = build_page(headline_html=f"{HEADLINE}<script>document.title='x'</script>")
        report = GUARD.extract_article(page).to_dict()
        self.assert_valid(report)
        self.assertTrue(report["browser_check"]["needed"])
        self.assertEqual(len(report["browser_check"]["reasons"]), 1)

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
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
        for text in (f"{HOMOGLYPH_TESLA} shares surge", f"Tes{ZERO_WIDTH_SPACE}la shares{RIGHT_TO_LEFT_OVERRIDE} surge",
                     FULL_WIDTH_BUY + " rally"):
            report = GUARD.analyze(text).to_dict()
            self.assertTrue(report["flags"], text)
            for flag in report["flags"]:
                self.assertLessEqual(0, flag["start"])
                self.assertLessEqual(flag["start"], flag["end"])
                self.assertLessEqual(flag["end"], len(report["text_as_written"]))
                self.assertEqual(report["text_as_written"][flag["start"]:flag["end"]], flag["flagged_text"])

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
    def test_schema_rejects_offsets_in_an_article_flag(self):
        page = build_page(headline_html=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA))
        report = GUARD.extract_article(page).to_dict()
        self.assertTrue(self.validator.is_valid(report))
        report["flags"][0].update(start=0, end=5)
        self.assertFalse(self.validator.is_valid(report))


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema not installed (the [test] extra)")
class TextEvidenceTests(ReportCase):
    """The evidence each character check gives, from docs/report_format.md."""

    def only_flag(self, text, category):
        report = GUARD.analyze(text).to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, category)
        return flag

    def test_ascii_look_alikes_list_the_ascii_stand_ins(self):
        flag = self.only_flag("TesIa shares surge", "watchlist_homoglyph")
        self.assertEqual(flag["evidence"], {
            "looks_like": "Tesla", "tickers": ["TSLA"],
            "characters": [{"code_point": "U+0049", "name": "LATIN CAPITAL LETTER I"}]})

    def test_ascii_look_alikes_of_a_different_length_list_what_was_swapped(self):
        # Latin "rn" reads as "m".
        flag = self.only_flag("rnicrosoft shares surge", "watchlist_homoglyph")
        self.assertEqual(flag["evidence"]["looks_like"], "microsoft")
        self.assertEqual([item["code_point"] for item in flag["evidence"]["characters"]], ["U+0072", "U+006E"])

    def test_added_accents(self):
        flag = self.only_flag("Tésla soars", "accented_watchlist_name")
        self.assertEqual(flag["evidence"], {
            "looks_like": "Tesla", "tickers": ["TSLA"],
            "characters": [{"code_point": "U+0301", "name": "COMBINING ACUTE ACCENT"}]})

    def test_a_native_word_that_resembles_a_name(self):
        flag = self.only_flag("Головна МЕТА компанії — вийти на ринок ЄС", "possible_watchlist_lookalike")
        self.assertEqual(flag["evidence"], {"looks_like": "META", "tickers": ["META"]})

    def test_mixed_script_word(self):
        flag = self.only_flag("hеllo world", "mixed_script_word")  # Cyrillic ie
        self.assertEqual(flag["evidence"], {
            "characters": [{"code_point": "U+0435", "name": "CYRILLIC SMALL LETTER IE"}]})

    def test_whole_script_look_alike(self):
        flag = self.only_flag("the сор arrested today", "whole_script_lookalike")  # Cyrillic
        self.assertEqual(flag["evidence"], {"looks_like": "cop"})

    def test_adjacent_compatibility_letters_merge_into_one_flag(self):
        flag = self.only_flag(FULL_WIDTH_BUY + " now", "compatibility_lookalike")
        self.assertEqual(flag["severity"], "medium")
        self.assertEqual(flag["evidence"]["looks_like"], "BUY")
        self.assertEqual([item["code_point"] for item in flag["evidence"]["characters"]],
                         ["U+FF22", "U+FF35", "U+FF39"])
        self.assertEqual(flag["evidence"]["characters"][0]["name"], "FULLWIDTH LATIN CAPITAL LETTER B")

    def test_a_character_outside_the_basic_plane_has_a_five_digit_code_point(self):
        flag = self.only_flag(chr(0x1D401) + "uy now", "compatibility_lookalike")  # mathematical bold B
        self.assertEqual(flag["evidence"]["characters"][0]["code_point"], "U+1D401")

    def test_invisible_character_in_an_ordinary_word(self):
        flag = self.only_flag(f"hel{ZERO_WIDTH_SPACE}lo world", "invisible_character")
        self.assertEqual(flag["severity"], "medium")
        self.assertEqual(flag["evidence"], {"characters": [{"code_point": "U+200B", "name": "ZERO WIDTH SPACE"}]})

    def test_invisible_character_inside_a_watched_name(self):
        flag = self.only_flag(f"Tes{ZERO_WIDTH_SPACE}la shares surge", "invisible_character")
        self.assertEqual(flag["severity"], "high")
        self.assertEqual(flag["evidence"], {
            "characters": [{"code_point": "U+200B", "name": "ZERO WIDTH SPACE"}],
            "inside_name": "Tesla", "tickers": ["TSLA"]})

    def test_bidi_control_and_adjacent_controls_merge(self):
        flag = self.only_flag(f"Tesla{RIGHT_TO_LEFT_OVERRIDE}{LEFT_TO_RIGHT_OVERRIDE} x", "bidi_control")
        self.assertEqual(flag["severity"], "medium")
        self.assertEqual(flag["evidence"], {"characters": [
            {"code_point": "U+202E", "name": "RIGHT-TO-LEFT OVERRIDE"},
            {"code_point": "U+202D", "name": "LEFT-TO-RIGHT OVERRIDE"}]})

    def test_bidi_control_inside_a_watched_name(self):
        flag = self.only_flag(f"Tes{RIGHT_TO_LEFT_OVERRIDE}la x", "bidi_control")
        self.assertEqual(flag["evidence"]["inside_name"], "Tesla")
        self.assertEqual(flag["evidence"]["tickers"], ["TSLA"])

    def test_stacked_marks(self):
        flag = self.only_flag(f"e{STACKED_MARKS} x", "excessive_combining_marks")
        self.assertEqual(flag["severity"], "medium")
        self.assertEqual([item["code_point"] for item in flag["evidence"]["characters"]],
                         ["U+0301", "U+0302", "U+0303"])
        self.assertNotIn("inside_name", flag["evidence"])

    def test_stacked_marks_inside_a_watched_name(self):
        flag = self.only_flag(f"T{STACKED_MARKS}esla x", "excessive_combining_marks")
        self.assertEqual(flag["severity"], "high")
        self.assertEqual((flag["evidence"]["inside_name"], flag["evidence"]["tickers"]), ("Tesla", ["TSLA"]))


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema not installed (the [test] extra)")
class HtmlEvidenceTests(ReportCase):
    def test_reordered_text_names_its_rule(self):
        html = '<h1>Tesla shares <span style="unicode-bidi:bidi-override;direction:rtl">surge fast</span></h1>'
        report = GUARD.analyze_html(html).to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "reordered_text")
        self.assertEqual(flag["evidence"], {"css": "unicode-bidi:bidi-override"})

    def test_scraper_text_that_adds_and_drops_words(self):
        page = '<h1>Apple beats <span style="display:none">estimates</span> today</h1>'
        report = GUARD.analyze_html(page, "//h1", scraped_text="Apple beats estimates tomorrow").to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "scraper_text_differs")
        self.assertEqual(flag["evidence"], {"added_text": "estimates tomorrow", "dropped_text": "today"})

    def test_scraper_text_that_only_adds_words(self):
        report = GUARD.analyze_html("<h1>Apple beats estimates</h1>", "//h1",
                                    scraped_text="Apple beats estimates losses").to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "scraper_text_differs")
        self.assertEqual(flag["evidence"], {"added_text": "losses"})

    def test_a_page_too_complex_to_read_gives_the_readers_message(self):
        report = GUARD.analyze_html("<div>" * 600 + "x").to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "page_too_complex_to_read")
        self.assertTrue(flag["evidence"]["message"])
        self.assertEqual(set(flag["evidence"]), {"message"})

    def test_a_missing_headline_element_has_no_evidence(self):
        report = GUARD.analyze_html("<p>No headline</p>", headline_xpath="//h1").to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "headline_not_found")
        self.assertEqual(flag["evidence"], {})

    def test_an_html_comment_has_no_evidence(self):
        report = GUARD.analyze_html("<h1>Apple beats estimates<!-- losses --></h1>").to_dict()
        self.assert_valid(report)
        [flag] = flags_of(report, "html_comment_text")
        self.assertEqual(flag["evidence"], {})

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
    def test_a_metadata_flag_says_which_title_it_was_found_in(self):
        page = build_page(og_title=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA) + " | Example News")
        report = GUARD.extract_article(page).to_dict()
        self.assert_valid(report)
        [flag] = [flag for flag in report["flags"] if flag["field"] == "metadata"]
        self.assertEqual(flag["category"], "watchlist_homoglyph")
        self.assertEqual(flag["evidence"], {
            "looks_like": "Tesla", "tickers": ["TSLA"], "characters": [CYRILLIC_TE], "found_in": "og:title"})


@unittest.skipUnless(HAS_JSONSCHEMA, "jsonschema not installed (the [test] extra)")
class SchemaRuleTests(ReportCase):
    """One negative case for each family of rules the schema states."""

    def homoglyph_report(self):
        return GUARD.analyze(f"{HOMOGLYPH_TESLA} shares surge").to_dict()

    def assert_rejected_after(self, report, change):
        self.assertTrue(self.validator.is_valid(report), "the report is valid before the change")
        broken = copy.deepcopy(report)
        change(broken)
        self.assertFalse(self.validator.is_valid(broken), json.dumps(broken, ensure_ascii=False))

    def test_evidence_the_category_requires_is_required(self):
        self.assert_rejected_after(self.homoglyph_report(), lambda report: report["flags"][0]["evidence"].pop("characters"))

    def test_a_category_takes_only_its_severities(self):
        self.assert_rejected_after(self.homoglyph_report(), lambda report: report["flags"][0].update(severity="low"))

    def test_a_flag_needs_its_evidence_object(self):
        self.assert_rejected_after(self.homoglyph_report(), lambda report: report["flags"][0].pop("evidence"))

    def test_a_character_code_point_is_upper_case_hex_of_four_digits_or_more(self):
        def lower_case(report):
            report["flags"][0]["evidence"]["characters"][0]["code_point"] = "U+042a"

        def too_short(report):
            report["flags"][0]["evidence"]["characters"][0]["code_point"] = "U+42"

        self.assert_rejected_after(self.homoglyph_report(), lower_case)
        self.assert_rejected_after(self.homoglyph_report(), too_short)

    def test_a_name_inside_needs_its_tickers(self):
        report = GUARD.analyze(f"Tes{ZERO_WIDTH_SPACE}la shares surge").to_dict()
        self.assert_rejected_after(report, lambda broken: broken["flags"][0]["evidence"].pop("tickers"))

    def test_words_shown_needs_words_total(self):
        report = {"schema_version": "1.0", "report_type": "text", "verdict": "review", "text_as_written": "x",
                  "text_cleaned": "x", "tickers": [],
                  "flags": [{"category": "browser_check_inconclusive", "severity": "medium", "field": None,
                             "flagged_text": "", "evidence": {"words_shown": 1, "words_total": 9},
                             "start": None, "end": None}]}
        self.assert_rejected_after(report, lambda broken: broken["flags"][0]["evidence"].pop("words_total"))

    @unittest.skipUnless(HAS_TRAFILATURA, "trafilatura not installed")
    def test_a_metadata_character_flag_needs_found_in(self):
        page = build_page(og_title=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA) + " | Example News")
        report = GUARD.extract_article(page).to_dict()
        [index] = [number for number, flag in enumerate(report["flags"]) if flag["field"] == "metadata"]
        self.assert_rejected_after(report, lambda broken: broken["flags"][index]["evidence"].pop("found_in"))

    def test_a_cause_the_spec_does_not_list_still_fits_the_schema_but_the_spec_check_rejects_it(self):
        report = GUARD.analyze_html('<h1>Tesla <span style="display:none">plunge</span></h1>').to_dict()
        report["flags"][0]["evidence"]["cause"] = "made_up_cause"
        self.assertTrue(self.validator.is_valid(report))  # the schema keeps the list open for newer versions
        with self.assertRaises(AssertionError):
            assert_follows_the_spec(self, report)

    def test_the_spec_check_rejects_an_unknown_category_and_a_stray_evidence_key(self):
        report = self.homoglyph_report()
        report["flags"][0]["evidence"]["detail"] = "a sentence"
        with self.assertRaises(AssertionError):
            assert_follows_the_spec(self, report)
        report = self.homoglyph_report()
        report["flags"][0]["category"] = "invented_category"
        with self.assertRaises(AssertionError):
            assert_follows_the_spec(self, report)


AFTER_THE_HIDDEN_PARAGRAPH = (
    "<p>Analysts expect the company to update its guidance when it reports results "
    "later this month, and several raised their price targets.</p>")


@unittest.skipUnless(HAS_JSONSCHEMA and HAS_TRAFILATURA, "jsonschema or trafilatura not installed")
class ArticleEvidenceTests(ReportCase):
    """The evidence of each flag the static article reading raises."""

    def only_flag(self, report, category):
        self.assert_valid(report)
        [flag] = flags_of(report, category)
        return flag

    def article_report(self, html, **options):
        return GUARD.extract_article(html, **options).to_dict()

    def test_one_added_ordinary_word_names_the_title_it_was_compared_with(self):
        html = gaps.article_page("Berkshire profit fell sharply as buybacks paused",
                                 title="Berkshire profit fell as buybacks paused")
        flag = self.only_flag(self.article_report(html), "headline_adds_words")
        self.assertEqual(flag["severity"], "low")
        self.assertEqual(flag["evidence"], {"compared_with": "<title>"})

    def test_words_a_script_may_hide_name_the_feed_title(self):
        html = gaps.article_page(f'{gaps.HEADLINE}<span id="p">{gaps.PAYLOAD}</span>',
                                 body_extra="<script>document.getElementById('p').style.display='none';</script>")
        flag = self.only_flag(self.article_report(html, feed_title=gaps.HEADLINE), "headline_adds_words")
        self.assertEqual(flag["severity"], "medium")
        self.assertEqual(flag["evidence"], {"compared_with": "feed title"})

    def test_a_kicker_is_marked(self):
        html = gaps.article_page(f'<span class="topline">Handel mit Wertpapieren</span> <span>{gaps.HEADLINE}</span>')
        flag = self.only_flag(self.article_report(html), "headline_adds_words")
        self.assertEqual(flag["severity"], "low")
        self.assertEqual(flag["evidence"], {"compared_with": "<title>", "kicker": True})

    def test_a_negation_in_its_own_element_is_not_a_kicker(self):
        html = gaps.article_page(f'<span>Not true:</span> <span>{gaps.HEADLINE}</span>')
        flag = self.only_flag(self.article_report(html), "headline_adds_words")
        self.assertEqual(flag["severity"], "medium")
        self.assertNotIn("kicker", flag["evidence"])

    def json_ld_page(self):
        json_ld = (
            '<script type="application/ld+json">{"@type": "NewsArticle", "headline": "' + gaps.HEADLINE + '", '
            '"articleBody": "Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order '
            'a breakup of the company, a ruling analysts said removes a major overhang. The decision lifted other '
            'large technology stocks as investors bet that regulators would struggle to force structural remedies '
            'on the sector."}</script>'
        )
        injected = ("<p>Insiders say the company is quietly preparing for mass layoffs and a profit warning "
                    "that will shock investors next week.</p>")
        return (f"<!doctype html><html><head><title>{gaps.HEADLINE}</title>{json_ld}</head><body><article>"
                f"<h1>{gaps.HEADLINE}</h1>{gaps.ARTICLE_BODY}{injected}</article></body></html>")

    def test_body_passages_missing_from_the_json_ld_copy(self):
        flag = self.only_flag(self.article_report(self.json_ld_page()), "body_text_not_in_page_copy")
        self.assertEqual(flag["evidence"], {"compared_with": "JSON-LD articleBody"})
        self.assertIn("mass layoffs", flag["flagged_text"])

    def test_body_passages_missing_from_the_feeds_article_text(self):
        feed_body = ("Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
                     "a breakup of the company, a ruling analysts said removes a major overhang. The decision "
                     "lifted other large technology stocks as investors bet that regulators would struggle to "
                     "force structural remedies on the sector.")
        flag = self.only_flag(self.article_report(self.json_ld_page(), feed_body=feed_body),
                              "body_text_not_in_page_copy")
        self.assertEqual(flag["evidence"], {"compared_with": "feed article text"})

    def test_hidden_body_text_gives_its_cause_and_rule(self):
        for style, evidence in (
            ('style="font-size:0"', {"cause": "tiny_font", "css": "font-size:0"}),
            ('style="opacity:0"', {"cause": "transparent", "css": "opacity:0"}),
            ("hidden", {"cause": "hidden_attribute"}),
        ):
            with self.subTest(style=style):
                html = gaps.body_page(f"<p {style}>{gaps.INJECTED_PARAGRAPH_TEXT}</p>" + AFTER_THE_HIDDEN_PARAGRAPH)
                flag = self.only_flag(self.article_report(html), "hidden_text_in_article")
                self.assertEqual(flag["severity"], "low")
                self.assertEqual(flag["evidence"], evidence)

    @unittest.skipUnless(gaps.CASCADE_AVAILABLE, "the CSS libraries are not installed")
    def test_white_text_on_an_undeclared_background_gives_the_color_rule(self):
        html = gaps.body_page(f'<p style="color:#fff">{gaps.INJECTED_PARAGRAPH_TEXT}</p>')
        flag = self.only_flag(self.article_report(html), "possibly_hidden_text")
        self.assertEqual(flag["evidence"], {"cause": "same_color_as_background", "css": "color:#fff"})

    def test_flags_without_evidence_have_an_empty_object(self):
        read_more = "".join(f"<p>Paragraph {number} of the rest of the story explains how the ruling affects "
                            "advertising revenue, cloud contracts and the company's hiring plans for next year.</p>"
                            for number in range(6))
        embedded_font = ('@font-face { font-family: "Remap"; src: url(data:font/woff2;base64,AAAA) format("woff2") } '
                         'h1 { font-family: "Remap", serif }')
        pages = {
            "headline_unconfirmed": ("<html><body><article><h1>" + gaps.HEADLINE + "</h1>" + gaps.ARTICLE_BODY
                                     + "</article></body></html>"),
            "headline_from_metadata": build_page(headline_html="Breaking"),
            "article_body_not_found": ("<html><head><title>Hello there world</title></head><body>"
                                       "<h1>Hello there world</h1></body></html>"),
            "css_generated_text": gaps.article_page(
                f'<span class="k"></span>{gaps.HEADLINE}',
                head_extra='<style>.k::before { content: "Exclusive: losses ahead " }</style>'),
            "embedded_font": gaps.article_page(gaps.HEADLINE, head_extra=f"<style>{embedded_font}</style>"),
            "most_of_article_hidden": gaps.body_page(
                f'<div class="readmore"><div id="ControlPara1">{read_more}</div></div>',
                head_extra='<style>.readmore div[id^="ControlPara"] > * { display: none }</style>'),
        }
        for category, html in pages.items():
            with self.subTest(category=category):
                flag = self.only_flag(self.article_report(html), category)
                self.assertEqual(flag["evidence"], {})

    def test_a_page_too_complex_to_read_gives_the_readers_message(self):
        report = self.article_report("<div>" * 600 + "x")
        flag = self.only_flag(report, "page_too_complex_to_read")
        self.assertEqual(flag["field"], "page")
        self.assertEqual(set(flag["evidence"]), {"message"})
        self.assertTrue(flag["evidence"]["message"])


def browser_reports():
    """Article reports after a browser run, from hand-made renders (no Chrome): the way
    tests/test_browser_check.py builds them."""
    from headline_guard.browser_check import compare_with_rendered_page
    from headline_guard.browser_visibility import RenderedPage
    from tests import test_browser_check as browser_tests

    headline, body = browser_tests.HEADLINE, browser_tests.BODY
    body_text = re.sub(r"<[^>]+>", "\n", body)
    visible = ("Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order "
               "a breakup of the company, a ruling analysts said removes a major overhang.")

    def rendered(headline_text, text=body_text, clipped_text="", complete=True, note=""):
        return RenderedPage(headline_text, f"{headline_text or ''}\n{text}", clipped_text, 5.0, complete, note)

    def compare(html, render):
        return compare_with_rendered_page(GUARD, GUARD.extract_article(html), render).to_dict()

    def long_page(hidden_count):
        hidden = "".join(f"<p>Insiders say restructuring wave {number} will bring mass layoffs, a profit warning "
                         "and a regulatory probe that analysts expect to hit the shares.</p>"
                         for number in range(hidden_count))
        return (f"<!doctype html><html><head><title>{headline}</title></head><body><article>"
                f"<h1>{headline}</h1><p>{visible}</p>{hidden}</article></body></html>")

    hiding_script = "<script>document.getElementById('p').style.display='none';</script>"
    hidden_paragraph = ('<p id="x">Insiders say the company is preparing mass layoffs and a profit warning that '
                        "will shock investors next week.</p>"
                        "<script>document.getElementById('x').style.visibility='hidden';</script>")
    return {
        "headline words hidden by a script": compare(
            browser_tests.page(f'{headline}<span id="p"> {browser_tests.PAYLOAD}</span>', body_extra=hiding_script),
            rendered(headline)),
        "headline words in svg text off its drawing": compare(
            browser_tests.page('Alphabet shares surge <svg width="300" height="40"><text x="10">fraud</text></svg>'
                               "after dodging antitrust breakup bullet"), rendered(headline)),
        "headline not found": compare(browser_tests.page(headline), rendered(None)),
        "a script added words": compare(browser_tests.page(headline), rendered(f"{headline} bonus")),
        "hidden body text": compare(browser_tests.page(headline, article_extra=hidden_paragraph), rendered(headline)),
        "incomplete load": compare(long_page(6), rendered(headline, visible, complete=False, note="timed out")),
        "most of the article hidden": compare(long_page(6), rendered(headline, visible)),
        "inconclusive render": compare(long_page(30), rendered(headline, visible)),
        "preview window": compare(browser_tests.page(headline), rendered(headline, "", clipped_text=body_text)),
    }


def article_reports():
    read_more = "".join(f"<p>Paragraph {number} of the rest of the story explains how the ruling affects "
                        "advertising revenue, cloud contracts and the company's hiring plans for next year.</p>"
                        for number in range(6))
    embedded_font = ('@font-face { font-family: "Remap"; src: url(data:font/woff2;base64,AAAA) format("woff2") } '
                     'h1 { font-family: "Remap", serif }')
    kicker = f'<span class="topline">Handel mit Wertpapieren</span> <span>{gaps.HEADLINE}</span>'
    json_ld = ('<script type="application/ld+json">{"@type": "NewsArticle", "headline": "' + gaps.HEADLINE + '", '
               '"articleBody": "Shares of Alphabet rose sharply on Tuesday after a federal judge declined to order '
               'a breakup of the company, a ruling analysts said removes a major overhang. The decision lifted other '
               'large technology stocks as investors bet that regulators would struggle to force structural remedies '
               'on the sector."}</script>')
    pages = {
        "homoglyph in an og:title": build_page(og_title=HEADLINE.replace("Tesla", HOMOGLYPH_TESLA) + " | News"),
        "headline words a script may hide": gaps.article_page(
            f'{gaps.HEADLINE}<span id="p">{gaps.PAYLOAD}</span>',
            body_extra="<script>document.getElementById('p').style.display='none';</script>"),
        "kicker": gaps.article_page(kicker),
        "no title to confirm the heading": ("<html><body><article><h1>" + gaps.HEADLINE + "</h1>" + gaps.ARTICLE_BODY
                                            + "</article></body></html>"),
        "heading matches no title": build_page(headline_html="Breaking"),
        "no article body": "<html><head><title>Hello there world</title></head><body><h1>Hello there world</h1></body></html>",
        "css generated words": gaps.article_page(
            f'<span class="k"></span>{gaps.HEADLINE}',
            head_extra='<style>.k::before { content: "Exclusive: losses ahead " }</style>'),
        "embedded font": gaps.article_page(gaps.HEADLINE, head_extra=f"<style>{embedded_font}</style>"),
        "article collapsed behind read more": gaps.body_page(
            f'<div class="readmore"><div id="ControlPara1">{read_more}</div></div>',
            head_extra='<style>.readmore div[id^="ControlPara"] > * { display: none }</style>'),
        "hidden paragraph": gaps.body_page(
            f'<p style="font-size:0">{gaps.INJECTED_PARAGRAPH_TEXT}</p>' + AFTER_THE_HIDDEN_PARAGRAPH),
        "white paragraph": gaps.body_page(f'<p style="color:#fff">{gaps.INJECTED_PARAGRAPH_TEXT}</p>'),
        "paragraph missing from the article copy": gaps.body_page(
            "<p>Insiders say the company is quietly preparing for mass layoffs and a profit warning "
            "that will shock investors next week.</p>", head_extra=json_ld),
        "page too complex": "<div>" * 600 + "x",
    }
    return {name: GUARD.extract_article(html).to_dict() for name, html in pages.items()}


def text_reports():
    texts = [f"{HOMOGLYPH_TESLA} shares surge", "TesIa shares surge", "Tésla soars",
             "Головна МЕТА компанії — вийти на ринок ЄС", "hеllo world", "the сор arrested today",
             FULL_WIDTH_BUY + " now", "Tesla" + "".join(chr(0xE0000 + ord(letter)) for letter in "buy"),
             f"hel{ZERO_WIDTH_SPACE}lo world", f"Tes{ZERO_WIDTH_SPACE}la shares", f"abc{RIGHT_TO_LEFT_OVERRIDE} def",
             f"Tes{RIGHT_TO_LEFT_OVERRIDE}la x", f"e{STACKED_MARKS} x", f"T{STACKED_MARKS}esla x"]
    reports = {text: GUARD.analyze(text).to_dict() for text in texts}
    pages = {
        "hidden text": '<h1>Tesla shares <span style="display:none">plunge</span> surge</h1>',
        "comment": "<h1>Apple beats estimates<!-- losses --></h1>",
        "reordered": '<h1>Tesla shares <span style="unicode-bidi:bidi-override;direction:rtl">surge fast</span></h1>',
        "no headline": "<p>No headline</p>",
        "page too complex": "<div>" * 600 + "x",
    }
    for name, html in pages.items():
        reports[name] = GUARD.analyze_html(html, headline_xpath="//h1" if name == "no headline" else None).to_dict()
    reports["scraper text"] = GUARD.analyze_html(
        "<h1>Apple beats estimates</h1>", "//h1", scraped_text="Apple beats estimates losses").to_dict()
    reports["browser text"] = GUARD.analyze_html(
        "<h1>Apple beats estimates</h1>", "//h1", scraped_text="Apple beats estimates bonus",
        rendered_by_browser=True).to_dict()
    return reports


@unittest.skipUnless(HAS_JSONSCHEMA and HAS_TRAFILATURA, "jsonschema or trafilatura not installed")
@unittest.skipUnless(gaps.CASCADE_AVAILABLE, "the CSS libraries are not installed")
class CoverageTests(ReportCase):
    def test_every_category_in_the_spec_is_produced_with_valid_evidence(self):
        produced = {}
        for source in (text_reports, article_reports, browser_reports):
            for name, report in source().items():
                self.assert_valid(report)
                for flag in report["flags"]:
                    produced.setdefault(flag["category"], name)
        missing = sorted(set(SPEC_CATEGORIES) - set(produced))
        self.assertEqual(missing, [], "categories in docs/report_format.md that no fixture produces")


if __name__ == "__main__":
    unittest.main()
