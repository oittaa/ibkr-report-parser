import os
import unittest
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from gcp_storage_emulator.server import create_server  # type: ignore
from moto import mock_s3  # type: ignore

from ibkr_report.definitions import StorageType
from ibkr_report.storage import get_storage
from ibkr_report.tools import Cache

TEST_BUCKET = "test"


class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_data = {"2021-10-25": {"USD": "1.1603"}}
        os.environ["STORAGE_EMULATOR_HOST"] = "http://localhost:9023"
        cls._server = create_server(
            "localhost", 9023, in_memory=True, default_bucket=TEST_BUCKET
        )
        cls._server.start()

    @classmethod
    def tearDownClass(cls):
        cls._server.stop()

    def setUp(self):
        Cache.clear()
        self.storage_dir = Path(mkdtemp())

    def tearDown(self):
        for item in self.storage_dir.iterdir():
            item.unlink()
        self.storage_dir.rmdir()

    def test_non_existent_type(self):
        with self.assertRaises(NotImplementedError):
            get_storage("not-implemented")

    def test_disabled_storage(self):
        storage = get_storage()()
        storage.cache = False
        storage.save(self.test_data)
        self.assertEqual(storage.load(), {})

    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    def test_google_cloud_storage_save_and_load(self):
        storage = get_storage(StorageType.GCP)()
        storage.cache = False
        storage.save(self.test_data)
        self.assertEqual(storage.load(), self.test_data)

    def test_gcp_load_not_existing(self):
        storage = get_storage(StorageType.GCP)(bucket_id=TEST_BUCKET)
        self.assertEqual(storage.load(), {})

    @mock_s3
    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    def test_aws_s3_save_and_load(self):
        storage = get_storage(StorageType.AWS)()
        storage.cache = False
        storage.save(self.test_data)
        self.assertEqual(storage.load(), self.test_data)

    @mock_s3
    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    def test_aws_s3_load_not_existing(self):
        storage = get_storage(StorageType.AWS)()
        self.assertEqual(storage.load(), {})

    def test_local_save_and_load(self):
        storage = get_storage(StorageType.LOCAL)(storage_dir=self.storage_dir)
        storage.cache = False
        storage.save(self.test_data)
        self.assertEqual(storage.load(), self.test_data)

    def test_local_load_not_existing(self):
        storage = get_storage(StorageType.LOCAL)(storage_dir=self.storage_dir)
        self.assertEqual(storage.load(), {})

    def test_local_custom_file_save_and_load(self):
        storage = get_storage(StorageType.LOCAL)(storage_dir=self.storage_dir)
        storage.save(self.test_data, "my-test-file")
        Cache.clear()
        self.assertEqual(storage.load("my-test-file"), self.test_data)
        self.assertEqual(storage.load("not-existing"), {})
        full_path = self.storage_dir.joinpath("my-test-file")
        self.assertTrue(full_path.is_file())

    def test_generating_filenames(self):
        storage = get_storage()()
        name1 = storage.get_filename("test1")
        name2 = storage.get_filename("test2")
        self.assertNotEqual(name1, name2)
        name_default = storage.get_filename()
        self.assertNotEqual(name1, name_default)
        self.assertNotEqual(name2, name_default)

    @patch("ibkr_report.storage.BUCKET_ID", TEST_BUCKET)
    def test_bucket_defined_but_type_not_defined(self):
        with self.assertRaises(ValueError):
            get_storage()


if __name__ == "__main__":
    unittest.main()
