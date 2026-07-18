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

    def test_warrants(self):
        """Warrants use Asset Category 'Warrants' and stock-like multiplier 1.

        Sample from https://github.com/oittaa/ibkr-report-parser/issues/522
        (GH8MB6). ClosedLot T. Price is reconstructed as unit cost including
        buy commission: 282.735 / 100 = 2.82735.
        """
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_warrants.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.prices, 2), Decimal("272.00"))
        self.assertEqual(round(report.gains, 2), Decimal("0.00"))
        self.assertEqual(round(report.losses, 2), Decimal("12.46"))
        self.assertEqual(len(report.details), 1)
        self.assertEqual(report.details[0].symbol, "GH8MB6")
        self.assertEqual(report.details[0].quantity, Decimal("100"))
        self.assertEqual(report.details[0].buy_date, "2022-11-23")
        self.assertEqual(report.details[0].sell_date, "2022-11-24")

    def test_prices_match_sum_of_detail_selling_prices(self):
        """Total selling prices must equal the sum of detail row prices.

        Previously totals used Trade Proceeds while details used ClosedLot-based
        prices, which diverged for shorts/options (issue #1458).
        """
        fixtures = (
            "tests/test-data/data_single_account.csv",
            "tests/test-data/data_multi_account.csv",
            "tests/test-data/data_shorting_stocks.csv",
            "tests/test-data/data_numbers_within_quotes.csv",
            "tests/test-data/data_warrants.csv",
            "tests/test-data/data_deemed_acquisition_cost.csv",
            "tests/test-data/data_single_account_2022.csv",
        )
        for path in fixtures:
            with self.subTest(path=path):
                Cache.clear()
                report = Report(use_deemed_acquisition_cost=False)
                with open(path, "rb") as file:
                    report.add_trades(file)
                detail_sum = sum((d.price for d in report.details), Decimal(0))
                self.assertEqual(report.prices, detail_sum, path)

    def test_sell_without_closed_lot_does_not_count_prices(self):
        """A Trade sell/short with no ClosedLot must not inflate totals."""
        csv_data = (
            b"Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
            b"Date/Time,Quantity,T. Price,Proceeds,Comm/Fee\n"
            b'Trades,Data,Trade,Stocks,EUR,ABC,"2020-06-15, 10:00:00",'
            b"-100,10,1000,-1\n"
        )
        report = Report(use_deemed_acquisition_cost=False)
        report.add_trades(csv_data.splitlines())
        self.assertEqual(report.prices, Decimal(0))
        self.assertEqual(report.details, [])
        self.assertEqual(report.gains, Decimal(0))
        self.assertEqual(report.losses, Decimal(0))


if __name__ == "__main__":
    unittest.main()
