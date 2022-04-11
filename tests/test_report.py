import os
import unittest
from decimal import Decimal
from unittest.mock import patch

from ibkr_report import Report
from ibkr_report.tools import Cache

THIS_PATH = os.path.abspath(os.getcwd())
TEST_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-hist.zip"


@patch("ibkr_report.exchangerates.EXCHANGE_RATES_URL", TEST_URL)
class ReportTest(unittest.TestCase):
    def setUp(self):
        Cache.clear()

    def test_without_deemed_cost(self):
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(report.prices, Decimal("9982.0"))
        self.assertEqual(round(report.gains, 2), Decimal("6937.94"))
        self.assertEqual(report.losses, Decimal("0.00"))

    def test_report_currency_usd(self):
        report = Report(report_currency="USD", use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.prices, 2), Decimal("10957.24"))
        self.assertEqual(round(report.gains, 2), Decimal("6826.73"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))

    def test_report_currency_eur_lowercase(self):
        report = Report(report_currency="eur")
        with open("tests/test-data/data_single_account.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.prices, 2), Decimal("8518.52"))
        self.assertEqual(round(report.gains, 2), Decimal("5964.76"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))

    def test_report_ibkr_2022_format(self):
        report = Report()
        with open("tests/test-data/data_single_account_2022.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.prices, 2), Decimal("2626.77"))
        self.assertEqual(round(report.gains, 2), Decimal("429.65"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))


if __name__ == "__main__":
    unittest.main()
