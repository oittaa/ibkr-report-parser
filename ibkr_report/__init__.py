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

from flask import Flask

from ibkr_report import cron, website
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.report import Report
from ibkr_report.storage import get_storage

__all__ = ["create_app", "get_storage", "ExchangeRates", "Report"]


def create_app() -> Flask:
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__)
    app.register_blueprint(cron.bp)
    app.register_blueprint(website.bp)

    return app
