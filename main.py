#!/usr/bin/env python3
""" IBKR Report Parser

TThis program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
"""


import logging
from base64 import b64encode
from codecs import iterdecode
from csv import reader
from dataclasses import dataclass
from datetime import datetime, timedelta, date
from decimal import Decimal
from flask import Flask, abort, make_response, render_template, request
from google.cloud import exceptions, storage  # type: ignore
from hashlib import sha384
from io import BytesIO
from json import dumps, loads
from lzma import compress, decompress
from os import getenv, path
from re import match, sub
from typing import Dict, Iterable, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

TITLE = getenv("TITLE", "IBKR Report Parser")
BUCKET_ID = getenv("BUCKET_ID", None)
DEBUG = bool(getenv("DEBUG"))
_DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
EXCHANGE_RATES_URL = getenv("EXCHANGE_RATES_URL", _DEFAULT_URL)
LOGGING_LEVEL = getenv("LOGGING_LEVEL", "INFO")

MAX_BACKTRACK_DAYS = 7
MAX_HTTP_RETRIES = 5
SAVED_RATES_FILE = "official_ecb_exchange_rates-{0}.json.xz"
CurrencyDict = Dict[str, Dict[str, str]]

_SINGLE_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
_MULTI_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
_OFFSET_DICT = {tuple(_SINGLE_ACCOUNT): 0, tuple(_MULTI_ACCOUNT): 1}
_DATE = "%Y-%m-%d"
_TIME = " %H:%M:%S"
_DATE_STR_FORMATS = (_DATE + "," + _TIME, _DATE + _TIME, _DATE)

app = Flask(__name__)

_cache: Dict = {}
_MAXCACHE = 5


@dataclass
class SRI:
    css: str
    js: str


@dataclass
class TickerInfo:
    symbol: str
    date_str: str
    rate: Decimal
    price_per_share: Decimal
    quantity: Decimal


@dataclass
class TradeDetails:
    symbol: str
    quantity: Decimal
    buy_date: str
    sell_date: str
    price: Decimal
    realized: Decimal


class Trade:
    """Trade which might be related to several ClosedLot rows."""

    fee: Decimal = Decimal(0)
    closed_quantity: Decimal = Decimal(0)
    total_selling_price: Decimal = Decimal(0)
    offset: int = 0
    fields: TickerInfo

    def __init__(self, items: Tuple[str, ...], offset: int) -> None:
        """Initializes the Trade and calculates the total selling price from it."""
        self.offset = offset
        self.fields = self._ticker_info(items)
        self.fee = decimal_cleanup(items[11 + offset]) / self.fields.rate
        # Sold stocks have a negative value in the "Quantity" column, items[8 + offset]
        if self.fields.quantity < Decimal(0):
            self.total_selling_price = (
                decimal_cleanup(items[10 + offset]) / self.fields.rate
            )
        app.logger.debug(
            'Trade: "%s" "%s" %.2f',
            self.fields.date_str,
            self.fields.symbol,
            self.fields.quantity,
        )

    def _ticker_info(self, items: Tuple[str, ...]) -> TickerInfo:
        symbol = items[5 + self.offset]
        date_str = items[6 + self.offset]
        rate = eur_exchange_rate(currency=items[4], date_str=items[6 + self.offset])
        price_per_share = decimal_cleanup(items[9 + self.offset]) / rate
        quantity = decimal_cleanup(items[8 + self.offset])
        return TickerInfo(symbol, date_str, rate, price_per_share, quantity)

    def details_from_closed_lot(self, items: Tuple[str, ...]) -> TradeDetails:
        """Most importantly calculates the realized gains or losses from the ClosedLot
        related to the Trade.
        """
        error_msg = ""
        fields = self._ticker_info(items)
        if self.fields.symbol != fields.symbol:
            error_msg = "Symbol mismatch! Date: {}, Trade: {}, ClosedLot: {}".format(
                fields.date_str, self.fields.symbol, fields.symbol
            )
        elif abs(self.fields.quantity + fields.quantity) > abs(self.fields.quantity):
            error_msg = 'Invalid data. "Trade" and "ClosedLot" quantities do not match. Date: {}, Symbol: {}'.format(
                fields.date_str, fields.symbol
            )
        if error_msg:
            app.logger.error(error_msg)
            app.logger.debug(items)
            abort(400, description=error_msg)

        sell_date = date_without_time(self.fields.date_str)
        sell_price = self.fields.price_per_share
        buy_date = date_without_time(fields.date_str)
        buy_price = fields.price_per_share

        # Swap if closing a short position
        if fields.quantity < Decimal(0):
            sell_date, buy_date = buy_date, sell_date
            sell_price, buy_price = buy_price, sell_price

        # One option represents 100 shares of the underlying stock
        multiplier = 100 if items[3] == "Equity and Index Options" else 1

        realized = (
            abs(fields.quantity) * (sell_price - buy_price) * multiplier
            - fields.quantity * self.fee / self.fields.quantity
        )
        total_sell_price = abs(fields.quantity) * sell_price * multiplier
        realized = min(
            realized,
            deemed_profit(
                buy_date=buy_date,
                sell_date=sell_date,
                total_sell_price=total_sell_price,
            ),
        )
        app.logger.info(
            "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, Selling price: %.2f, Gains/Losses: %.2f",
            fields.symbol,
            abs(fields.quantity),
            buy_date,
            sell_date,
            total_sell_price,
            realized,
        )
        self.closed_quantity += fields.quantity
        if self.closed_quantity + self.fields.quantity == Decimal(0):
            app.logger.debug("All lots closed")
        return TradeDetails(
            symbol=fields.symbol,
            quantity=abs(fields.quantity),
            buy_date=buy_date,
            sell_date=sell_date,
            price=total_sell_price,
            realized=realized,
        )


