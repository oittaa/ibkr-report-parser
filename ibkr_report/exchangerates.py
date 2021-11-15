import csv
import json
import logging
import os
import re
from codecs import iterdecode
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO
from lzma import compress, decompress
from typing import Iterable
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

from google.cloud import exceptions, storage  # type: ignore

from ibkr_report.definitions import (
    _DATE,
    BUCKET_ID,
    EXCHANGE_RATES_URL,
    MAX_BACKTRACK_DAYS,
    MAX_HTTP_RETRIES,
    SAVED_RATES_FILE,
    CurrencyDict,
)
from ibkr_report.tools import get_date, is_number


log = logging.getLogger(__name__)


class ExchangeRates:
    """Euro foreign exchange rates"""

    rates: CurrencyDict = {}

    def __init__(self, url: str = None, cron_job: bool = False) -> None:
        """Tries to fetch a previously built exchange rate dictionary from a Google Cloud
        Storage bucket. If that's not available, downloads the official exchange rates from
        European Central Bank and builds a new dictionary from it.
        """
        if url is None:
            url = EXCHANGE_RATES_URL
        if BUCKET_ID:
            today = datetime.now().strftime(_DATE)
            self.latest_rates_file = SAVED_RATES_FILE.format(today)
            self._init_storage_client()
            self._download_rates_from_bucket(cron_job)
        if not self.rates:
            self.download_official_rates(url)
            if BUCKET_ID:
                self._upload_rates_to_bucket()

    def add_to_exchange_rate_dictionary(self, rates_file: Iterable[bytes]) -> None:
        """Builds the dictionary for the exchange rates from the downloaded CSV file
        and adds it to the dictionary.

        {"2015-01-20": {"USD": "1.1579", ...}, ...}
        """
        rates = {}
        currencies = None
        for items in csv.reader(iterdecode(rates_file, "utf-8")):
            if items[0] == "Date":
                # The first row should be "Date,USD,JPY,..."
                currencies = items
            elif currencies and re.match(r"^\d\d\d\d-\d\d-\d\d$", items[0]):
                # And the following rows like "2015-01-20,1.1579,137.37,..."
                date_rates = {}
                for key, val in enumerate(items):
                    if key == 0 or not currencies[key] or not is_number(val):
                        continue
                    date_rates[currencies[key]] = val
                if date_rates:
                    rates[items[0]] = date_rates

        self.rates = {**self.rates, **rates}
        # TODO Python3.9+ "self.rates |= rates"

    def download_official_rates(self, url: str) -> None:
        """Downloads the official currency exchange rates from European Central Bank
        and builds a new exchange rate dictionary from it.
        """
        retries = 0
        while True:
            if retries > MAX_HTTP_RETRIES:
                raise ValueError(
                    "Maximum number of retries exceeded. Could not retrieve currency exchange rates."
                )
            try:
                response = urlopen(url)
                break
            except HTTPError as e:
                # Return code error (e.g. 404, 501, ...)
                error_msg = "HTTP Error while retrieving rates: %d %s"
                log.warning(error_msg, e.code, e.reason)
                retries += 1
        log.debug("Successfully downloaded the latest exchange rates: %s", url)
        with ZipFile(BytesIO(response.read())) as rates_zip:
            for filename in rates_zip.namelist():
                with rates_zip.open(filename) as rates_file:
                    self.add_to_exchange_rate_dictionary(rates_file)
        log.debug("Parsed exchange rates from the retrieved data.")

    def eur_exchange_rate(self, currency: str, date_str: str) -> Decimal:
        """Currency's exchange rate on a given day."""
        if currency == "EUR":
            return Decimal(1)

        original_date = search_date = get_date(date_str)
        while original_date - search_date < timedelta(MAX_BACKTRACK_DAYS):
            date_rates = self.rates.get(search_date.strftime(_DATE), {})
            rate = date_rates.get(currency)
            if rate is not None:
                return Decimal(rate)
            search_date -= timedelta(1)
        error_msg = "Currency {} not found near date {} - ended search at {}"
        raise ValueError(error_msg.format(currency, original_date, search_date))

    def _init_storage_client(self) -> None:
        if os.getenv("STORAGE_EMULATOR_HOST"):
            client = storage.Client.create_anonymous_client()
            client.project = "<none>"
        else:
            client = storage.Client()
        self.client = client
        try:
            self.bucket = self.client.get_bucket(BUCKET_ID)
        except exceptions.NotFound:
            self.bucket = self.client.create_bucket(BUCKET_ID)

    def _upload_rates_to_bucket(self) -> None:
        blob = self.bucket.blob(self.latest_rates_file)
        blob.upload_from_string(self.encode(self.rates))

    def _download_rates_from_bucket(self, cron_job: bool = False) -> None:
        blob = self.bucket.get_blob(self.latest_rates_file)
        if not blob and not cron_job:
            # Try to use exchange rates from the previous day if not in a cron job.
            yesterday = (datetime.now() - timedelta(1)).strftime(_DATE)
            previous_rates_file = SAVED_RATES_FILE.format(yesterday)
            blob = self.bucket.get_blob(previous_rates_file)
        if blob:
            self.rates = self.decode(blob.download_as_bytes())

    @staticmethod
    def encode(data: CurrencyDict) -> bytes:
        return compress(json.dumps(data).encode("utf-8"))

    @staticmethod
    def decode(data: bytes) -> CurrencyDict:
        return json.loads(decompress(data).decode("utf-8"))
