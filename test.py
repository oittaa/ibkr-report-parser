import json
import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from urllib.error import HTTPError

from gcp_storage_emulator.server import create_server  # type: ignore

from ibkr_report.definitions import FieldValue
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.report import Report
from ibkr_report.tools import Cache
from main import app

TEST_BUCKET = "test"
THIS_PATH = os.path.abspath(os.getcwd())
TEST_URL = f"file://{THIS_PATH}/test-data/eurofxref-hist.zip"
TEST_BROKEN_URL = f"file://{THIS_PATH}/test-data/eurofxref-broken.csv"


@patch("ibkr_report.exchangerates.BUCKET_ID", TEST_BUCKET)
@patch("ibkr_report.exchangerates.EXCHANGE_RATES_URL", TEST_URL)
class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:9023"
        cls._server = create_server(
            "localhost", 9023, in_memory=True, default_bucket=TEST_BUCKET
        )
        cls._server.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.stop()

    def setUp(self):
        self.app = app.test_client()
        self.assertEqual(app.debug, False)

    def test_get_main_page(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)

    @patch("ibkr_report.cron.BUCKET_ID", TEST_BUCKET)
    def test_get_cron(self):
        response = self.app.get("/cron")
        self.assertEqual(response.status_code, 403)
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"Done!")

    def test_get_cron_without_bucket(self):
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"BUCKET_ID missing!")

    def test_post_single_account(self):
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_single_account_json(self):
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 8518.52)
        self.assertEqual(data_json["gains"], 5964.76)
        self.assertEqual(data_json["losses"], 0)
        self.assertIsInstance(data_json["details"], list)

    def test_post_multi_account_json(self):
        data = {"file": open("test-data/data_multi_account.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6873.02)
        self.assertEqual(data_json["gains"], 1064.02)
        self.assertEqual(data_json["losses"], 445.98)

    def test_post_data_in_future(self):
        data = {"file": open("test-data/data_dates_in_future.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_shorting_stocks(self):
        data = {"file": open("test-data/data_shorting_stocks.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6034.30)
        self.assertEqual(data_json["gains"], 2644.18)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_deemed_acquisition_cost(self):
        data = {"file": open("test-data/data_deemed_acquisition_cost.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 9982.0)
        self.assertEqual(data_json["gains"], 5989.2)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_closedlot_without_trade(self):
        data = {"file": open("test-data/data_closedlot_without_trade.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_numbers_within_quotes(self):
        data = {"file": open("test-data/data_numbers_within_quotes.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7195.37)
        self.assertEqual(data_json["gains"], 455.67)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_currency_rate_over_1000(self):
        data = {"file": open("test-data/data_currency_rate_over_1000.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7.2)
        self.assertEqual(data_json["gains"], 5.0)
        self.assertEqual(data_json["losses"], 0.00)

    @patch("ibkr_report.tools.LOGGING_LEVEL", "INVALID_LOGGING_LEVEL")
    def test_post_invalid_date_html(self):
        data = {"file": open("test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_invalid_data(self):
        data = {"file": open("test-data/eurofxref-hist.zip", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_invalid_date_json(self):
        data = {"file": open("test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"], "400 Bad Request: Invalid date '20xx-08-23, 09:33:11'"
        )

    def test_post_symbol_mismatch(self):
        data = {"file": open("test-data/data_symbol_mismatch.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"],
            "400 Bad Request: Symbol mismatch! Date: 2021-03-15, Trade: UPST, ClosedLot: XXXX",
        )

    def test_post_wrong_quantities(self):
        data = {"file": open("test-data/data_wrong_quantities.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"],
            '400 Bad Request: Invalid data. "Trade" and "ClosedLot" quantities do not match. Date: 2021-03-15, Symbol: UPST',
        )

    def test_404_error_from_downloading(self):
        self._server.wipe()
        Cache.clear()
        with patch(
            "ibkr_report.exchangerates.urlopen",
            side_effect=HTTPError("", 404, "Test", {}, None),
        ):
            data = {"file": open("test-data/data_single_account.csv", "rb")}
            response = self.app.post("/result?json", data=data)
            self.assertEqual(response.status_code, 400)
            data_json = json.loads(response.data)
            self.assertEqual(
                data_json["error"],
                "400 Bad Request: Maximum number of retries exceeded. Could not retrieve currency exchange rates.",
            )

    @patch("ibkr_report.tools._MAXCACHE", 0)
    def test_caching_filled_from_cron(self):
        self._server.wipe()
        Cache.clear()

        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)

    @patch("ibkr_report.tools._MAXCACHE", 5)
    def test_cache_pruning(self):
        Cache.set("my_key", "my_value")
        self.assertEqual(Cache.get("my_key"), "my_value")

        value = "x {}"
        for key in range(5):
            Cache.set(key, value.format(key))
        for key in range(5):
            self.assertEqual(Cache.get(key), value.format(key))

        self.assertIsNone(Cache.get("my_key"))

    def test_str_enum(self):
        self.assertEqual(FieldValue.TRADES, "Trades")


@patch("ibkr_report.exchangerates.EXCHANGE_RATES_URL", TEST_URL)
class ReportTest(unittest.TestCase):
    def test_without_deemed_cost(self):
        report = Report(use_deemed_acquisition_cost=False)
        with open("test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(report.prices, Decimal("9982.0"))
        self.assertEqual(round(report.gains, 2), Decimal("6937.94"))
        self.assertEqual(report.losses, Decimal("0.00"))

    def test_report_currency_usd(self):
        report = Report(report_currency="USD", use_deemed_acquisition_cost=False)
        with open("test-data/data_deemed_acquisition_cost.csv", "rb") as file:
            report.add_trades(file)
        self.assertEqual(round(report.prices, 2), Decimal("10957.24"))
        self.assertEqual(round(report.gains, 2), Decimal("6826.73"))
        self.assertEqual(round(report.losses, 2), Decimal("0.00"))


class ExchangeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rates = ExchangeRates(TEST_URL)

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

    def test_currency_does_not_exist(self):
        with self.assertRaises(ValueError):
            self.rates.get_rate("KEKW", "USD", "2015-12-01")

    def test_far_in_the_future(self):
        with self.assertRaises(ValueError):
            self.rates.get_rate("USD", "CAD", "2500-01-01")

    def test_broken_input(self):
        with open("test-data/eurofxref-broken.csv", "rb") as file:
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


if __name__ == "__main__":
    unittest.main()
