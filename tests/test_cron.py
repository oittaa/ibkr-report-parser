import os
import unittest
from unittest.mock import patch

from gcp_storage_emulator.server import create_server  # type: ignore

from ibkr_report import create_app
from ibkr_report.tools import Cache

TEST_BUCKET = "test"
THIS_PATH = os.path.abspath(os.getcwd())
TEST_URL = f"file://{THIS_PATH}/tests/test-data/eurofxref-hist.zip"


@patch("ibkr_report.exchangerates.EXCHANGE_RATES_URL", TEST_URL)
class IntegrationTests(unittest.TestCase):
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

    def test_get_cron_without_bucket(self):
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.data, b"BUCKET_ID missing!")

    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.cron.BUCKET_ID", TEST_BUCKET)
    @patch("ibkr_report.storage.STORAGE_TYPE", "gcp")
    def test_get_cron(self):
        response = self.app.get("/cron")
        self.assertEqual(response.status_code, 403)
        response = self.app.get("/cron", headers={"X-Appengine-Cron": "true"})
        self.assertEqual(response.data, b"Done!")
        self.assertEqual(response.status_code, 200)

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


if __name__ == "__main__":
    unittest.main()
