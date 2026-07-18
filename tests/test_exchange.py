import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from ibkr_report import ExchangeRates
from ibkr_report.exchangerates import clear_rate_parse_cache
from ibkr_report.tools import Cache

THIS_PATH = os.path.abspath(os.getcwd())
TEST_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-hist.zip"
TEST_BROKEN_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-broken.csv"


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clear_rate_parse_cache()
        cls.rates = ExchangeRates(TEST_URL)

    def setUp(self):
        Cache.clear()

    def test_self(self):
        same_same = self.rates.get_rate("USD", "USD", "2015-12-01")
        self.assertEqual(same_same, 1)

    def test_sek_usd(self):
        sek_usd = self.rates.get_rate("SEK", "USD", "2015-12-01")
        self.assertLess(sek_usd, Decimal("0.2"))

    def test_back_and_forth(self):
        sek_usd = self.rates.get_rate("SEK", "USD", "2015-12-01")
        usd_sek = self.rates.get_rate("USD", "SEK", "2015-12-01")
        should_be_one = sek_usd * usd_sek
        self.assertEqual(should_be_one, 1)
        self.assertNotEqual(sek_usd, 1)

    def test_from_euro(self):
        eur_usd = self.rates.get_rate("EUR", "USD", "2015-12-01")
        self.assertGreater(eur_usd, 1)

    def test_to_euro(self):
        nok_eur = self.rates.get_rate("NOK", "EUR", "2010-01-01")
        self.assertLess(nok_eur, Decimal("0.2"))

    @patch("ibkr_report.exchangerates.MAX_BACKTRACK_DAYS", 0)
    def test_no_backtrack(self):
        with self.assertRaises(ValueError):
            self.rates.get_rate("NOK", "EUR", "2010-01-01")

    def test_currency_does_not_exist(self):
        with self.assertRaises(ValueError):
            self.rates.get_rate("KEKW", "USD", "2015-12-01")

    def test_far_in_the_future(self):
        with self.assertRaises(ValueError):
            self.rates.get_rate("USD", "CAD", "2500-01-01")

    def test_broken_input(self):
        with open("tests/test-data/eurofxref-broken.csv", "rb") as file:
            self.rates.add_to_exchange_rates(file)
        eur_usd = self.rates.get_rate("EUR", "USD", "2021-10-26")
        self.assertEqual(eur_usd, Decimal("1.1618"))
        eur_usd = self.rates.get_rate("EUR", "USD", "2021-10-25")
        self.assertEqual(eur_usd, Decimal("1.1603"))

    def test_download_without_zip(self):
        rates = ExchangeRates(TEST_BROKEN_URL)
        eur_usd = rates.get_rate("EUR", "USD", "2021-10-26")
        self.assertEqual(eur_usd, Decimal("1.1618"))
        with self.assertRaises(ValueError):
            eur_usd = rates.get_rate("EUR", "USD", "2021-10-25")

    def test_process_cache_avoids_reparse_after_tools_cache_clear(self):
        """Parsed rates stay in process memory across tools.Cache.clear()."""
        clear_rate_parse_cache()
        first = ExchangeRates(TEST_URL)
        Cache.clear()
        with patch.object(
            ExchangeRates, "download_official_rates", autospec=True
        ) as download:
            second = ExchangeRates(TEST_URL)
            download.assert_not_called()
        self.assertEqual(
            first.get_rate("EUR", "USD", "2015-12-01"),
            second.get_rate("EUR", "USD", "2015-12-01"),
        )


if __name__ == "__main__":
    unittest.main()
