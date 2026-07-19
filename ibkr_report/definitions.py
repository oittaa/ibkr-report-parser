"""Constants and other definitions"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum, unique
from typing import Dict, Optional, Sequence


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
    """String enum compatible with Python 3.10 (stdlib StrEnum is 3.11+)."""


@unique
class Field(StrEnum):
    """CSV fields used by the application"""

    TRADES = "Trades"
    HEADER = "Header"
    DATA_DISCRIMINATOR = "DataDiscriminator"
    ASSET_CATEGORY = "Asset Category"
    CURRENCY = "Currency"
    SYMBOL = "Symbol"
    DATE_TIME = "Date/Time"
    QUANTITY = "Quantity"
    TRANSACTION_PRICE = "T. Price"
    # Present in IBKR headers; not used in P/L math (selling price comes from lots).
    PROCEEDS = "Proceeds"
    COMMISSION_AND_FEES = "Comm/Fee"


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
    WARRANTS = "Warrants"


@unique
class FieldValue(StrEnum):
    """Other possible values in a CSV file"""

    TRADES = "Trades"
    HEADER = "Data"


# Optional CSV column (not required in Field — older exports may omit it).
CODE_COLUMN = "Code"

# IBKR trade codes that close an option into the underlying (no option P/L).
EXERCISE_ASSIGNMENT_CODES = frozenset({"A", "Ex"})

# Equity/index options: one contract is 100 shares of the underlying.
OPTION_MULTIPLIER = 100


@unique
class StorageType(StrEnum):
    """Storage type"""

    DISABLED = "disabled"
    AWS = "aws"
    GCP = "gcp"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class ReportConfig:
    """Immutable report configuration (no parse-state)."""

    report_currency: str
    use_deemed_acquisition_cost: bool


@dataclass(frozen=True, slots=True)
class PremiumLot:
    """Option premium pool for a related stock assignment/exercise.

    Amounts are in report currency for ``shares`` of the underlying.

    ``sell_delta`` is added to stock proceeds (short call assignment, long put
    exercise). ``basis_delta`` is added to stock acquisition cost (long call
    exercise increases cost; short put assignment decreases it).
    """

    shares: Decimal
    sell_delta: Decimal = Decimal(0)
    basis_delta: Decimal = Decimal(0)


@dataclass(frozen=True, slots=True)
class TradeOpen:
    """A Trade row from an IBKR activity statement (may pair with ClosedLots)."""

    symbol: str
    trade_date: date
    asset_category: str
    currency: str
    quantity: Decimal
    unit_price_native: Decimal
    fee_native: Decimal
    codes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ClosedLot:
    """A ClosedLot row from an IBKR activity statement."""

    symbol: str
    lot_date: date
    asset_category: str
    currency: str
    quantity: Decimal  # signed: short lots are negative
    unit_price_native: Decimal


@dataclass(frozen=True, slots=True)
class Disposal:
    """One taxable disposal (ClosedLot matched to a Trade), in report currency."""

    symbol: str
    quantity: Decimal
    acquired_on: date
    acquisition_cost: Decimal  # total, report currency (incl. option adjustments)
    disposed_on: date
    proceeds: Decimal  # total selling price, report currency
    realized: Decimal
    used_deemed_acquisition_cost: bool = False


@dataclass(frozen=True, slots=True)
class Totals:
    """Aggregated MyTax totals for a report year."""

    proceeds: Decimal
    gains: Decimal
    losses: Decimal

    @staticmethod
    def from_disposals(rows: Sequence[Disposal]) -> Totals:
        """Sum proceeds and split realized into gains vs losses."""
        proceeds = Decimal(0)
        gains = Decimal(0)
        losses = Decimal(0)
        for row in rows:
            proceeds += row.proceeds
            if row.realized > 0:
                gains += row.realized
            else:
                losses -= row.realized
        return Totals(proceeds=proceeds, gains=gains, losses=losses)


@dataclass(frozen=True, slots=True)
class ReportResult:
    """Immutable outcome of processing one or more CSV files."""

    year: Optional[int]
    file_count: int
    totals: Totals
    disposals: tuple[Disposal, ...]
    config: ReportConfig
