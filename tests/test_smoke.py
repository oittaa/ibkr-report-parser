import json
import os
import unittest
from tempfile import NamedTemporaryFile
from unittest.mock import patch
from urllib.error import HTTPError

from gcp_storage_emulator.server import create_server  # type: ignore

from ibkr_report import create_app
from ibkr_report.definitions import FieldValue, _strtobool
from ibkr_report.tools import Cache, calculate_sri_on_file

TEST_BUCKET = "test"
THIS_PATH = os.path.abspath(os.getcwd())
TEST_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-hist.zip"
TEST_BROKEN_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-broken.csv"

# echo -n "" | openssl dgst -sha384 -binary | openssl base64 -A
EMPTY_FILE_SRI = (
    "sha384-OLBgp1GsljhM2TJ+sbHjaiH9txEUvgdDTAzHv2P24donTt6/529l+9Ua0vFImLlb"
)
TEST_STRING = "alert('Hello, world.');"
# echo -n "alert('Hello, world.');" | openssl dgst -sha384 -binary | openssl base64 -A
TEST_STRING_SRI = (
    "sha384-H8BRh8j48O9oYatfu5AZzq6A9RINhZO5H16dQZngK7T62em8MUt1FLm52t+eX6xO"
)


@patch("ibkr_report.exchangerates.EXCHANGE_RATES_URL", TEST_URL)
class SmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:9023"
        os.environ["GOOGLE_CLOUD_PROJECT"] = "<test>"
        cls._server = create_server(
            "localhost", 9023, in_memory=True, default_bucket=TEST_BUCKET
        )
        cls._server.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.stop()

    def setUp(self):
        app = create_app()
        self.app = app.test_client()
        self.assertEqual(app.debug, False)

    def test_get_main_page(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)

    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.cron.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.storage.STORAGE_TYPE", "gcp")
    def test_get_cron(self):
        response = self.app.get("/cron")
        self.assertEqual(response.status_code, 403)
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.data, b"Done!")
        self.assertEqual(response.status_code, 200)

    def test_get_cron_without_bucket(self):
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data, b"BUCKET_ID missing!")

    @patch("ibkr_report.cron.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    def test_get_cron_with_storage_disabled(self):
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 500)
        msg = (
            b"[BUCKET_ID] set as 'test', but [STORAGE_TYPE] is set as 'disabled'."
            + b" With a bucket [STORAGE_TYPE] needs to be set as [AWS|GCP]."
        )
        self.assertEqual(response.data, msg)

    def test_post_single_account(self):
        data = {"file": open("tests/test-data/data_single_account.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_single_account_json(self):
        data = {"file": open("tests/test-data/data_single_account.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 8518.52)
        self.assertEqual(data_json["gains"], 5964.76)
        self.assertEqual(data_json["losses"], 0)
        self.assertIsInstance(data_json["details"], list)

    def test_post_multi_account_json(self):
        data = {"file": open("tests/test-data/data_multi_account.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6873.02)
        self.assertEqual(data_json["gains"], 1064.02)
        self.assertEqual(data_json["losses"], 445.98)

    def test_post_data_in_future(self):
        data = {"file": open("tests/test-data/data_dates_in_future.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_shorting_stocks(self):
        data = {"file": open("tests/test-data/data_shorting_stocks.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6034.30)
        self.assertEqual(data_json["gains"], 2644.18)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_shorting_not_closed(self):
        data = {"file": open("tests/test-data/data_shorting_not_closed.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6034.30)
        self.assertEqual(data_json["gains"], 0.00)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_deemed_acquisition_cost(self):
        data = {"file": open("tests/test-data/data_deemed_acquisition_cost.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 9982.0)
        self.assertEqual(data_json["gains"], 5989.2)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_closedlot_without_trade(self):
        data = {"file": open("tests/test-data/data_closedlot_without_trade.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_numbers_within_quotes(self):
        data = {"file": open("tests/test-data/data_numbers_within_quotes.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7195.37)
        self.assertEqual(data_json["gains"], 455.67)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_currency_rate_over_1000(self):
        data = {"file": open("tests/test-data/data_currency_rate_over_1000.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7.2)
        self.assertEqual(data_json["gains"], 5.0)
        self.assertEqual(data_json["losses"], 0.00)

    @patch("ibkr_report.tools.LOGGING_LEVEL", "INVALID_LOGGING_LEVEL")
    def test_post_invalid_date_html(self):
        data = {"file": open("tests/test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_invalid_data(self):
        data = {"file": open("tests/test-data/eurofxref-hist.zip", "rb")}
        response = self.app.post("/result", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_invalid_date_json(self):
        data = {"file": open("tests/test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"], "400 Bad Request: Invalid date '20xx-08-23, 09:33:11'"
        )

    def test_post_symbol_mismatch(self):
        data = {"file": open("tests/test-data/data_symbol_mismatch.csv", "rb")}
        response = self.app.post("/result?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"],
            "400 Bad Request: Symbol mismatch! Date: 2021-03-15, Trade: UPST, ClosedLot: XXXX",
        )

    def test_post_wrong_quantities(self):
        data = {"file": open("tests/test-data/data_wrong_quantities.csv", "rb")}
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
            data = {"file": open("tests/test-data/data_single_account.csv", "rb")}
            response = self.app.post("/result?json", data=data)
            self.assertEqual(response.status_code, 400)
            data_json = json.loads(response.data)
            self.assertEqual(
                data_json["error"],
                "400 Bad Request: Maximum number of retries exceeded. Could not retrieve currency exchange rates.",
            )

    @patch("ibkr_report.tools._MAXCACHE", 0)
    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.storage.STORAGE_TYPE", "gcp")
    @patch("ibkr_report.cron.BUCKET_ID", TEST_BUCKET)
    def test_caching_filled_from_cron(self):
        self._server.wipe()
        Cache.clear()
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)
        data = {"file": open("tests/test-data/data_single_account.csv", "rb")}
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

    def test_strtobool(self):
        self.assertTrue(_strtobool("TRUE"))
        self.assertFalse(_strtobool("FALSE"))
        with self.assertRaises(ValueError):
            _strtobool("not_a_bool")

    def test_sri(self):
        with NamedTemporaryFile() as tempf:
            val1 = calculate_sri_on_file(tempf.name)
            tempf.write(TEST_STRING.encode("utf-8"))
            tempf.flush()
            val2 = calculate_sri_on_file(tempf.name)
        self.assertEqual(val1, EMPTY_FILE_SRI)
        self.assertEqual(val2, TEST_STRING_SRI)


if __name__ == "__main__":
    unittest.main()
