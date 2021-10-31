#!/usr/bin/env python3

import logging
from codecs import iterdecode
from csv import reader
from dataclasses import InitVar, dataclass
from datetime import datetime, timedelta, date
from decimal import Decimal
from flask import Flask, abort, render_template, request
from google.cloud import exceptions, storage  # type: ignore
from io import BytesIO
from json import dumps, loads
from lzma import compress, decompress
from os import getenv
from re import match, sub
from typing import Dict, Iterable, List, Tuple, TypedDict
from urllib.error import HTTPError
from urllib.request import urlopen
from zipfile import ZipFile

TITLE = getenv("TITLE", "IBKR Report Parser")
BUCKET_ID = getenv("BUCKET_ID", None)
DEBUG = bool(getenv("DEBUG"))
_DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
EXCHANGE_RATES_URL = getenv("EXCHANGE_RATES_URL", _DEFAULT_URL)
LOGGING_LEVEL = getenv("LOGGING_LEVEL", "INFO")
_SINGLE_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
_MULTI_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
OFFSET_DICT = {tuple(_SINGLE_ACCOUNT): 0, tuple(_MULTI_ACCOUNT): 1}
_DATE = "%Y-%m-%d"
DATE_STR_FORMATS = (_DATE + ", %H:%M:%S", _DATE + " %H:%M:%S", _DATE)
MAX_BACKTRACK_DAYS = 7
MAX_HTTP_RETRIES = 5
SAVED_RATES_FILE = "official_ecb_exchange_rates-{0}.json.xz"
CurrencyDict = Dict[str, Dict[str, str]]

app = Flask(__name__)

_cache: Dict[str, CurrencyDict] = {}
_MAXCACHE = 5


class TradeData(TypedDict, total=False):
    fee: Decimal
    quantity: Decimal
    symbol: str
    total_selling_price: Decimal
    sell_date: str
    sell_price: Decimal
    buy_date: str
    buy_price: Decimal


