"""Euro foreign exchange rates from European Central Bank"""

import csv
import logging
import re
from codecs import iterdecode
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from typing import Iterable
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import BadZipFile, ZipFile

from ibkr_report.definitions import (
    DATE_FORMAT,
    EXCHANGE_RATES_URL,
    MAX_BACKTRACK_DAYS,
    MAX_HTTP_RETRIES,
    CurrencyDict,
    StorageType,
)
from ibkr_report.tools import get_date, is_number
from ibkr_report.storage import get_storage

log = logging.getLogger(__name__)


class ExchangeRates:
    """Euro foreign exchange rates"""

    rates: CurrencyDict

    def __init__(
        self, url: str = None, storage_type: StorageType = None, **kwargs
    ) -> None:
        """Tries to fetch a previously built exchange rate dictionary from a
        Storage backend. If that's not available, downloads the official
        exchange rates from European Central Bank and builds a new dictionary
        from it.
        """
        url = url or EXCHANGE_RATES_URL
        storage = get_storage(storage_type=storage_type)
        self.storage = storage(**kwargs)
        self.rates = self.storage.load()
        if not self.rates:
            self.download_official_rates(url)
            self.storage.save(content=self.rates)

    def add_to_exchange_rates(self, rates_file: Iterable[bytes]) -> None:
        """Builds the dictionary for the exchange rates from the downloaded CSV file
        and adds it to the dictionary.

        {"2015-01-20": {"USD": "1.1579", ...}, ...}
        """
        rates: CurrencyDict = {}
        currencies = []
        for items in csv.reader(iterdecode(rates_file, "utf-8")):
            if items[0] == "Date":
                # The first row should be "Date,USD,JPY,..."
                currencies = items[1:]
            if currencies and re.match(r"^\d\d\d\d-\d\d-\d\d$", items[0]):
                # And the following rows like "2015-01-20,1.1579,137.37,..."
                date_rates = {
                    cur: val
                    for cur, val in zip(currencies, items[1:])
                    if is_number(val)
                }
                if date_rates:
                    rates[items[0]] = date_rates
        log.debug("Adding currency data from %d rows.", len(rates))
        self.rates = {**self.rates, **rates}
        # TODO: Python3.9+ "self.rates |= rates"  # pylint: disable=fixme

    def download_official_rates(self, url: str) -> None:
        """Downloads the official currency exchange rates from European Central Bank
        and builds a new exchange rate dictionary from it.
        """
        retries = 0
        while True:
            if retries > MAX_HTTP_RETRIES:
                raise ValueError(
                    "Maximum number of retries exceeded. "
                    "Could not retrieve currency exchange rates."
                )
            try:
                with urlopen(url) as response:
                    bytes_io = BytesIO(response.read())
                break
            except HTTPError as err:
                # Return code error (e.g. 404, 501, ...)
                error_msg = "HTTP Error while retrieving rates: %d %s"
                log.warning(error_msg, err.code, err.reason)
                retries += 1
        log.debug("Successfully downloaded the latest exchange rates: %s", url)
        self.unzip_and_add(bytes_io)

    def unzip_and_add(self, bytes_io: BytesIO) -> None:
        """Unzips the data and passes it to `add_to_exchange_rates`."""
        try:
            with ZipFile(bytes_io) as rates_zip:
                for filename in rates_zip.namelist():
                    with rates_zip.open(filename) as rates_file:
                        self.add_to_exchange_rates(rates_file)
        except BadZipFile:
            bytes_io.seek(0)
            self.add_to_exchange_rates(bytes_io)
        log.debug("Parsed exchange rates from the retrieved data.")

    def get_rate(self, currency_from: str, currency_to: str, date_str: str) -> Decimal:
        """Exchange rate between two currencies on a given day."""
        if currency_from == currency_to:
            return Decimal(1)

        original_date = search_date = get_date(date_str)
        while original_date - search_date <= timedelta(MAX_BACKTRACK_DAYS):
            date_rates = self.rates.get(search_date.strftime(DATE_FORMAT), {})
            from_rate = "1" if currency_from == "EUR" else date_rates.get(currency_from)
            to_rate = "1" if currency_to == "EUR" else date_rates.get(currency_to)
            if from_rate is not None and to_rate is not None:
                return Decimal(to_rate) / Decimal(from_rate)
            search_date -= timedelta(1)
        raise ValueError(
            f"Currencies {currency_from} and {currency_to} not found near "
            f"date {original_date} - search ended before {search_date}"
        )
