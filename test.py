import json
import os
import unittest
from gcp_storage_emulator.server import create_server
from main import app
from unittest.mock import patch

TEST_BUCKET = "test"
TEST_URL = "file://" + os.path.abspath(os.getcwd()) + "/test-data/eurofxref-hist.zip"


@patch("main.EXCHANGE_RATES_URL", TEST_URL)
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
        self._server.wipe()

    def test_get_main_page(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)

    @patch("main.BUCKET_ID", TEST_BUCKET)
    def test_get_cron(self):
        response = self.app.get("/cron")
        self.assertEqual(response.status_code, 403)
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)

    def test_post_single_account(self):
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_single_account_json(self):
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 8518.52)
        self.assertEqual(data_json["gains"], 5964.76)
        self.assertEqual(data_json["losses"], 0)

    def test_post_multi_account_json(self):
        data = {"file": open("test-data/data_multi_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6873.02)
        self.assertEqual(data_json["gains"], 1064.02)
        self.assertEqual(data_json["losses"], 445.98)

    def test_post_data_in_future(self):
        data = {"file": open("test-data/data_dates_in_future.csv", "rb")}
        response = self.app.post("/", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_shorting_stocks(self):
        data = {"file": open("test-data/data_shorting_stocks.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 6034.30)
        self.assertEqual(data_json["gains"], 2644.18)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_deemed_acquisition_cost(self):
        data = {"file": open("test-data/data_deemed_acquisition_cost.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 9982.0)
        self.assertEqual(data_json["gains"], 5989.2)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_closedlot_without_trade(self):
        data = {"file": open("test-data/data_closedlot_without_trade.csv", "rb")}
        response = self.app.post("/", data=data)
        self.assertEqual(response.status_code, 400)

    def test_post_numbers_within_quotes(self):
        data = {"file": open("test-data/data_numbers_within_quotes.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7195.37)
        self.assertEqual(data_json["gains"], 455.67)
        self.assertEqual(data_json["losses"], 0.00)

    def test_post_currency_rate_over_1000(self):
        data = {"file": open("test-data/data_currency_rate_over_1000.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 7.2)
        self.assertEqual(data_json["gains"], 5.0)
        self.assertEqual(data_json["losses"], 0.00)

    @patch("main.LOGGING_LEVEL", "INVALID_LOGGING_LEVEL")
    def test_post_invalid_date_html(self):
        data = {"file": open("test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.headers.get("Content-Type"), "text/html; charset=utf-8"
        )

    def test_post_invalid_date_json(self):
        data = {"file": open("test-data/data_invalid_date.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.headers.get("Content-Type"), "application/json")
        data_json = json.loads(response.data)
        self.assertEqual(
            data_json["error"], "400 Bad Request: Invalid date '20xx-08-23, 09:33:11'"
        )

    @patch("main._cache", {})
    @patch("main._MAXCACHE", 0)
    @patch("main.BUCKET_ID", TEST_BUCKET)
    def test_caching_filled_from_cron(self):
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 200)
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)

    @patch("main.BUCKET_ID", TEST_BUCKET)
    def test_caching_from_previous_request(self):
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data = {"file": open("test-data/data_single_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
