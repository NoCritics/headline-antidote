"""The guard must be cheap enough to run on every headline."""

import time
import unittest

from headline_guard import HeadlineGuard, PAPER_WATCHLIST

MAXIMUM_AVERAGE_MILLISECONDS = 1.0

SAMPLE_HEADLINES = [
    "Tesla shares surge after record deliveries",
    "Теsla shares surge",
    "Акции NVIDIA выросли на фоне спроса на чипы",
    "Eli Lilly and Exxon-Mobil rise; JPMorgan Chase flat; Tesla's sales slip",
    "Apple shares ѕurge",
    "トヨタ自動車の株価が上昇",
    "Η Τράπεζα της Ελλάδος αύξησε τις προβλέψεις για το ΑΕΠ",
    "Tes​la stock jumps",
]


class PerformanceTests(unittest.TestCase):
    def test_average_time_per_headline(self):
        guard = HeadlineGuard(PAPER_WATCHLIST)
        repetitions = 500
        started = time.perf_counter()
        for _ in range(repetitions):
            for headline in SAMPLE_HEADLINES:
                guard.analyze(headline)
        elapsed_seconds = time.perf_counter() - started
        average_milliseconds = elapsed_seconds * 1000 / (repetitions * len(SAMPLE_HEADLINES))
        print(f"\naverage {average_milliseconds * 1000:.0f} microseconds per headline")
        self.assertLess(average_milliseconds, MAXIMUM_AVERAGE_MILLISECONDS)


if __name__ == "__main__":
    unittest.main()
