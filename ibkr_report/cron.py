"""App Engine Cron jobs"""

from typing import Tuple

from flask import Blueprint, abort, request

from ibkr_report.definitions import BUCKET_ID
from ibkr_report.exchangerates import ExchangeRates

bp = Blueprint("cron", __name__)


@bp.route("/cron", methods=["GET"])
def cron() -> Tuple[str, int]:
    """Cron function that fetches the latest exchange rates if necessary."""
    if request.headers.get("X-Appengine-Cron") is None:
        abort(403)
    if BUCKET_ID:
        try:
            _ = ExchangeRates()
        except ValueError as err:
            return str(err), 500
        return "Done!", 200
    return "BUCKET_ID missing!", 500
