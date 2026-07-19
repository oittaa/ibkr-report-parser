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
        self.assertEqual(report.proceeds, Decimal("9982.0"))
        self.assertEqual(round(report.gains, 2), Decimal("6937.94"))
        self.assertEqual(report.losses, Decimal("0.00"))
        self.assertFalse(any(d.used_deemed_acquisition_cost for d in report.disposals))

    def test_deemed_cost_marks_rows_where_applied(self):
        """Flag is set only when deemed acquisition cost reduces the gain."""
        report = Report(use_deemed_acquisition_cost=True)
        with open("tests/test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.gains, 2), Decimal("5989.2"))
        self.assertTrue(any(d.used_deemed_acquisition_cost for d in report.disposals))
        for d in report.disposals:
            if d.used_deemed_acquisition_cost:
                # 10y+ holding → 40% deemed cost → gain is 60% of selling price
                self.assertEqual(
                    round(d.realized, 2), round(d.proceeds * Decimal("0.6"), 2)
                )
            else:
                self.assertFalse(d.used_deemed_acquisition_cost)

    def test_report_currency_usd(self):
        report = Report(report_currency="USD", use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.proceeds, 2), Decimal("10957.24"))
        self.assertEqual(round(report.gains, 2), Decimal("6826.73"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))

    def test_report_currency_eur_lowercase(self):
        report = Report(report_currency="eur")
        with open("tests/test-data/data_single_account.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.proceeds, 2), Decimal("8518.52"))
        self.assertEqual(round(report.gains, 2), Decimal("5964.76"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))

    def test_report_ibkr_2022_format(self):
        report = Report()
        with open("tests/test-data/data_single_account_2022.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.proceeds, 2), Decimal("2626.77"))
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
        self.assertEqual(round(report.proceeds, 2), Decimal("272.00"))
        self.assertEqual(round(report.gains, 2), Decimal("0.00"))
        self.assertEqual(round(report.losses, 2), Decimal("12.46"))
        self.assertEqual(len(report.disposals), 1)
        self.assertEqual(report.disposals[0].symbol, "GH8MB6")
        self.assertEqual(report.disposals[0].quantity, Decimal("100"))
        self.assertEqual(report.disposals[0].acquired_on.isoformat(), "2022-11-23")
        self.assertEqual(report.disposals[0].disposed_on.isoformat(), "2022-11-24")

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
            "tests/test-data/data_option_assignment.csv",
        )
        for path in fixtures:
            with self.subTest(path=path):
                Cache.clear()
                report = Report(use_deemed_acquisition_cost=False)
                with open(path, "rb") as file:
                    report.add_trades(file)
                detail_sum = sum((d.proceeds for d in report.disposals), Decimal(0))
                self.assertEqual(report.proceeds, detail_sum, path)

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
        self.assertEqual(report.proceeds, Decimal(0))
        self.assertEqual(report.disposals, ())
        self.assertEqual(report.gains, Decimal(0))
        self.assertEqual(report.losses, Decimal(0))

    def test_option_assignment_skips_option_and_folds_premium_into_stock(self):
        """Covered-call assignments: no option rows; premium in stock selling price.

        Real IBKR 2025 activity excerpt (issue #1191): short calls assigned into
        stock sales. Option Realized P/L is 0; premium is part of stock P/L.
        """
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_option_assignment.csv", "rb") as file:
            report.add_trades(file)

        # Four stock assignment lots; no option detail rows.
        self.assertEqual(len(report.disposals), 4)
        symbols = {d.symbol for d in report.disposals}
        self.assertEqual(symbols, {"ARKK", "NVDA", "SOFI"})
        option_symbols = {
            "ARKK 19SEP25 80 C",
            "NVDA 18JUL25 150 C",
            "NVDA 15AUG25 170 C",
            "SOFI 19SEP25 25 C",
        }
        self.assertTrue(symbols.isdisjoint(option_symbols))

        self.assertEqual(round(report.proceeds, 2), Decimal("39509.55"))
        self.assertEqual(round(report.gains, 2), Decimal("34087.02"))
        self.assertEqual(report.losses, Decimal("0"))

        # ARKK: strike proceeds 8000 + premium 162.94576 USD → EUR on 2025-09-19
        arkk = next(d for d in report.disposals if d.symbol == "ARKK")
        self.assertEqual(arkk.quantity, Decimal("100"))
        self.assertEqual(arkk.disposed_on.isoformat(), "2025-09-19")
        self.assertEqual(arkk.acquired_on.isoformat(), "2022-10-27")
        self.assertEqual(round(arkk.proceeds, 2), Decimal("6955.48"))
        self.assertEqual(round(arkk.realized, 2), Decimal("3109.39"))

        detail_sum = sum((d.proceeds for d in report.disposals), Decimal(0))
        self.assertEqual(report.proceeds, detail_sum)

    def test_option_expiry_still_reported(self):
        """Option expirations (code Ep) remain normal closed disposals."""
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_multi_account.csv", "rb") as file:
            report.add_trades(file)
        option_rows = [d for d in report.disposals if "CLOV" in d.symbol]
        self.assertEqual(len(option_rows), 3)
        self.assertTrue(all(d.realized > 0 for d in option_rows))

    def test_short_put_assignment_reduces_basis_multi_file(self):
        """Short put assigned in 2023; stock sold in 2024 — premium cuts cost basis.

        Files uploaded newest-first to prove order independence. Report year is
        2024 only; option rows are omitted; realized = sell - (strike - premium).
        """
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_short_put_sell_2024.csv", "rb") as file:
            report.add_trades(file)
        with open("tests/test-data/data_short_put_assign_2023.csv", "rb") as file:
            report.add_trades(file)

        self.assertEqual(report.file_count, 2)
        self.assertEqual(report.report_year, 2024)
        self.assertEqual(len(report.disposals), 1)
        row = report.disposals[0]
        self.assertEqual(row.symbol, "ABC")
        self.assertEqual(row.quantity, Decimal("100"))
        self.assertEqual(row.acquired_on.isoformat(), "2023-08-16")
        self.assertEqual(row.disposed_on.isoformat(), "2024-03-15")
        # Selling price: 100 * 60 = 6000; cost: 5000 - 200 premium = 4800
        self.assertEqual(row.acquisition_cost, Decimal("4800"))
        self.assertEqual(row.proceeds, Decimal("6000"))
        self.assertEqual(row.realized, Decimal("1200"))
        self.assertEqual(report.proceeds, Decimal("6000"))
        self.assertEqual(report.gains, Decimal("1200"))
        self.assertEqual(report.losses, Decimal("0"))
        self.assertTrue(all(" P" not in d.symbol for d in report.disposals))

    def test_short_put_without_prior_year_has_no_premium(self):
        """2024-only file cannot recover 2023 put premium — strike cost only."""
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_short_put_sell_2024.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(len(report.disposals), 1)
        self.assertEqual(report.disposals[0].realized, Decimal("1000"))
        self.assertEqual(report.report_year, 2024)

    def test_long_call_exercise_increases_basis(self):
        """Long call exercise: premium paid is added to stock acquisition cost."""
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_long_call_exercise.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(report.report_year, 2024)
        self.assertEqual(len(report.disposals), 1)
        row = report.disposals[0]
        self.assertEqual(row.symbol, "XYZ")
        # Sell 5500 - buy (4000 + 300 premium) = 1200
        self.assertEqual(row.proceeds, Decimal("5500"))
        self.assertEqual(row.realized, Decimal("1200"))
        self.assertNotIn("XYZ 15MAR24 40 C", {d.symbol for d in report.disposals})

    def test_long_put_exercise_reduces_selling_price(self):
        """Long put exercise: premium paid reduces stock selling price."""
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_long_put_exercise.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(report.report_year, 2024)
        self.assertEqual(len(report.disposals), 1)
        row = report.disposals[0]
        self.assertEqual(row.symbol, "QRS")
        # Sell (4500 - 150 premium) - buy 5000 = -650
        self.assertEqual(row.proceeds, Decimal("4350"))
        self.assertEqual(row.realized, Decimal("-650"))
        self.assertEqual(report.losses, Decimal("650"))

    def test_latest_year_filter_hides_prior_disposals(self):
        """Prior-year stock sales are dropped when a later year is present."""
        report = Report(use_deemed_acquisition_cost=False)
        with open("tests/test-data/data_prior_year_disposal.csv", "rb") as file:
            report.add_trades(file)
        with open("tests/test-data/data_short_put_sell_2024.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(report.report_year, 2024)
        self.assertEqual(len(report.disposals), 1)
        self.assertEqual(report.disposals[0].symbol, "ABC")
        # No 2023 premium file → unadjusted 1000 gain on ABC
        self.assertEqual(report.disposals[0].realized, Decimal("1000"))
        self.assertEqual(report.proceeds, Decimal("6000"))

    def test_partial_put_assigned_lot_prorates_premium(self):
        """Selling half of put-assigned shares uses half the premium."""
        assign = (
            b"Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
            b"Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code\n"
            b"Trades,Data,Trade,Equity and Index Options,EUR,ABC 16AUG23 50 P,"
            b'"2023-08-16, 16:20:00",1,0,0,0,200,0,A;C\n'
            b"Trades,Data,ClosedLot,Equity and Index Options,EUR,ABC 16AUG23 50 P,"
            b"2023-07-01,-1,2.0,,,-200,0,ST\n"
            b'Trades,Data,Trade,Stocks,EUR,ABC,"2023-08-16, 16:20:00",'
            b"100,50,-5000,0,5000,0,A;O\n"
        )
        sell_half = (
            b"Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,"
            b"Date/Time,Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code\n"
            b'Trades,Data,Trade,Stocks,EUR,ABC,"2024-03-15, 10:00:00",'
            b"-50,60,3000,0,-2500,500,C\n"
            b"Trades,Data,ClosedLot,Stocks,EUR,ABC,2023-08-16,50,50,,,2500,500,ST\n"
        )
        report = Report(use_deemed_acquisition_cost=False)
        report.add_trades(assign.splitlines())
        report.add_trades(sell_half.splitlines())
        self.assertEqual(len(report.disposals), 1)
        # Sell 3000 - buy (2500 - 100 half premium) = 600
        self.assertEqual(report.disposals[0].realized, Decimal("600"))


if __name__ == "__main__":
    unittest.main()
