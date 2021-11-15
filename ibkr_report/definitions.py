import os
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum, IntEnum, unique
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


# TODO: StrEnum available in Python 3.11+
class StrEnum(str, Enum):  # pragma: no cover
    """
    Enum where members are also (and must be) strings
    """

    def __new__(cls, *values):
        if len(values) > 3:
            raise TypeError("too many arguments for str(): %r" % (values,))
        if len(values) == 1:
            # it must be a string
            if not isinstance(values[0], str):
                raise TypeError("%r is not a string" % (values[0],))
        if len(values) >= 2:
            # check that encoding argument is a string
            if not isinstance(values[1], str):
                raise TypeError("encoding must be a string, not %r" % (values[1],))
        if len(values) == 3:
            # check that errors argument is a string
            if not isinstance(values[2], str):
                raise TypeError("errors must be a string, not %r" % (values[2]))
        value = str(*values)
        member = str.__new__(cls, value)
        member._value_ = value
        return member

    __str__ = str.__str__  # type: ignore

    __format__ = str.__format__

    def _generate_next_value_(name, start, count, last_values):
        """
        Return the lower-cased version of the member name.
        """
        return name.lower()


@unique
class Field(IntEnum):
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
    TRADE = "Trade"
    CLOSED_LOT = "ClosedLot"


@unique
class AssetCategory(StrEnum):
    STOCKS = "Stocks"
    OPTIONS = "Equity and Index Options"


@unique
class FieldValue(StrEnum):
    TRADES = "Trades"
    HEADER = "Data"


@dataclass
class RowData:
    symbol: str
    date_str: str
    rate: Decimal
    price_per_share: Decimal
    quantity: Decimal


@dataclass
class TradeDetails:
    symbol: str
    quantity: Decimal
    buy_date: str
    sell_date: str
    price: Decimal
    realized: Decimal
