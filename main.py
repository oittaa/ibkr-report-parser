#!/usr/bin/env python3

from csv import reader
from datetime import datetime, timedelta, date
from flask import Flask, abort, render_template, request
from google.cloud import storage
from json import dumps, loads
from os import getenv
from re import match, sub
from urllib.error import HTTPError
from urllib.request import urlopen
from zlib import compress, decompress
import logging


TITLE = getenv("TITLE", "IBKR Report Parser")
BUCKET_ID = getenv("BUCKET_ID", None)
DEBUG = bool(getenv("DEBUG"))
DEFAULT_EXCHANGE_RATES_URL = (
    "https://www.suomenpankki.fi/WebForms/ReportViewerPage.aspx?report=/tilastot/valuuttakurssit/"
    "valuuttakurssit_short_xml_fi&output=csv"
)
EXCHANGE_RATES_URL = getenv("EXCHANGE_RATES_URL", DEFAULT_EXCHANGE_RATES_URL)

DATA_STR_SINGLE_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
DATA_STR_MULTI_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
MAXIMUM_BACKTRACK_DAYS = 7
RATES_FILE = "official_exchange_rates-{0}.json.gz"

app = Flask(__name__)
cache = {}


def get_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d, %H:%M:%S").date()
    except ValueError:
        try:
            return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").date()
        except ValueError:
            return datetime.strptime(date_str, "%Y-%m-%d").date()


def add_years(d, years):
    """Return a date that's `years` years after the date (or datetime)
    object `d`. Return the same calendar date (month and day) in the
    destination year, if it exists, otherwise use the previous day
    (thus changing February 29 to February 28).

    """
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d + (date(d.year + years, 3, 1) - date(d.year, 3, 1))


def date_without_time(date_str):
    return sub(r"([0-9-]+),? ([0-9:]+)", r"\1", date_str)


def float_cleanup(number_str):
    return float(sub(r"[,\s]+", "", number_str))


def download_official_rates(url):
    max_retries = 5
    rates = {}
    while True:
        if max_retries < 0:
            raise ValueError(
                "Maximum number of retries exceeded. Could not retrieve currency exchange rates."
            )
        try:
            response = urlopen(url)
            break
        except HTTPError as e:
            # Return code error (e.g. 404, 501, ...)
            app.logger.warning("HTTP Error while retrieving rates: %d", e.code)
            max_retries -= 1

    app.logger.info("Successfully downloaded the latest exchange rates.")
    for line in response:
        m = match(
            r'.*,(\d\d\d\d-\d\d-\d\d),EUR-([A-Z]+),"([\d\s]+),([\d]+)"',
            line.decode("utf-8"),
        )
        if m:
            # example: rates["2014-01-02"]["MXN"] = 17.9384
            n = sub(r"[\s]+", r"", m.group(3))
            rate = float("{0}.{1}".format(n, m.group(4)))
            d = m.group(1)
            date_rates = rates.get(d, {})
            date_rates[m.group(2)] = rate
            rates[d] = date_rates
    app.logger.info("Parsed exchange rates from the retrieved data.")
    return rates


def get_exchange_rates(url, cron_job=False):
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(1)).strftime("%Y-%m-%d")
    latest_rates_file = RATES_FILE.format(today)
    previous_rates_file = RATES_FILE.format(yesterday)
    if BUCKET_ID:
        client = storage.Client()
        bucket = client.get_bucket(BUCKET_ID)
        blob = bucket.get_blob(latest_rates_file)
        if not blob and not cron_job:
            # Try to use exchange rates from the previous day if not in a cron job.
            blob = bucket.get_blob(previous_rates_file)
        if blob:
            return loads(decompress(blob.download_as_bytes()).decode("utf-8"))
    rates = download_official_rates(url)
    if BUCKET_ID:
        blob = bucket.blob(latest_rates_file)
        blob.upload_from_string(compress(dumps(rates).encode("utf-8")))
    return rates


def eur_exchange_rate(currency, date_str, cache_key):
    if "EUR" == currency:
        return 1
    original_date = search_date = get_date(date_str)
    while original_date - search_date < timedelta(MAXIMUM_BACKTRACK_DAYS):
        date_rates = cache[cache_key].get(search_date.strftime("%Y-%m-%d"), {})
        rate = date_rates.get(currency)
        if rate is not None:
            return rate
        search_date -= timedelta(1)
    app.logger.error(
        "Currency %s not found near date %s - ended search at %s",
        currency,
        original_date,
        search_date,
    )
    abort(400)


def parse_trade(items, offset, rate):
    trade_data = {"total_selling_price": 0, "fee_per_share": 0}
    trade_data["symbol"] = items[5 + offset]
    # Sold stocks have a negative value in the "Quantity" column, items[8 + offset]
    trade_data["quantity"] = float_cleanup(items[8 + offset])
    if trade_data["quantity"] != 0:
        trade_data["fee_per_share"] = (
            float_cleanup(items[11 + offset]) / abs(trade_data["quantity"]) / rate
        )
    if trade_data["quantity"] < 0:
        trade_data["total_selling_price"] = float_cleanup(items[10 + offset]) / rate
        trade_data["sell_date"] = items[6 + offset]
        trade_data["sell_price"] = float_cleanup(items[9 + offset]) / rate
    else:
        trade_data["buy_date"] = items[6 + offset]
        trade_data["buy_price"] = float_cleanup(items[9 + offset]) / rate
    app.logger.debug(
        "Trade %s %s: %s - quantity: %s, price: %s, per share EUR: %f, fee: %s",
        items[3],
        items[4],
        items[5 + offset],
        items[8 + offset],
        items[10 + offset],
        float_cleanup(items[9 + offset]) / rate,
        items[11 + offset],
    )
    return trade_data


