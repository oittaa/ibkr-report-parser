#!/usr/bin/env python3

from datetime import datetime, timedelta
from flask import Flask, abort, render_template, request
from google.cloud import storage
import json
import logging
import os
import re
import urllib.error
import urllib.request
import zlib


EXCHANGE_RATES_URL = (
    "https://www.suomenpankki.fi/WebForms/ReportViewerPage.aspx?report=/tilastot/valuuttakurssit/"
    "valuuttakurssit_short_xml_fi&output=csv"
)
DATA_STR_SINGLE_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Quantity,"
    "T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Realized P/L %,MTM P/L,Code"
)
DATA_STR_MULTI_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Quantity,"
    "T. Price,C. Price,Proceeds,Comm/Fee,Basis,Realized P/L,MTM P/L,Code"
)
MAXIMUM_BACKTRACK_DAYS = 7
RATES_FILE = "exchange_rates-{0}.json.gz"

TITLE = os.getenv("TITLE", "IBKR Report Parser")
BUCKET_ID = os.getenv("BUCKET_ID", None)

app = Flask(__name__)
cache = {}


def get_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").date()


def download_official_rates(url):
    max_retries = 5
    rates = {}
    while True:
        if max_retries < 0:
            raise ValueError(
                "Maximum number of retries exceeded. Could not retrieve currency exchange rates."
            )
        try:
            response = urllib.request.urlopen(url)
            break
        except urllib.error.HTTPError as e:
            # Return code error (e.g. 404, 501, ...)
            app.logger.warning("HTTP Error while retrieving rates: %d", e.code)
            max_retries -= 1

    app.logger.info("Successfully downloaded the latest exchange rates.")
    for line in response:
        m = re.match(
            r'.*,(\d\d\d\d-\d\d-\d\d),EUR-([A-Z]+),"([\d]+),([\d]+)"',
            line.decode("utf-8"),
        )
        if m:
            # example: rates['MXN-2014-01-02'] = 17.9384
            rates["{0}-{1}".format(m.group(2), m.group(1))] = float(
                "{0}.{1}".format(m.group(3), m.group(4))
            )
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
            return json.loads(zlib.decompress(blob.download_as_bytes()).decode("utf-8"))
    rates = download_official_rates(url)
    if BUCKET_ID:
        blob = bucket.blob(latest_rates_file)
        blob.upload_from_string(zlib.compress(json.dumps(rates).encode("utf-8")))
    return rates


def eur_exchange_rate(currency, date_str, cache_key):
    original_date = date = get_date(date_str)
    while original_date - date < timedelta(MAXIMUM_BACKTRACK_DAYS):
        rate = cache[cache_key].get("{}-{}".format(currency, date.strftime("%Y-%m-%d")))
        if rate is not None:
            return rate
        date -= timedelta(1)
    app.logger.error(
        "Currency %s not found near date %s - ended search at %s",
        currency,
        original_date,
        date,
    )
    abort(400)


@app.route("/", methods=["GET"])
def main_get():
    return render_template("index.html", title=TITLE)


@app.route("/", methods=["POST"])
def main_post():
    prices, gains, losses = 0, 0, 0
    cache_key = datetime.now().strftime("%Y-%m-%d")
    if cache_key not in cache:
        app.logger.info("Cache miss: %s", cache_key)
        cache[cache_key] = get_exchange_rates(EXCHANGE_RATES_URL)
    offset = 0
    upload = request.files.get("file")
    lines = upload.read().decode("utf-8").split("\n")
    for line in lines:
        if line == DATA_STR_SINGLE_ACCOUNT:
            offset = 0
            continue
        elif line == DATA_STR_MULTI_ACCOUNT:
            offset = 1
            continue
        # remove comma from datetime
        line = re.sub(r'"([0-9-]+), ([0-9:]+)"', r"\1 \2", line)
        items = line.split(",")
        if (
            len(items) == 17
            and items[0] == "Trades"
            and items[1] == "Data"
            and items[2] == "Order"
            and (items[3] == "Stocks" or items[3] == "Equity and Index Options")
        ):
            if items[4] == "EUR":
                rate = 1
            else:
                rate = eur_exchange_rate(items[4], items[6 + offset], cache_key)
            # Sold stocks have a negative value in the "Quantity" column, items[7 + offset]
            if float(items[7 + offset]) < 0:
                prices += float(items[10 + offset]) / rate
            realized = float(items[13 + offset]) / rate
            if realized > 0:
                gains += realized
            else:
                losses += realized
            app.logger.debug(
                "%s %s: %s - quantity: %s, price: %s, realized: %s, realized EUR: %.2f",
                items[3],
                items[4],
                items[5 + offset],
                items[7 + offset],
                items[10 + offset],
                items[13 + offset],
                realized,
            )

    if request.args.get("json") is not None:
        return {
            "prices": round(prices, 2),
            "gains": round(gains, 2),
            "losses": round(abs(losses), 2),
        }

    return render_template(
        "result.html",
        title=TITLE,
        prices=round(prices, 2),
        gains=round(gains, 2),
        losses=round(abs(losses), 2),
    )


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
    app.run(host="127.0.0.1", port=8080, debug=True)
    app.logger.setLevel(logging.DEBUG)
