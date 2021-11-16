"""Cron jobs"""

from flask import Blueprint, abort, request

from ibkr_report.definitions import BUCKET_ID
from ibkr_report.exchangerates import ExchangeRates


bp = Blueprint("cron", __name__)


@bp.route("/cron", methods=["GET"])
def cron():
    """Cron function that fetches the latest exchange rates if necessary."""
    if request.headers.get("X-Appengine-Cron") is None:
        abort(403)
    if BUCKET_ID:
        _ = ExchangeRates(cron_job=True)
    return "Done!"
