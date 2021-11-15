import os
from flask import Blueprint, abort, current_app, make_response, render_template, request

from ibkr_report.definitions import TITLE
from ibkr_report.report import Report
from ibkr_report.tools import get_sri, set_logging


bp = Blueprint("website", __name__)


@bp.route("/", methods=["GET"])
def index():
    resp = make_response(render_template("index.html", title=TITLE, sri=_sri()))
    resp.cache_control.max_age = 600
    return resp


@bp.route("/result", methods=["POST"])
def result():
    if not current_app.debug:
        set_logging()
    current_app.logger.debug("Logging level: {}".format(current_app.logger.level))
    try:
        report = Report(request.files.get("file"))
    except ValueError as err:
        abort(400, description=err)
    json_format = True if request.args.get("json") is not None else False
    return show_results(report=report, json_format=json_format)


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
        sri=_sri(),
    )


@bp.errorhandler(400)
def bad_request(e):
    if request.args.get("json") is not None:
        return {"error": str(e)}, 400
    return (
        render_template(
            "error.html",
            title=TITLE,
            message=str(e),
            sri=_sri(),
        ),
        400,
    )


def _sri():
    return get_sri(
        {
            "main.css": os.path.join(
                current_app.root_path, "static", "css", "main.css"
            ),
            "main.js": os.path.join(current_app.root_path, "static", "js", "main.js"),
        }
    )
