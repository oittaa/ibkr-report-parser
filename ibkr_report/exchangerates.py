"""Euro foreign exchange rates from European Central Bank"""

from __future__ import annotations

import csv
import logging
from codecs import iterdecode
from datetime import date, timedelta
from decimal import Decimal
from io import BytesIO
from typing import Dict, Iterable, Optional, Tuple, Union
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
from ibkr_report.storage import get_storage
from ibkr_report.tools import get_date

log = logging.getLogger(__name__)

# ECB marks missing observations as N/A; empty cells appear too.
_MISSING_RATE = frozenset({"", "N/A", "n/a"})

# Process-level cache of fully parsed rate tables. Keyed by source URL and the
# calendar day the table was loaded so tests (and multi-request web workers)
# do not re-parse the large ECB zip after tools.Cache.clear() or with storage
# disabled. Invalidates automatically when the local date changes.
# Values are treated as immutable; instances share the mapping until they mutate.
_ParsedRatesKey = Tuple[str, str]  # (url, YYYY-MM-DD)
_parsed_rates_cache: Dict[_ParsedRatesKey, CurrencyDict] = {}


def clear_rate_parse_cache() -> None:
    """Drop in-process parsed rate tables (for tests that need a cold load)."""
    _parsed_rates_cache.clear()


def _today_key() -> str:
    return date.today().strftime(DATE_FORMAT)


def _copy_rates(rates: CurrencyDict) -> CurrencyDict:
    """Shallow-copy date -> currency map so callers can mutate safely."""
    return {day: dict(day_rates) for day, day_rates in rates.items()}


def _cache_get_parsed_rates(url: str) -> Optional[CurrencyDict]:
    """Return a shared (immutable) rate table, or None."""
    return _parsed_rates_cache.get((url, _today_key()))


def _cache_set_parsed_rates(url: str, rates: CurrencyDict) -> None:
    # Drop entries from other days so the cache cannot grow without bound.
    today = _today_key()
    stale = [key for key in _parsed_rates_cache if key[1] != today]
    for key in stale:
        del _parsed_rates_cache[key]
    # Store a copy so later mutation of the caller's dict cannot corrupt the cache.
    _parsed_rates_cache[(url, today)] = _copy_rates(rates)


def _is_rate_value(val: str) -> bool:
    """True if `val` looks like a numeric FX rate (avoids try/except per cell)."""
    if not val or val in _MISSING_RATE:
        return False
    # Rates are non-negative decimals like "1.1579" or "137.37".
    if val[0] == "-":
        return False
    saw_digit = False
    saw_dot = False
    for ch in val:
        if ch.isdigit():
            saw_digit = True
        elif ch == "." and not saw_dot:
            saw_dot = True
        else:
            return False
    return saw_digit


class ExchangeRates:
    """Euro foreign exchange rates"""

    rates: CurrencyDict
    _rates_owned: bool

    def __init__(
        self,
        url: Optional[str] = None,
        storage_type: Optional[StorageType] = None,
        **kwargs,
    ) -> None:
        """Tries to fetch a previously built exchange rate dictionary from a
        Storage backend. If that's not available, downloads the official
        exchange rates from European Central Bank and builds a new dictionary
        from it.
        """
        url = url or EXCHANGE_RATES_URL
        storage = get_storage(storage_type=storage_type)
        self.storage = storage(**kwargs)

        # Prefer the process-level table (shared, no deep-copy) over storage/tools.Cache
        # which would re-copy the large ECB map on every Report().
        cached = _cache_get_parsed_rates(url)
        if cached is not None:
            log.debug("Using in-process exchange rate cache for %s", url)
            self.rates = cached
            self._rates_owned = False
            return

        self.rates = self.storage.load()
        if self.rates:
            self._rates_owned = True
            _cache_set_parsed_rates(url, self.rates)
            return

        self.rates = {}
        self._rates_owned = True
        self.download_official_rates(url)
        self.storage.save(content=self.rates)
        _cache_set_parsed_rates(url, self.rates)

    def _ensure_owned_rates(self) -> None:
        if not self._rates_owned:
            self.rates = _copy_rates(self.rates)
            self._rates_owned = True

    def add_to_exchange_rates(self, rates_file: Iterable[bytes]) -> None:
        """Builds the dictionary for the exchange rates from the downloaded CSV file
        and adds it to the dictionary.

        {"2015-01-20": {"USD": "1.1579", ...}, ...}
        """
        self._ensure_owned_rates()
        rates: CurrencyDict = {}
        currencies: list[str] = []
        for items in csv.reader(iterdecode(rates_file, "utf-8")):
            if not items:
                continue
            if items[0] == "Date":
                # The first row should be "Date,USD,JPY,..."
                currencies = items[1:]
                continue
            # Data rows: "2015-01-20,1.1579,137.37,..."
            if not currencies or len(items[0]) != 10 or items[0][4] != "-":
                continue
            date_rates = {
                cur: val
                for cur, val in zip(currencies, items[1:])
                if _is_rate_value(val)
            }
            if date_rates:
                rates[items[0]] = date_rates
        log.debug("Adding currency data from %d rows.", len(rates))
        self.rates |= rates

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

    def get_rate(
        self,
        currency_from: str,
        currency_to: str,
        on: Union[date, str],
    ) -> Decimal:
        """Exchange rate between two currencies on a given day.

        ``on`` may be a ``date`` or an IBKR/ISO date string (parsed once).
        """
        if currency_from == currency_to:
            return Decimal(1)

        original_date = search_date = on if isinstance(on, date) else get_date(on)
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
