"""Real headlines in many languages must pass untouched: no flags, no changes.

This is what separates the guard from "map every Cyrillic letter to Latin".
"""

import unittest

from headline_antidote import HeadlineAntidote, PAPER_WATCHLIST

GUARD = HeadlineAntidote(PAPER_WATCHLIST)

CLEAN_HEADLINES = [
    # English, including accents, possessives, tickers and multi-word names.
    "Tesla shares surge after record deliveries",
    "NVIDIA beats estimates as data-centre demand soars",
    "Nestlé and L'Oréal lead European consumer stocks higher",
    "Eli Lilly and Exxon-Mobil rise; JPMorgan Chase flat; Tesla's sales slip",
    "$AAPL, $MSFT and $GOOGL close at record highs",
    "Biotech rally: α-synuclein trial data lifts shares",
    "Alphabet's Q3 revenue tops $100bn for the first time",
    "CO₂ credits jump 5% as EU tightens cap",
    # Russian, including words made only of Latin-looking letters (сахар, орех, рост).
    "Акции «Газпрома» выросли на 3% после отчёта",
    "ЦБ сохранил ключевую ставку на уровне 16%",
    "Цена на сахар и орех выросла, рост продолжится",
    "Сбербанк увеличил чистую прибыль на 12%",
    "СБЕРБАНК УВЕЛИЧИЛ ЧИСТУЮ ПРИБЫЛЬ",
    "РОСТ ЦЕН НА НЕФТЬ ПРОДОЛЖИЛСЯ",
    # Russian headlines that contain Latin brand names.
    "Акции NVIDIA выросли на фоне спроса на чипы",
    "Tesla снизила цены на Model Y в Китае",
    "Apple представила новый iPhone",
    # Ukrainian.
    "Нацбанк України підвищив облікову ставку",
    "Мета компанії — вийти на ринок ЄС",
    # Serbian, both alphabets.
    "Народна банка Србије задржала референтну каматну стопу",
    "Narodna banka Srbije zadržala referentnu kamatnu stopu",
    # Bulgarian.
    "Българската народна банка запази лихвата",
    # Greek.
    "Η Τράπεζα της Ελλάδος αύξησε τις προβλέψεις για το ΑΕΠ",
    "Άνοδος για το Χρηματιστήριο Αθηνών",
    "ΑΝΟΔΟΣ ΓΙΑ ΤΟ ΧΡΗΜΑΤΙΣΤΗΡΙΟ ΑΘΗΝΩΝ",
    # Persian with zero-width non-joiners, Arabic, Hebrew with a right-to-left mark.
    "دولت می‌خواهد مالیات را کاهش دهد",
    "البنك المركزي يرفع سعر الفائدة",
    "בנק ישראל הותיר את הריבית ללא שינוי‏",
    # Hindi, with a zero-width joiner inside a conjunct.
    "रिज़र्व बैंक ने रेपो दर में बदलाव नहीं किया",
    "क्‍ष शेयर बाज़ार में तेज़ी",
    # Japanese (mixed scripts in one word, full-width letters), Chinese, Korean.
    "トヨタ自動車の株価が上昇",
    "ＴＯＰＩＸ、３日続伸",
    "英伟达股价创新高",
    "삼성전자 주가 상승",
    # Spanish ordinal indicator and German.
    "El 1º de mayo la bolsa cerró al alza",
    "Börse Frankfurt: DAX schließt höher",
    # Emoji: ZWJ sequences, skin tones, keycaps, and a subdivision flag made of tag characters.
    "Tesla \U0001f680 shares surge \U0001f468‍\U0001f4bb",
    "Apple \U0001f44d\U0001f3fd beats estimates 1️⃣",
    "\U0001f3f4\U000e0067\U000e0062\U000e0073\U000e0063\U000e0074\U000e007f Scottish banks rally",
]


class RealLanguageTests(unittest.TestCase):
    def test_real_headlines_have_no_flags(self):
        for headline in CLEAN_HEADLINES:
            with self.subTest(headline=headline):
                result = GUARD.analyze(headline)
                self.assertEqual(result.flags, [])
                self.assertEqual(result.verdict, "pass")

    def test_real_headlines_are_not_changed(self):
        for headline in CLEAN_HEADLINES:
            with self.subTest(headline=headline):
                result = GUARD.analyze(headline)
                # Full-width forms are folded for the model even when they are legitimate.
                if "ＴＯ" in headline:
                    continue
                self.assertEqual(result.clean_text, headline)

    def test_latin_brand_names_in_russian_headlines_are_recognised(self):
        result = GUARD.analyze("Акции NVIDIA выросли на фоне спроса на чипы")
        self.assertEqual(result.tickers, ["NVDA"])

    def test_cyrillic_word_spelled_like_a_ticker_in_a_cyrillic_headline_is_only_low(self):
        # "МЕТА" means "goal" in Ukrainian; it is spelled with letters that look like META.
        result = GUARD.analyze("Головна МЕТА компанії — вийти на ринок ЄС")
        self.assertEqual(result.verdict, "pass")
        self.assertEqual(result.tickers, [])
        self.assertEqual(len(result.flags), 1)
        self.assertEqual(result.flags[0].kind, "possible_watchlist_lookalike")
        self.assertEqual(result.clean_text, "Головна МЕТА компанії — вийти на ринок ЄС")

    def test_same_cyrillic_word_inside_an_english_headline_is_an_attack(self):
        result = GUARD.analyze("МЕТА shares slump")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.tickers, ["META"])

    def test_russian_transliteration_of_a_name_is_not_flagged(self):
        result = GUARD.analyze("Акции Тесла упали на 5%")
        self.assertEqual(result.flags, [])

    def test_attack_inside_a_russian_headline_is_still_caught(self):
        # Latin "Tesla" with a Cyrillic IE, inside Russian text.
        result = GUARD.analyze("Акции Tеsla упали на 5%")
        self.assertEqual(result.verdict, "quarantine")
        self.assertEqual(result.tickers, ["TSLA"])


if __name__ == "__main__":
    unittest.main()
