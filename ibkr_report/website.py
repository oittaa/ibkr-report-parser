"""Flask Blueprints for the website."""

from typing import Dict, Union
from flask import Blueprint, Response, abort, make_response, render_template, request

from ibkr_report.definitions import TITLE
from ibkr_report.report import Report
from ibkr_report.tools import set_logging, _sri


bp = Blueprint("website", __name__)


@bp.route("/", methods=["GET"])
def index() -> Response:
    """Main page"""
    resp = make_response(render_template("index.html", title=TITLE, sri=_sri()))
    resp.cache_control.max_age = 600
    return resp


@bp.route("/result", methods=["POST"])
def result():
    """Parse results and pass them to show_results."""
    set_logging()
    try:
        report = Report(request.files.get("file"))
    except ValueError as err:
        abort(400, description=err)
    json_format = request.args.get("json") is not None
    return show_results(report=report, json_format=json_format)


def show_results(
    report: Report, json_format: bool = False
) -> Union[str, Dict[str, object]]:
    """Show the results either in JSON or HTML format."""
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
def bad_request(err):
    """Error response for bad requests."""
    if request.args.get("json") is not None:
        return {"error": str(err)}, 400
    return (
        render_template(
            "error.html",
            title=TITLE,
            message=str(err),
            sri=_sri(),
        ),
        400,
    )
