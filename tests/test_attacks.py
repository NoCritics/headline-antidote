"""Attacks from arXiv:2601.13082 and their close variants must be flagged, never silently fixed.

Homoglyphs are written as \\u escapes so it is clear which letters are not Latin.
"""

import unittest

from headline_guard import HIGH, MEDIUM, HeadlineGuard, PAPER_WATCHLIST

GUARD = HeadlineGuard(PAPER_WATCHLIST)


def encode_as_tag_characters(text):
    tag_characters = []
    for character in text:
        tag_characters.append(chr(0xE0000 + ord(character)))
    return "".join(tag_characters)


class WatchlistHomoglyphTests(unittest.TestCase):
    def assert_lookalike_caught(self, headline, ticker, expected_clean_text):
        result = GUARD.analyze(headline)
        self.assertEqual(result.verdict, "quarantine", result.flags)
        self.assertIn(ticker, result.tickers)
        self.assertEqual(result.clean_text, expected_clean_text)
        kinds = []
        for flag in result.flags:
            kinds.append(flag.kind)
        self.assertIn("watchlist_homoglyph", kinds)

    def test_cyrillic_letters_in_title_case_name(self):
        # Те + sla: Cyrillic TE and IE.
        self.assert_lookalike_caught("Теsla shares surge", "TSLA", "Tesla shares surge")

    def test_cyrillic_letters_in_upper_case_name(self):
        self.assert_lookalike_caught("ТЕSLA shares surge", "TSLA", "TESLA shares surge")

    def test_ukrainian_i_in_lower_case_name(self):
        self.assert_lookalike_caught("nvіdіа beats estimates", "NVDA", "nvidia beats estimates")

    def test_paper_google_example(self):
        self.assert_lookalike_caught("Gооgle wins appeal", "GOOGL", "Google wins appeal")

    def test_cyrillic_letter_in_ticker(self):
        self.assert_lookalike_caught("$ТSLA rallies", "TSLA", "$TSLA rallies")

    def test_greek_letters_in_name(self):
        # Greek capital ALPHA and IOTA.
        self.assert_lookalike_caught("NVΙDIΑ hits record", "NVDA", "NVIDIA hits record")

    def test_ascii_lookalike_capital_i_for_l(self):
        self.assert_lookalike_caught("TesIa recalls cars", "TSLA", "Tesla recalls cars")

    def test_lookalike_inside_multi_word_name(self):
        self.assert_lookalike_caught("Eli Lіlly raises guidance", "LLY", "Eli Lilly raises guidance")

    def test_flag_offsets_point_into_original_headline(self):
        headline = "Breaking: Теsla shares surge"
        result = GUARD.analyze(headline)
        flag = result.flags[0]
        self.assertEqual(headline[flag.start:flag.end], "Теsla")


class InvisibleCharacterTests(unittest.TestCase):
    def test_zero_width_space_inside_name_is_high(self):
        result = GUARD.analyze("Tes​la stock jumps")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.clean_text, "Tesla stock jumps")
        self.assertEqual(result.tickers, ["TSLA"])
        self.assertEqual(result.flags[0].kind, "invisible_character")
        self.assertEqual(result.flags[0].severity, HIGH)

    def test_zero_width_joiner_between_latin_letters(self):
        result = GUARD.analyze("Ama‍zon cuts jobs")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.tickers, ["AMZN"])

    def test_invisible_character_inside_a_word_is_medium(self):
        result = GUARD.analyze("Mar⁠kets rally")
        self.assertEqual(result.verdict, "review")
        self.assertEqual(result.flags[0].severity, MEDIUM)
        self.assertEqual(result.clean_text, "Markets rally")

    def test_invisible_character_between_words_is_low(self):
        # As found in a real Economic Times title: "full list - ​Diwali Delight".
        result = GUARD.analyze("See the full list - ​Diwali Delight")
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(len(result.flags), 1)
        self.assertEqual(result.clean_text, "See the full list - Diwali Delight")

    def test_run_of_invisibles_becomes_one_flag(self):
        result = GUARD.analyze("Te​‌⁠sla up")
        invisible_flags = []
        for flag in result.flags:
            if flag.kind == "invisible_character":
                invisible_flags.append(flag)
        self.assertEqual(len(invisible_flags), 1)
        self.assertEqual(invisible_flags[0].end - invisible_flags[0].start, 3)

    def test_hidden_tag_characters_are_decoded(self):
        headline = "Apple beats estimates" + encode_as_tag_characters(" losses and layoffs")
        result = GUARD.analyze(headline)
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.clean_text, "Apple beats estimates")
        self.assertEqual(result.flags[0].kind, "hidden_tag_characters")
        self.assertEqual(result.flags[0].evidence, {"decoded_text": " losses and layoffs"})

    def test_bidi_override_in_latin_headline(self):
        result = GUARD.analyze("Tesla ‮egrus‬ shares")
        kinds = []
        for flag in result.flags:
            kinds.append(flag.kind)
        self.assertIn("bidi_control", kinds)
        self.assertNotEqual(result.verdict, "pass")

    def test_soft_hyphen_inside_name_is_raised_to_high(self):
        result = GUARD.analyze("Nvi­dia earnings")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.tickers, ["NVDA"])