def parse_closed_lot(trade_data, items, offset, rate):
    if trade_data.get("symbol") != items[5 + offset]:
        app.logger.error(
            "Symbol mismatch! Trade: %s, ClosedLot: %s",
            trade_data.get("symbol"),
            items[5 + offset],
        )
        app.logger.debug(trade_data)
        app.logger.debug(items)
        abort(400)
    multiplier = 1
    if "Equity and Index Options" == items[3]:
        multiplier = 100
    lot_quantity = float_cleanup(items[8 + offset])
    if lot_quantity < 0:
        trade_data["sell_date"] = items[6 + offset]
        trade_data["sell_price"] = float_cleanup(items[9 + offset]) / rate
    else:
        trade_data["buy_date"] = items[6 + offset]
        trade_data["buy_price"] = float_cleanup(items[9 + offset]) / rate
    if not all(
        k in trade_data for k in ("sell_date", "sell_price", "buy_date", "buy_price")
    ):
        app.logger.error(
            "Invalid data, missing one or more of the following: 'sell_date','sell_price','buy_date','buy_price'"
        )
        app.logger.debug(trade_data)
        abort(400)
    realized = (
        trade_data["sell_price"] * multiplier
        - trade_data["buy_price"] * multiplier
        + trade_data["fee_per_share"]
    ) * abs(lot_quantity)
    total_sell_price = trade_data["sell_price"] * multiplier * abs(lot_quantity)
    deemed_cost = calculate_deemed_acquisition_cost(
        get_date(trade_data["buy_date"]),
        get_date(trade_data["sell_date"]),
        total_sell_price,
    )
    deemed_profit = total_sell_price - deemed_cost
    app.logger.debug(
        "ClosedLot %s %s: %s - quantity: %s, realized: %.2f, deemed profit: %.2f",
        items[3],
        items[4],
        items[5 + offset],
        items[8 + offset],
        realized,
        deemed_profit,
    )
    app.logger.info(
        "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, Selling price: %.2f, Gains/Losses: %.2f",
        trade_data["symbol"],
        abs(lot_quantity),
        date_without_time(trade_data["buy_date"]),
        date_without_time(trade_data["sell_date"]),
        total_sell_price,
        min(realized, deemed_profit),
    )
    return min(realized, deemed_profit), lot_quantity


def calculate_deemed_acquisition_cost(buy_date, sell_date, total_sell_price):
    """If you have owned the shares you sell for less than 10 years, the deemed
    acquisition cost is 20% of the selling price of the shares.
    If you have owned the shares you sell for at least 10 years, the deemed
    acquisition cost is 40% of the selling price of the shares.
    """
    coefficient = 0.2
    max_coefficient_before = add_years(sell_date, -10)
    if buy_date < max_coefficient_before:
        coefficient = 0.4
    return coefficient * total_sell_price


def check_offset(items, offset):
    if DATA_STR_SINGLE_ACCOUNT == items:
        offset = 0
    elif DATA_STR_MULTI_ACCOUNT == items:
        offset = 1
    return offset


def show_results(prices, gains, losses):
    if request.args.get("json") is not None:
        return {
            "prices": round(prices, 2),
            "gains": round(gains, 2),
            "losses": round(losses, 2),
        }
    return render_template(
        "result.html",
        title=TITLE,
        prices=prices,
        gains=gains,
        losses=losses,
    )


@app.route("/", methods=["GET"])
def main_get():
    return render_template("index.html", title=TITLE)


@app.route("/", methods=["POST"])
def main_post():
    app.logger.setLevel(logging.INFO)
    if app.debug:
        app.logger.setLevel(logging.DEBUG)
    prices, gains, losses, offset = 0.0, 0.0, 0.0, 0
    trade_data = {}
    cache_key = datetime.now().strftime("%Y-%m-%d")
    if cache_key not in cache:
        app.logger.info("Cache miss: %s", cache_key)
        cache[cache_key] = get_exchange_rates(EXCHANGE_RATES_URL)
    upload = request.files.get("file")
    lines = reader(upload.read().decode("utf-8").split("\n"))
    for items in lines:
        offset = check_offset(items, offset)
        if not (
            len(items) == 15 + offset
            and "Trades" == items[0]
            and "Data" == items[1]
            and items[2] in ("Trade", "ClosedLot")
            and items[3] in ("Stocks", "Equity and Index Options")
        ):
            continue
        rate = eur_exchange_rate(items[4], items[6 + offset], cache_key)
        if "Trade" == items[2]:
            trade_data = parse_trade(items, offset, rate)
            prices += trade_data["total_selling_price"]
        elif "ClosedLot" == items[2]:
            realized, lot_quantity = parse_closed_lot(trade_data, items, offset, rate)
            if realized > 0:
                gains += realized
            else:
                losses -= realized
            trade_data["quantity"] += lot_quantity
            if 0 == trade_data["quantity"]:
                app.logger.debug("Trade completed.")
                trade_data = {}

    return show_results(prices, gains, losses)


@app.route("/cron", methods=["GET"])
def cron():
    """Cron function that fetches the latest exchange rates if necessary."""
    if request.headers.get("X-Appengine-Cron") is None:
        abort(403)
    if BUCKET_ID:
        _ = get_exchange_rates(EXCHANGE_RATES_URL, cron_job=True)
    return "Done!"


if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.
    app.run(host="127.0.0.1", port=8080, debug=DEBUG)
