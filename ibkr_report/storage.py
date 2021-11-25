"""Storage to save and load exchange rates."""

import importlib
import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from lzma import compress, decompress
from pathlib import Path
from typing import Optional, Type

from ibkr_report.definitions import (
    BUCKET_ID,
    DATE_FORMAT,
    SAVED_RATES_FILE,
    STORAGE_DIR,
    STORAGE_TYPE,
    CurrencyDict,
    StorageType,
)
from ibkr_report.tools import Cache

log = logging.getLogger(__name__)


class Storage(ABC):
    """Storage class to save exchange rates."""

    cache: bool = True

    def save(self, content: CurrencyDict, filename: str = None) -> None:
        """Save CurrencyDict to storage."""
        filename = filename or self.get_filename()
        log.debug("Save to '%s' using %s backend.", filename, self.name)
        if self.cache:
            Cache.set(filename, content)
        self._save(content, filename)

    def load(self, filename: str = None) -> CurrencyDict:
        """Load CurrencyDict from storage."""
        filename = filename or self.get_filename()
        log.debug("Load '%s' using %s backend.", filename, self.name)
        if self.cache:
            content = Cache.get(filename)
            if content:
                log.debug("Cache hit: %s", filename)
                return content
            log.debug("Cache miss: %s", filename)
        content = self._load(filename)
        if content and self.cache:
            Cache.set(filename, content)
        return content

    @abstractmethod
    def _save(self, content: CurrencyDict, filename: str) -> None:
        """Backend specific `save` implementation."""

    @abstractmethod
    def _load(self, filename: str) -> CurrencyDict:
        """Backend specific `load` implementation."""

    @property
    def name(self) -> str:
        """Class name"""
        return self.__class__.__name__

    @staticmethod
    def get_filename(identifier: str = None) -> str:
        """Generate a filename based on the current date.

        Optionally you can give your own identifier that distinguishes files.
        """
        if identifier is None:
            identifier = datetime.now().strftime(DATE_FORMAT)
        return SAVED_RATES_FILE.format(identifier)

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

    def _save(self, content: CurrencyDict, filename: str) -> None:
        pass

    def _load(self, filename: str) -> CurrencyDict:
        return {}


class AmazonS3(Storage):
    """Amazon S3 backend"""

    def __init__(self, bucket_id: str = None) -> None:
        boto3 = importlib.import_module("boto3")

        log.debug("Using %s backend.", self.name)
        self.bucket_id = bucket_id or BUCKET_ID
        self.aws_s3 = boto3.resource("s3")  # type: ignore
        bucket = self.aws_s3.Bucket(self.bucket_id)
        bucket.create()

    def _save(self, content: CurrencyDict, filename: str) -> None:
        obj = self.aws_s3.Object(self.bucket_id, filename)
        obj.put(Body=self.encode(content))

    def _load(self, filename: str) -> CurrencyDict:
        obj = self.aws_s3.Object(self.bucket_id, filename)
        try:
            return self.decode(obj.get()["Body"].read())
        except self.aws_s3.meta.client.exceptions.NoSuchKey:
            return {}


class GoogleCloudStorage(Storage):
    """Google Cloud Storage backend"""

    def __init__(self, bucket_id: str = None) -> None:
        storage = importlib.import_module("google.cloud.storage")
        exceptions = importlib.import_module("google.cloud.exceptions")
        auth_exceptions = importlib.import_module("google.auth.exceptions")

        log.debug("Using %s backend.", self.name)
        self.bucket_id = bucket_id or BUCKET_ID
        try:
            client = storage.Client()  # type: ignore
        except (auth_exceptions.DefaultCredentialsError, OSError):  # type: ignore
            # Local testing etc.
            client = storage.Client.create_anonymous_client()  # type: ignore
            client.project = "<none>"
        try:
            self.bucket = client.get_bucket(self.bucket_id)
        except exceptions.NotFound:  # type: ignore
            self.bucket = client.create_bucket(self.bucket_id)

    def _save(self, content: CurrencyDict, filename: str) -> None:
        blob = self.bucket.blob(filename)
        blob.upload_from_string(self.encode(content))

    def _load(self, filename: str) -> CurrencyDict:
        blob = self.bucket.get_blob(filename)
        if blob:
            return self.decode(blob.download_as_bytes())
        return {}


class LocalStorage(Storage):
    """Local storage backend."""

    def __init__(self, storage_dir: str) -> None:
        log.debug("Using %s backend.", self.name)
        self.storage_dir = Path(storage_dir or STORAGE_DIR)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _save(self, content: CurrencyDict, filename: str) -> None:
        with open(self.storage_dir.joinpath(filename), "wb") as file:
            file.write(self.encode(content))

    def _load(self, filename: str) -> CurrencyDict:
        try:
            with open(self.storage_dir.joinpath(filename), "rb") as file:
                return self.decode(file.read())
        except FileNotFoundError:
            return {}


def get_storage(storage_type: StorageType = None) -> Type[Storage]:
    """Returns a storage backend."""
    if storage_type is None:
        storage_type = StorageType(STORAGE_TYPE)

    cloud_storage = get_cloud_storage(storage_type)
    if cloud_storage:
        return cloud_storage

    if storage_type is StorageType.LOCAL:
        return LocalStorage
    if storage_type is StorageType.DISABLED:
        return StorageDisabled

    raise NotImplementedError(f"Not implemented: {storage_type!r}")


def get_cloud_storage(storage_type: StorageType = None) -> Optional[Type[Storage]]:
    """Cloud storages with storage buckets."""
    if storage_type is StorageType.AWS:
        return AmazonS3
    if storage_type is StorageType.GCP:
        return GoogleCloudStorage
    # Past the cloud storage options, fail if BUCKET_ID is set
    if BUCKET_ID:
        raise ValueError(
            f"[BUCKET_ID] set as {BUCKET_ID!r}, but [STORAGE_TYPE] is set as {STORAGE_TYPE!r}."
            " With a bucket [STORAGE_TYPE] needs to be set as [AWS|GCP]."
        )
    return None