@dataclass
class IBKRTrades:
    lines: InitVar[Iterable[List[str]]] = None
    prices: Decimal = Decimal(0)
    gains: Decimal = Decimal(0)
    losses: Decimal = Decimal(0)

    def __post_init__(self, lines: Iterable) -> None:
        if lines is None:
            return
        self._offset = 0
        self._trade_data = TradeData()
        try:
            for items in lines:
                items = tuple(items)
                self._offset = OFFSET_DICT.get(items, self._offset)
                if not (
                    len(items) == 15 + self._offset
                    and items[0] == "Trades"
                    and items[1] == "Data"
                    and items[2] in ("Trade", "ClosedLot")
                    and items[3] in ("Stocks", "Equity and Index Options")
                ):
                    continue
                self._rate = eur_exchange_rate(items[4], items[6 + self._offset])
                if items[2] == "Trade":
                    self.parse_trade(items)
                    self.prices += self._trade_data["total_selling_price"]
                    self._closed_quantity = Decimal(0)
                elif items[2] == "ClosedLot":
                    realized = self.realized_from_closed_lot(items)
                    if realized > 0:
                        self.gains += realized
                    else:
                        self.losses -= realized
        except UnicodeDecodeError:
            abort(400, description="Input data not in UTF-8 text format.")

    def parse_trade(self, items: Tuple[str, ...]) -> None:
        trade_data = TradeData(
            fee=decimal_cleanup(items[11 + self._offset]) / self._rate,
            quantity=decimal_cleanup(items[8 + self._offset]),
            symbol=items[5 + self._offset],
            total_selling_price=Decimal(0),
        )
        date_str = items[6 + self._offset]
        price_per_share = decimal_cleanup(items[9 + self._offset]) / self._rate
        # Sold stocks have a negative value in the "Quantity" column, items[8 + offset]
        if trade_data["quantity"] < Decimal(0):
            trade_data["total_selling_price"] = (
                decimal_cleanup(items[10 + self._offset]) / self._rate
            )
            trade_data["sell_date"] = date_str
            trade_data["sell_price"] = price_per_share
        else:
            trade_data["buy_date"] = date_str
            trade_data["buy_price"] = price_per_share
        app.logger.debug(
            "Trade %s %s: %s - quantity: %s, price: %s, per share EUR: %f, fee: %s",
            items[3],
            items[4],
            items[5 + self._offset],
            items[8 + self._offset],
            items[10 + self._offset],
            price_per_share,
            items[11 + self._offset],
        )
        self._trade_data = trade_data

    def realized_from_closed_lot(self, items: Tuple[str, ...]) -> Decimal:
        if self._trade_data.get("symbol") != items[5 + self._offset]:
            error_msg = "Symbol mismatch! Trade: {}, ClosedLot: {}".format(
                self._trade_data.get("symbol"), items[5 + self._offset]
            )
            app.logger.error(error_msg)
            app.logger.debug(self._trade_data)
            app.logger.debug(items)
            abort(400, description=error_msg)
        date_str = items[6 + self._offset]
        price_per_share = decimal_cleanup(items[9 + self._offset]) / self._rate
        lot_quantity = decimal_cleanup(items[8 + self._offset])
        if lot_quantity < 0:
            self._trade_data["sell_date"] = date_str
            self._trade_data["sell_price"] = price_per_share
        else:
            self._trade_data["buy_date"] = date_str
            self._trade_data["buy_price"] = price_per_share
        for key in ("sell_date", "buy_date"):
            if not self._trade_data.get(key):
                error_msg = "Invalid data, missing '{}'".format(key)
                app.logger.error(error_msg)
                app.logger.debug(self._trade_data)
                abort(400, description=error_msg)
        multiplier = 100 if items[3] == "Equity and Index Options" else 1
        realized = abs(lot_quantity) * (
            (
                (self._trade_data["sell_price"] - self._trade_data["buy_price"])
                * multiplier
            )
            + self._trade_data["fee"] / abs(self._trade_data["quantity"])
        )
        total_sell_price = (
            self._trade_data["sell_price"] * multiplier * abs(lot_quantity)
        )
        deemed = deemed_profit(
            self._trade_data["buy_date"],
            self._trade_data["sell_date"],
            total_sell_price,
        )
        app.logger.debug(
            "ClosedLot %s %s: %s - quantity: %s, realized: %.2f, deemed profit: %.2f",
            items[3],
            items[4],
            items[5 + self._offset],
            items[8 + self._offset],
            realized,
            deemed,
        )
        app.logger.info(
            "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, Selling price: %.2f, Gains/Losses: %.2f",
            self._trade_data["symbol"],
            abs(lot_quantity),
            date_without_time(self._trade_data["buy_date"]),
            date_without_time(self._trade_data["sell_date"]),
            total_sell_price,
            min(realized, deemed),
        )
        self._closed_quantity += lot_quantity
        if self._closed_quantity + self._trade_data["quantity"] == Decimal(0):
            app.logger.debug("Trade closed")
            self._trade_data = TradeData()
        return min(realized, deemed)


def get_date(date_str: str) -> date:
    for date_format in DATE_STR_FORMATS:
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


def extract_exchange_rates(rates_file: Iterable[bytes]) -> CurrencyDict:
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
                temp_rates = extract_exchange_rates(rates_file)
                rates = {**rates, **temp_rates}
                # TODO Python3.9+ "rates |= temp_rates"
    app.logger.debug("Parsed exchange rates from the retrieved data.")
    return rates


def get_exchange_rates(cron_job: bool = False) -> CurrencyDict:
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


def show_results(trades: IBKRTrades):
    if request.args.get("json") is not None:
        return {
            "prices": float(round(trades.prices, 2)),
            "gains": float(round(trades.gains, 2)),
            "losses": float(round(trades.losses, 2)),
        }
    return render_template(
        "result.html",
        title=TITLE,
        prices=trades.prices,
        gains=trades.gains,
        losses=trades.losses,
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
        ),
        400,
    )


@app.route("/", methods=["GET"])
def main_get():
    return render_template("index.html", title=TITLE)


@app.route("/", methods=["POST"])
def main_post():
    if app.debug:
        app.logger.setLevel(logging.DEBUG)
    elif LOGGING_LEVEL.upper() in logging._nameToLevel.keys():
        app.logger.setLevel(logging._nameToLevel[LOGGING_LEVEL.upper()])
    else:
        app.logger.setLevel(logging.WARNING)
    upload = request.files.get("file")
    trades = IBKRTrades(reader(iterdecode(upload, "utf-8")))
    return show_results(trades)


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