class IBKRReport:
    """Total selling prices, total capital gains, and total capital losses
    calculated from the CSV files.
    """

    prices: Decimal = Decimal(0)
    gains: Decimal = Decimal(0)
    losses: Decimal = Decimal(0)
    details: List[TradeDetails]
    _offset: int = 0
    _trade: Optional[Trade] = None

    def __init__(self, file: Iterable[bytes] = None) -> None:
        self.details = []
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file."""
        try:
            for items_list in reader(iterdecode(file, "utf-8")):
                items = tuple(items_list)
                offset = _OFFSET_DICT.get(items)
                if offset is not None:
                    self._offset = offset
                    self._trade = None
                    continue
                if self._is_stock_or_options_trade(items):
                    self._handle_trade(items)
        except UnicodeDecodeError:
            abort(400, description="Input data not in UTF-8 text format.")

    def _is_stock_or_options_trade(self, items: Tuple[str, ...]) -> bool:
        """Checks whether the current row is part of a trade or not."""
        if (
            len(items) == 15 + self._offset
            and items[0] == "Trades"
            and items[1] == "Data"
            and items[2] in ("Trade", "ClosedLot")
            and items[3] in ("Stocks", "Equity and Index Options")
        ):
            return True
        return False

    def _handle_trade(self, items: Tuple[str, ...]) -> None:
        """Parses prices, gains, and losses from trades."""
        if items[2] == "Trade":
            self._trade = Trade(items, self._offset)
            self.prices += self._trade.total_selling_price
        elif items[2] == "ClosedLot":
            if not self._trade:
                abort(400, description="Tried to close a lot without trades.")
            details = self._trade.details_from_closed_lot(items)
            if details.realized > 0:
                self.gains += details.realized
            else:
                self.losses -= details.realized
            self.details.append(details)


def get_date(date_str: str) -> date:
    """Converts a string formatted date to a date object."""
    for date_format in _DATE_STR_FORMATS:
        try:
            return datetime.strptime(date_str, date_format).date()
        except ValueError:
            pass
    error_msg = "Invalid date '{}'".format(date_str)
    app.logger.error(error_msg)
    abort(400, description=error_msg)


def add_years(d: date, years: int) -> date:
    """Return a date that's `years` years after the date (or datetime)
    object `d`. Return the same calendar date (month and day) in the
    destination year, if it exists, otherwise use the previous day
    (thus changing February 29 to February 28).
    """
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d + (date(d.year + years, 3, 1) - date(d.year, 3, 1))


def date_without_time(date_str: str) -> str:
    return sub(r"(\d\d\d\d-\d\d-\d\d),? ([0-9:]+)", r"\1", date_str)


def decimal_cleanup(number_str: str) -> Decimal:
    return Decimal(sub(r"[,\s]+", "", number_str))


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def build_exchange_rate_dictionary(rates_file: Iterable[bytes]) -> CurrencyDict:
    """Builds the dictionary for the exchange rates from the downloaded CSV file.
    {"2015-01-20": {"USD": "1.1579", ...}, ...}
    """
    rates = {}
    currencies = None
    for items in reader(iterdecode(rates_file, "utf-8")):
        if items[0] == "Date":
            currencies = items
        elif currencies and match(r"^\d\d\d\d-\d\d-\d\d$", items[0]):
            date_rates = {}
            for key, val in enumerate(items):
                if key == 0 or not currencies[key] or not is_number(val):
                    continue
                date_rates[currencies[key]] = val
            if date_rates:
                rates[items[0]] = date_rates
    return rates


def download_official_rates_ecb(url: str) -> CurrencyDict:
    """Downloads the official currency exchange rates from European Central Bank
    and builds a new exchange rate dictionary from it.
    """
    retries = 0
    rates: CurrencyDict = {}
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
            app.logger.warning("HTTP Error while retrieving rates: %d", e.code)
            retries += 1
    app.logger.debug("Successfully downloaded the latest exchange rates: %s", url)
    with ZipFile(BytesIO(response.read())) as rates_zip:
        for filename in rates_zip.namelist():
            with rates_zip.open(filename) as rates_file:
                temp_rates = build_exchange_rate_dictionary(rates_file)
                rates = {**rates, **temp_rates}
                # TODO Python3.9+ "rates |= temp_rates"
    app.logger.debug("Parsed exchange rates from the retrieved data.")
    return rates


def get_exchange_rates(cron_job: bool = False) -> CurrencyDict:
    """Tries to fetch a previously built exchange rate dictionary from a Google Cloud
    Storage bucket. If that's not available, downloads the official exchange rates from
    European Central Bank and builds a new dictionary from it.
    """
    if BUCKET_ID:
        if getenv("STORAGE_EMULATOR_HOST"):
            client = storage.Client.create_anonymous_client()
            client.project = "<none>"
        else:
            client = storage.Client()
        try:
            bucket = client.get_bucket(BUCKET_ID)
        except exceptions.NotFound:
            bucket = client.create_bucket(BUCKET_ID)
        today = datetime.now().strftime(_DATE)
        latest_rates_file = SAVED_RATES_FILE.format(today)
        blob = bucket.get_blob(latest_rates_file)
        if not blob and not cron_job:
            # Try to use exchange rates from the previous day if not in a cron job.
            yesterday = (datetime.now() - timedelta(1)).strftime(_DATE)
            previous_rates_file = SAVED_RATES_FILE.format(yesterday)
            blob = bucket.get_blob(previous_rates_file)
        if blob:
            return loads(decompress(blob.download_as_bytes()).decode("utf-8"))
    rates = download_official_rates_ecb(EXCHANGE_RATES_URL)
    if BUCKET_ID:
        blob = bucket.blob(latest_rates_file)
        blob.upload_from_string(compress(dumps(rates).encode("utf-8")))
    return rates


def eur_exchange_rate(currency: str, date_str: str) -> Decimal:
    """Currency's exchange rate on a given day."""
    if currency == "EUR":
        return Decimal(1)
    cache_key = datetime.now().strftime(_DATE)
    if cache_key not in _cache:
        app.logger.debug("Cache miss: %s", cache_key)
        if len(_cache) >= _MAXCACHE:
            try:
                del _cache[next(iter(_cache))]
            except (StopIteration, RuntimeError, KeyError):
                pass
        _cache[cache_key] = get_exchange_rates()
    original_date = search_date = get_date(date_str)
    while original_date - search_date < timedelta(MAX_BACKTRACK_DAYS):
        date_rates = _cache[cache_key].get(search_date.strftime(_DATE), {})
        rate = date_rates.get(currency)
        if rate is not None:
            return Decimal(rate)
        search_date -= timedelta(1)
    error_msg = "Currency {} not found near date {} - ended search at {}".format(
        currency,
        original_date,
        search_date,
    )
    app.logger.error(error_msg)
    abort(400, description=error_msg)


