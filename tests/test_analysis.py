import unittest
from analysis import analyze_pair

class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.pair = {
            "priceUsd": "1.0", "pairCreatedAt": 1793890000000,
            "liquidity": {"usd": 60000}, "volume": {"m5": 80000},
            "txns": {"m5": {"buys": 120, "sells": 50}},
            "priceChange": {"m5": 3, "h1": 12},
        }

    def test_market_candidate_has_unverified_security_status(self):
        result = analyze_pair(self.pair, min_score=70)
        self.assertEqual(result["security_status"], "UNVERIFIED")
        self.assertIsInstance(result["score"], int)

    def test_low_liquidity_is_rejected(self):
        self.pair["liquidity"]["usd"] = 1000
        result = analyze_pair(self.pair)
        self.assertFalse(result["eligible"])
        self.assertTrue(any("Likidite" in reason for reason in result["reasons"]))

    def test_extreme_short_term_pump_is_rejected(self):
        self.pair["priceChange"]["m5"] = 40
        result = analyze_pair(self.pair)
        self.assertFalse(result["eligible"])

if __name__ == "__main__":
    unittest.main()
