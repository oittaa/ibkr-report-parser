import json
import os
import unittest

from main import app
from unittest.mock import patch

TEST_URL = (
    "file://"
    + os.path.abspath(os.getcwd())
    + "/test-data/valuuttakurssit_short_xml_fi.csv"
)


@patch("main.EXCHANGE_RATES_URL", TEST_URL)
class SmokeTests(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.assertEqual(app.debug, False)

    def test_get_main_page(self):
        response = self.app.get("/")
        self.assertEqual(response.status_code, 200)

    def test_get_cron(self):
        response = self.app.get("/cron")
        self.assertEqual(response.status_code, 403)

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
        self.assertEqual(data_json["prices"], 15525.69)
        self.assertEqual(data_json["gains"], 0.08)
        self.assertEqual(data_json["losses"], 1324.88)

    def test_post_multi_account_json(self):
        data = {"file": open("test-data/data_multi_account.csv", "rb")}
        response = self.app.post("/?json", data=data)
        self.assertEqual(response.status_code, 200)
        data_json = json.loads(response.data)
        self.assertEqual(data_json["prices"], 4217.61)
        self.assertEqual(data_json["gains"], 360.81)
        self.assertEqual(data_json["losses"], 455.57)

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
        self.assertEqual(data_json["gains"], 2957.89)
        self.assertEqual(data_json["losses"], 0.00)


if __name__ == "__main__":
    unittest.main()
