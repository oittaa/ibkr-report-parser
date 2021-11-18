"""Constants and other definitions"""

import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, IntEnum, auto, unique
from typing import Dict

TITLE = os.getenv("TITLE", "IBKR Report Parser")
BUCKET_ID = os.getenv("BUCKET_ID", None)
DEBUG = bool(os.getenv("DEBUG"))
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "INFO")
_DEFAULT_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
EXCHANGE_RATES_URL = os.getenv("EXCHANGE_RATES_URL", _DEFAULT_URL)

MAX_BACKTRACK_DAYS = 7
MAX_HTTP_RETRIES = 5
SAVED_RATES_FILE = "official_ecb_exchange_rates-{0}.json.xz"

_SINGLE_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
_MULTI_ACCOUNT = (
    "Trades,Header,DataDiscriminator,Asset Category,Currency,Account,Symbol,Date/Time,Exchange,"
    "Quantity,T. Price,Proceeds,Comm/Fee,Basis,Realized P/L,Code"
).split(",")
_OFFSET_DICT = {
    tuple(_SINGLE_ACCOUNT): 0,
    tuple(_MULTI_ACCOUNT): len(_MULTI_ACCOUNT) - len(_SINGLE_ACCOUNT),
}
_FIELD_COUNT = len(_SINGLE_ACCOUNT)
_DATE = "%Y-%m-%d"
_TIME = " %H:%M:%S"
_DATE_STR_FORMATS = (_DATE + "," + _TIME, _DATE + _TIME, _DATE)

CurrencyDict = Dict[str, Dict[str, str]]


class StrEnum(str, Enum):
    """TODO: StrEnum available in Python 3.11+"""

    ...


@unique
class Field(IntEnum):
    """CSV indices."""

    TRADES = 0
    HEADER = 1
    DATA_DISCRIMINATOR = 2
    ASSET_CATEGORY = 3
    CURRENCY = 4
    SYMBOL = 5
    DATE_TIME = 6
    EXCHANGE = 7
    QUANTITY = 8
    TRANSACTION_PRICE = 9
    PROCEEDS = 10
    COMMISSION_AND_FEES = 11
    BASIS = 12
    REALIZED_PL = 13
    CODE = 14


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
class ReportOptions(Enum):
    """Report options

    REPORT_CURRENCY:
    The currency used in the output.

    DEEMED_ACQUISITION_COST:
    The deemed acquisition cost is either 20% or 40% of the selling price. The
    percentage is determined on the basis of how long you have owned the
    property before selling it. The deemed acquisition cost is 20% of the
    selling price if you have owned the property for less than 10 years.
    """

    REPORT_CURRENCY = auto()
    DEEMED_ACQUISITION_COST = auto()
    OFFSET = auto()


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