def deemed_profit(buy_date: str, sell_date: str, total_sell_price: Decimal) -> Decimal:
    """If you have owned the shares you sell for less than 10 years, the deemed
    acquisition cost is 20% of the selling price of the shares.
    If you have owned the shares you sell for at least 10 years, the deemed
    acquisition cost is 40% of the selling price of the shares.
    """
    multiplier = Decimal(0.8)
    if get_date(buy_date) <= add_years(get_date(sell_date), -10):
        multiplier = Decimal(0.6)
    return multiplier * total_sell_price


def get_sri() -> SRI:
    """Calculate Subresource Integrity for CSS and Javascript files."""
    try:
        sri = _cache["sri"]
    except KeyError:
        sri = SRI(
            css=calculate_sri_on_file(
                path.join(app.root_path, "static", "css", "main.css")
            ),
            js=calculate_sri_on_file(
                path.join(app.root_path, "static", "js", "main.js")
            ),
        )
        _cache["sri"] = sri
    return sri


def calculate_sri_on_file(filename: str) -> str:
    """Calculate Subresource Integrity string."""
    hash_digest = hash_sum(filename, sha384()).digest()
    hash_base64 = b64encode(hash_digest).decode()
    return "sha384-{}".format(hash_base64)


def hash_sum(filename, hash_func):
    """Compute message digest from a file."""
    byte_array = bytearray(128 * 1024)
    memory_view = memoryview(byte_array)
    with open(filename, "rb", buffering=0) as file:
        for block in iter(lambda: file.readinto(memory_view), 0):
            hash_func.update(memory_view[:block])
    return hash_func


