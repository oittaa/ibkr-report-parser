"""Flask Blueprints for the website."""

from typing import Dict, List, Union
from flask import Blueprint, Response, abort, make_response, render_template, request
from werkzeug.datastructures import FileStorage

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
        report = _report_from_upload()
    except ValueError as err:
        abort(400, description=str(err))
    json_format = request.args.get("json") is not None
    return show_results(report=report, json_format=json_format)


def _uploaded_files() -> List[FileStorage]:
    """Return non-empty uploaded CSV files (supports multi-file input)."""
    files = request.files.getlist("file")
    return [f for f in files if f and f.filename]


def _report_from_upload() -> Report:
    files = _uploaded_files()
    if not files:
        raise ValueError("No CSV file uploaded.")
    report = Report()
    for uploaded in files:
        report.add_trades(uploaded)
    return report


def show_results(
    report: Report, json_format: bool = False
) -> Union[str, Dict[str, object]]:
    """Show the results either in JSON or HTML format."""
    use_deemed = report.options.deemed_acquisition_cost
    if json_format:
        return {
            "prices": float(round(report.prices, 2)),
            "gains": float(round(report.gains, 2)),
            "losses": float(round(report.losses, 2)),
            "details": report.details,
            "report_year": report.report_year,
            "file_count": report.file_count,
            "use_deemed_acquisition_cost": use_deemed,
        }
    return render_template(
        "result.html",
        title=TITLE,
        prices=report.prices,
        gains=report.gains,
        losses=report.losses,
        details=report.details,
        report_year=report.report_year,
        file_count=report.file_count,
        use_deemed_acquisition_cost=use_deemed,
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
