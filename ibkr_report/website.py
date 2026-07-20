"""Flask Blueprints for the website."""

from decimal import Decimal
from typing import Dict, List, Union

from flask import (
    Blueprint,
    Response,
    abort,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.datastructures import FileStorage

from ibkr_report.definitions import TITLE, Disposal
from ibkr_report.i18n import (
    LANG_COOKIE,
    LANG_COOKIE_MAX_AGE,
    SUPPORTED_LANGS,
    detect_lang_from_request,
    make_translator,
    normalize_lang,
)
from ibkr_report.report import Report
from ibkr_report.tools import set_logging, _sri

bp = Blueprint("website", __name__)


def _template_lang_context() -> Dict[str, object]:
    lang = detect_lang_from_request(request)
    return {
        "lang": lang,
        "t": make_translator(lang),
        "supported_langs": SUPPORTED_LANGS,
    }


def _set_lang_cookie(resp: Response, lang: str) -> None:
    resp.set_cookie(
        LANG_COOKIE,
        lang,
        max_age=LANG_COOKIE_MAX_AGE,
        samesite="Lax",
        path="/",
    )


@bp.route("/", methods=["GET"])
def index() -> Response:
    """Main page"""
    query_lang = normalize_lang(request.args.get("lang"))
    if query_lang:
        # Persist preference and redirect to a clean URL.
        resp = make_response(redirect(url_for("website.index")))
        _set_lang_cookie(resp, query_lang)
        return resp

    lang = detect_lang_from_request(request)
    resp = make_response(
        render_template(
            "index.html",
            title=TITLE,
            sri=_sri(),
            **_template_lang_context(),
        )
    )
    resp.cache_control.max_age = 600
    # Vary on language so shared caches don't mix FI/EN.
    resp.headers["Vary"] = "Cookie, Accept-Language"
    # Ensure first-time visitors with Accept-Language get a cookie for later POSTs.
    if LANG_COOKIE not in request.cookies:
        _set_lang_cookie(resp, lang)
    return resp


@bp.route("/result", methods=["POST"])
def result():
    """Parse results and pass them to show_results."""
    set_logging()
    try:
        report = _report_from_upload()
        # Force pipeline here so parse/match ValueErrors become HTTP 400.
        report.result()
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


def _json_number(value: Decimal) -> float:
    return float(round(value, 2))


def _disposal_json(item: Disposal) -> Dict[str, object]:
    return {
        "symbol": item.symbol,
        "quantity": _json_number(item.quantity),
        "acquired_on": item.acquired_on.isoformat(),
        "acquisition_cost": _json_number(item.acquisition_cost),
        "disposed_on": item.disposed_on.isoformat(),
        "proceeds": _json_number(item.proceeds),
        "realized": _json_number(item.realized),
        "used_deemed_acquisition_cost": item.used_deemed_acquisition_cost,
    }


def show_results(
    report: Report, json_format: bool = False
) -> Union[str, Dict[str, object]]:
    """Show the results either in JSON or HTML format."""
    outcome = report.result()
    use_deemed = outcome.config.use_deemed_acquisition_cost
    if json_format:
        return {
            "proceeds": _json_number(outcome.totals.proceeds),
            "gains": _json_number(outcome.totals.gains),
            "losses": _json_number(outcome.totals.losses),
            "disposals": [_disposal_json(d) for d in outcome.disposals],
            "report_year": outcome.year,
            "file_count": outcome.file_count,
            "use_deemed_acquisition_cost": use_deemed,
        }
    return render_template(
        "result.html",
        title=TITLE,
        proceeds=outcome.totals.proceeds,
        gains=outcome.totals.gains,
        losses=outcome.totals.losses,
        disposals=outcome.disposals,
        report_year=outcome.year,
        file_count=outcome.file_count,
        use_deemed_acquisition_cost=use_deemed,
        sri=_sri(),
        **_template_lang_context(),
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
            **_template_lang_context(),
        ),
        400,
    )
