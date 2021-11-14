import os
from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum, unique
from typing import Dict

BUCKET_ID = os.getenv("BUCKET_ID", None)
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
_DATE = "%Y-%m-%d"
_TIME = " %H:%M:%S"
_DATE_STR_FORMATS = (_DATE + "," + _TIME, _DATE + _TIME, _DATE)

CurrencyDict = Dict[str, Dict[str, str]]


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


@dataclass
class DataDiscriminator:
    trade: str = "Trade"
    closed_lot: str = "ClosedLot"


@dataclass
class AssetCategory:
    stocks = "Stocks"
    options = "Equity and Index Options"


@dataclass
class FieldValues:
    trades: str = "Trades"
    header: str = "Data"


@dataclass
class SRI:
    css: str
    js: str


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
