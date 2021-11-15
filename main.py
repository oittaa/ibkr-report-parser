#!/usr/bin/env python3
""" IBKR Report Parser

This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <https://www.gnu.org/licenses/>.
"""


import logging
import os

from flask import Flask, abort, make_response, render_template, request

from ibkr_report.definitions import BUCKET_ID
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.report import Report
from ibkr_report.tools import get_sri

TITLE = os.getenv("TITLE", "IBKR Report Parser")
DEBUG = bool(os.getenv("DEBUG"))
_DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
EXCHANGE_RATES_URL = os.getenv("EXCHANGE_RATES_URL", _DEFAULT_URL)
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO")


app = Flask(__name__)
_SRI = get_sri(
    {
        "main.css": os.path.join(app.root_path, "static", "css", "main.css"),
        "main.js": os.path.join(app.root_path, "static", "js", "main.js"),
    }
)


def set_logging() -> None:
    if LOGGING_LEVEL.upper() in logging._nameToLevel.keys():
        app.logger.setLevel(logging._nameToLevel[LOGGING_LEVEL.upper()])
    else:
        app.logger.setLevel(logging.WARNING)


def show_results(report: Report, json_format: bool = False):
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
        sri=_SRI,
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
            sri=_SRI,
        ),
        400,
    )


@app.route("/", methods=["GET"])
def main_get():
    resp = make_response(render_template("index.html", title=TITLE, sri=_SRI))
    resp.cache_control.max_age = 600
    return resp


@app.route("/", methods=["POST"])
def main_post():
    if not app.debug:
        set_logging()
    app.logger.debug("Logging level: {}".format(logging._levelToName[app.logger.level]))
    try:
        report = Report(request.files.get("file"))
    except ValueError as err:
        abort(400, description=err)
    json_format = True if request.args.get("json") is not None else False
    return show_results(report=report, json_format=json_format)


@app.route("/cron", methods=["GET"])
def cron():
    """Cron function that fetches the latest exchange rates if necessary."""
    if request.headers.get("X-Appengine-Cron") is None:
        abort(403)
    if BUCKET_ID:
        _ = ExchangeRates(cron_job=True)
    return "Done!"


if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google App
    # Engine, a webserver process such as Gunicorn will serve the app. This
    # can be configured by adding an `entrypoint` to app.yaml.
    app.run(host="127.0.0.1", port=8080, debug=DEBUG)