class CompatibilityFormTests(unittest.TestCase):
    def test_math_bold_name(self):
        result = GUARD.analyze("\U0001d40d\U0001d415\U0001d408\U0001d403\U0001d408\U0001d400 stock soars")
        self.assertEqual(result.clean_text, "NVIDIA stock soars")
        self.assertEqual(result.tickers, ["NVDA"])
        self.assertEqual(len(result.flags), 1)
        self.assertEqual(result.flags[0].kind, "compatibility_lookalike")
        self.assertEqual(result.flags[0].severity, HIGH)

    def test_full_width_name_in_english_headline(self):
        result = GUARD.analyze("Ｔｅｓｌａ deliveries beat")
        self.assertEqual(result.clean_text, "Tesla deliveries beat")
        self.assertEqual(result.verdict, "quarantine")

    def test_math_bold_sentiment_word_is_medium(self):
        result = GUARD.analyze("Apple shares \U0001d42c\U0001d42e\U0001d42b\U0001d420\U0001d41e")
        self.assertEqual(result.clean_text, "Apple shares surge")
        self.assertEqual(result.verdict, "review")


class SentimentWordTests(unittest.TestCase):
    def test_mixed_script_sentiment_word(self):
        # Cyrillic DZE in "surge".
        result = GUARD.analyze("Apple shares ѕurge")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.clean_text, "Apple shares surge")
        self.assertEqual(result.flags[0].kind, "mixed_script_word")

    def test_whole_cyrillic_word_inside_english_headline(self):
        # Cyrillic TE, O, ER reading as "TOP".
        result = GUARD.analyze("Tesla is a ТОР pick")
        self.assertEqual(result.verdict, "review")
        self.assertEqual(result.clean_text, "Tesla is a TOP pick")
        self.assertEqual(result.flags[0].kind, "whole_script_lookalike")

    def test_stacked_combining_marks_inside_name(self):
        result = GUARD.analyze("Te̷̸̶sla soars")
        self.assertEqual(result.clean_text, "Tesla soars")
        self.assertEqual(result.tickers, ["TSLA"])
        self.assertEqual(result.verdict, "quarantine")


class EvasionOfLanguageExemptionTests(unittest.TestCase):
    """Attacks shaped to fall inside the exemptions that protect real non-Latin text."""

    def test_whole_headline_in_cyrillic_lookalikes(self):
        # "МЕТА ТОР РІСК" written entirely in Cyrillic, so Cyrillic would "dominate" the headline.
        result = GUARD.analyze("МЕТА ТОР РІСК")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.tickers, ["META"])
        self.assertEqual(result.clean_text, "META TOP PICK")

    def test_fake_subdivision_flag_carrying_hidden_text(self):
        headline = (
            "Apple beats estimates \U0001f3f4"
            + encode_as_tag_characters("lossesandlayoffs")
            + "\U000e007f"
        )
        result = GUARD.analyze(headline)
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.flags[0].evidence, {"decoded_text": "lossesandlayoffs"})

    def test_accent_added_to_watched_name(self):
        result = GUARD.analyze("Tésla soars")
        self.assertEqual(result.verdict, "review")
        self.assertEqual(result.tickers, ["TSLA"])
        self.assertEqual(result.clean_text, "Tesla soars")
        self.assertEqual(result.flags[0].kind, "accented_watchlist_name")

    def test_precomposed_accent_with_cyrillic_letter(self):
        # Precomposed i with dot above plus Cyrillic A.
        result = GUARD.analyze("Nvidíа rallies")
        self.assertNotEqual(result.verdict, "pass")
        self.assertEqual(result.tickers, ["NVDA"])


class NoSilentRepairTests(unittest.TestCase):
    def test_every_change_to_the_text_has_a_flag(self):
        attacked_headlines = [
            "Теsla shares surge",
            "Tes​la stock jumps",
            "Apple shares ѕurge",
            "\U0001d40d\U0001d415\U0001d408\U0001d403\U0001d408\U0001d400 stock soars",
            "Apple beats estimates" + encode_as_tag_characters(" losses"),
            "Tesla is a ТОР pick",
            "Te̷̸̶sla soars",
        ]
        for headline in attacked_headlines:
            with self.subTest(headline=headline):
                result = GUARD.analyze(headline)
                self.assertNotEqual(result.clean_text, headline)
                self.assertTrue(result.flags, "text changed without a flag")


if __name__ == "__main__":
    unittest.main()
