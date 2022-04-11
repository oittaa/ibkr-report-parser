"""Constants and other definitions"""

import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, unique
from typing import Dict


def _strtobool(val: str) -> bool:
    """Convert a string representation of truth to True or False.

    True values are 'y', 'yes', 't', 'true', 'on', and '1'; false values
    are 'n', 'no', 'f', 'false', 'off', and '0'. Raises ValueError if
    'val' is anything else.
    """
    val = val.lower()
    if val in ("y", "yes", "t", "true", "on", "1"):
        return True
    if val in ("n", "no", "f", "false", "off", "0"):
        return False
    raise ValueError(f"invalid truth value {val!r}")


TITLE = os.getenv("TITLE", "IBKR Report Parser")
BUCKET_NAME = os.getenv("BUCKET_NAME", None)
BUCKET_ID = os.getenv("BUCKET_ID", BUCKET_NAME)
CURRENCY = os.getenv("CURRENCY", "EUR")
USE_DEEMED_ACQUISITION_COST = _strtobool(
    os.getenv("USE_DEEMED_ACQUISITION_COST", "TRUE")
)
STORAGE_TYPE = os.getenv("STORAGE_TYPE", "disabled").lower()
STORAGE_DIR = os.getenv("STORAGE_DIR", ".ibkr_storage")
DEBUG = _strtobool(os.getenv("DEBUG", "FALSE"))
_DEFAULT_LOGGING = "DEBUG" if DEBUG else "INFO"
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", _DEFAULT_LOGGING)
_DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
EXCHANGE_RATES_URL = os.getenv("EXCHANGE_RATES_URL", _DEFAULT_URL)

MAX_BACKTRACK_DAYS = 7
MAX_HTTP_RETRIES = 5
SAVED_RATES_FILE = "official_ecb_exchange_rates-{0}.json.xz"

DATE_FORMAT = "%Y-%m-%d"
TIME_FORMAT = " %H:%M:%S"
DATE_STR_FORMATS = (
    DATE_FORMAT + "," + TIME_FORMAT,
    DATE_FORMAT + TIME_FORMAT,
    DATE_FORMAT,
)

CurrencyDict = Dict[str, Dict[str, str]]


class StrEnum(str, Enum):
    """TODO: StrEnum available in Python 3.11+"""


@unique
class Field(StrEnum):
    """CSV indices."""

    TRADES = "Trades"
    HEADER = "Header"
    DATA_DISCRIMINATOR = "DataDiscriminator"
    ASSET_CATEGORY = "Asset Category"
    CURRENCY = "Currency"
    SYMBOL = "Symbol"
    DATE_TIME = "Date/Time"
    EXCHANGE = "Exchange"
    QUANTITY = "Quantity"
    TRANSACTION_PRICE = "T. Price"
    PROCEEDS = "Proceeds"
    COMMISSION_AND_FEES = "Comm/Fee"
    BASIS = "Basis"
    REALIZED_PL = "Realized P/L"
    CODE = "Code"


@unique
class DataDiscriminator(StrEnum):
    """CSV DataDiscriminator values"""

    TRADE = "Trade"
    CLOSED_LOT = "ClosedLot"


@unique
class AssetCategory(StrEnum):
    """CSV Asset Category values"""

    STOCKS = "Stocks"
    OPTIONS = "Equity and Index Options"


@unique
class FieldValue(StrEnum):
    """Other possible values in a CSV file"""

    TRADES = "Trades"
    HEADER = "Data"


@unique
class StorageType(StrEnum):
    """Storage type"""

    DISABLED = "disabled"
    AWS = "aws"
    GCP = "gcp"
    LOCAL = "local"


@dataclass
class ReportOptions:
    """Report options"""

    report_currency: str
    deemed_acquisition_cost: bool
    fields: dict


@dataclass
class RowData:
    """Extracted data from a CSV file"""

    symbol: str
    date_str: str
    rate: Decimal
    price_per_share: Decimal
    quantity: Decimal


@dataclass
class TradeDetails:
    """Extracted and calculated data from a trade"""

    symbol: str
    quantity: Decimal
    buy_date: str
    sell_date: str
    price: Decimal
    realized: Decimal