def show_results(report: IBKRReport, json_format: bool = False):
    if json_format:
        return {
            "prices": float(round(report.prices, 2)),
            "gains": float(round(report.gains, 2)),
            "losses": float(round(report.losses, 2)),
            "details": report.details,
        }
    return render_template(
        "result.html",
        title=TITLE,
        prices=report.prices,
        gains=report.gains,
        losses=report.losses,
        details=report.details,
        sri=get_sri(),
    )


@app.errorhandler(400)
def bad_request(e):
    if request.args.get("json") is not None:
        return {"error": str(e)}, 400
    return (
        render_template(
            "error.html",
            title=TITLE,
            message=str(e),
            sri=get_sri(),
        ),
        400,
    )


@app.route("/", methods=["GET"])
def main_get():
    resp = make_response(render_template("index.html", title=TITLE, sri=get_sri()))
    resp.cache_control.max_age = 600
    return resp


@app.route("/", methods=["POST"])
def main_post():
    if app.debug:
        app.logger.setLevel(logging.DEBUG)
    elif LOGGING_LEVEL.upper() in logging._nameToLevel.keys():
        app.logger.setLevel(logging._nameToLevel[LOGGING_LEVEL.upper()])
    else:
        app.logger.setLevel(logging.WARNING)
    report = IBKRReport(request.files.get("file"))
    json_format = True if request.args.get("json") is not None else False
    return show_results(report=report, json_format=json_format)


@app.route("/cron", methods=["GET"])
def cron():
    """Cron function that fetches the latest exchange rates if necessary."""
    if request.headers.get("X-Appengine-Cron") is None:
        abort(403)
    if BUCKET_ID:
        _ = get_exchange_rates(cron_job=True)
    return "Done!"


if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.
    app.run(host="127.0.0.1", port=8080, debug=DEBUG)
