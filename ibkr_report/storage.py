"""Storage to save and load exchange rates."""

import importlib
import json
import logging
import os
from datetime import datetime
from lzma import compress, decompress
from pathlib import Path

from ibkr_report.definitions import (
    _DATE,
    BUCKET_ID,
    SAVED_RATES_FILE,
    STORAGE_DIR,
    STORAGE_TYPE,
    CurrencyDict,
    StorageType,
)

log = logging.getLogger(__name__)


class Storage:
    """Storage class to save exchange rates."""

    def save(self, content: CurrencyDict, file_name: str = None) -> None:
        """Save CurrencyDict to storage."""
        file_name = file_name or self.get_rates_file_name()
        log.debug("Save to '%s' using %s backend.", file_name, self.name)
        self._save(content, file_name)

    def load(self, file_name: str = None) -> CurrencyDict:
        """Load CurrencyDict from storage."""
        file_name = file_name or self.get_rates_file_name()
        log.debug("Load '%s' using %s backend.", file_name, self.name)
        return self._load(file_name) or {}

    def _save(self, content: CurrencyDict, file_name: str) -> None:
        pass

    def _load(self, file_name: str) -> CurrencyDict:
        pass

    @property
    def name(self) -> str:
        """Class name"""
        return self.__class__.__name__

    @staticmethod
    def get_rates_file_name() -> str:
        """Generate file name based on the current date."""
        today = datetime.now().strftime(_DATE)
        return SAVED_RATES_FILE.format(today)

    @staticmethod
    def encode(data: CurrencyDict) -> bytes:
        """Encode dictionary so it can be saved."""
        return compress(json.dumps(data).encode("utf-8"))

    @staticmethod
    def decode(data: bytes) -> CurrencyDict:
        """Decode saved dictionary."""
        return json.loads(decompress(data).decode("utf-8"))


class StorageDisabled(Storage):
    """Storage backend that doesn't do anything."""


class AmazonS3(Storage):
    """Amazon S3 backend"""

    def __init__(self, bucket_id: str = None) -> None:
        boto3 = importlib.import_module("boto3")

        log.debug("Using %s backend.", self.name)
        self.bucket_id = bucket_id
        self.aws_s3 = boto3.resource("s3")  # type: ignore
        bucket = self.aws_s3.Bucket(self.bucket_id)
        bucket.create()

    def _save(self, content: CurrencyDict, file_name: str) -> None:
        obj = self.aws_s3.Object(self.bucket_id, file_name)
        obj.put(Body=self.encode(content))

    def _load(self, file_name: str) -> CurrencyDict:
        obj = self.aws_s3.Object(self.bucket_id, file_name)
        try:
            return self.decode(obj.get()["Body"].read())
        except self.aws_s3.meta.client.exceptions.NoSuchKey:
            return {}


class GoogleCloudStorage(Storage):
    """Google Cloud Storage backend"""

    def __init__(self, bucket_id: str = None) -> None:
        storage = importlib.import_module("google.cloud.storage")
        exceptions = importlib.import_module("google.cloud.exceptions")

        log.debug("Using %s backend.", self.name)
        self.bucket_id = bucket_id
        if os.getenv("STORAGE_EMULATOR_HOST"):
            # Local testing etc.
            client = storage.Client.create_anonymous_client()  # type: ignore
            client.project = "<none>"
        else:
            client = storage.Client()  # type: ignore
        try:
            self.bucket = client.get_bucket(self.bucket_id)
        except exceptions.NotFound:  # type: ignore
            self.bucket = client.create_bucket(self.bucket_id)

    def _save(self, content: CurrencyDict, file_name: str) -> None:
        blob = self.bucket.blob(file_name)
        blob.upload_from_string(self.encode(content))

    def _load(self, file_name: str) -> CurrencyDict:
        blob = self.bucket.get_blob(file_name)
        if blob:
            return self.decode(blob.download_as_bytes())
        return {}


class LocalStorage(Storage):
    """Local storage backend."""

    def __init__(self, storage_dir: str) -> None:
        log.debug("Using %s backend.", self.name)
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _save(self, content: CurrencyDict, file_name: str) -> None:
        with open(self.storage_dir.joinpath(file_name), "wb") as file:
            file.write(self.encode(content))

    def _load(self, file_name: str) -> CurrencyDict:
        try:
            with open(self.storage_dir.joinpath(file_name), "rb") as file:
                return self.decode(file.read())
        except FileNotFoundError:
            return {}


def get_storage(
    storage_type: StorageType = None, bucket_id: str = None, storage_dir: str = None
) -> Storage:
    """Returns a storage backend."""
    if storage_type is None:
        storage_type = StorageType(STORAGE_TYPE)
    if bucket_id is None:
        bucket_id = BUCKET_ID
    if storage_dir is None:
        storage_dir = STORAGE_DIR

    if storage_type is StorageType.AWS:
        return AmazonS3(bucket_id)
    if storage_type is StorageType.GCP:
        return GoogleCloudStorage(bucket_id)

    # Past the cloud storage options, fail if bucket_id is set
    if bucket_id:
        raise ValueError(
            f"[BUCKET_ID|BUCKET_NAME] set as {bucket_id!r}, but [STORAGE_TYPE] is not set."
        )
    if storage_type is StorageType.LOCAL:
        return LocalStorage(storage_dir)
    if storage_type is StorageType.DISABLED:
        return StorageDisabled()

    raise NotImplementedError(f"Not implemented: {storage_type!r}")
