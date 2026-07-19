"""Parse IBKR activity CSV rows into typed trade events."""

from __future__ import annotations

import csv
from codecs import iterdecode
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple, Union

from ibkr_report.definitions import (
    CODE_COLUMN,
    AssetCategory,
    ClosedLot,
    DataDiscriminator,
    Field,
    FieldValue,
    TradeOpen,
)
from ibkr_report.tools import decimal_cleanup, get_date

RawRow = Tuple[str, ...]
Event = Union[TradeOpen, ClosedLot]

_TRADE_ASSETS = frozenset(
    {AssetCategory.STOCKS, AssetCategory.OPTIONS, AssetCategory.WARRANTS}
)


def read_csv_rows(file: Iterable[bytes]) -> List[RawRow]:
    """Decode a UTF-8 CSV byte stream into raw row tuples."""
    try:
        return [tuple(items) for items in csv.reader(iterdecode(file, "utf-8"))]
    except UnicodeDecodeError as err:
        raise ValueError("Input data not in UTF-8 text format.") from err
    except csv.Error as err:
        # e.g. binary uploads: "_csv.Error: line contains NUL" (Python 3.10+)
        raise ValueError("Input data is not a valid CSV file.") from err


def parse_events(rows: Sequence[RawRow]) -> List[Event]:
    """Turn buffered CSV rows into TradeOpen / ClosedLot events (dates parsed once)."""
    return list(iter_events(rows))


def iter_events(rows: Sequence[RawRow]) -> Iterator[Event]:
    """Yield trade/closed-lot events from raw CSV rows, rebinding schema on headers."""
    schema: Optional[Dict[str, int]] = None
    for items in rows:
        if _is_header(items):
            schema = {name: index for index, name in enumerate(items)}
            continue
        if schema is None or len(schema) != len(items):
            continue
        if not _is_trade_section(items, schema):
            continue
        disc = items[schema[Field.DATA_DISCRIMINATOR]]
        asset = items[schema[Field.ASSET_CATEGORY]]
        if asset not in _TRADE_ASSETS:
            continue
        if disc == DataDiscriminator.TRADE:
            yield _trade_open(items, schema)
        elif disc == DataDiscriminator.CLOSED_LOT:
            yield _closed_lot(items, schema)


def _is_header(items: Sequence[str]) -> bool:
    return all(field in items for field in Field)


def _is_trade_section(items: Sequence[str], schema: Dict[str, int]) -> bool:
    return (
        items[schema[Field.TRADES]] == FieldValue.TRADES
        and items[schema[Field.HEADER]] == FieldValue.HEADER
        and items[schema[Field.DATA_DISCRIMINATOR]]
        in (DataDiscriminator.TRADE, DataDiscriminator.CLOSED_LOT)
        and items[schema[Field.ASSET_CATEGORY]] in _TRADE_ASSETS
    )


def _trade_open(items: Sequence[str], schema: Dict[str, int]) -> TradeOpen:
    return TradeOpen(
        symbol=items[schema[Field.SYMBOL]],
        trade_date=get_date(items[schema[Field.DATE_TIME]]),
        asset_category=items[schema[Field.ASSET_CATEGORY]],
        currency=items[schema[Field.CURRENCY]],
        quantity=decimal_cleanup(items[schema[Field.QUANTITY]]),
        unit_price_native=decimal_cleanup(items[schema[Field.TRANSACTION_PRICE]]),
        fee_native=decimal_cleanup(items[schema[Field.COMMISSION_AND_FEES]]),
        codes=_parse_codes(items, schema),
    )


def _closed_lot(items: Sequence[str], schema: Dict[str, int]) -> ClosedLot:
    return ClosedLot(
        symbol=items[schema[Field.SYMBOL]],
        lot_date=get_date(items[schema[Field.DATE_TIME]]),
        asset_category=items[schema[Field.ASSET_CATEGORY]],
        currency=items[schema[Field.CURRENCY]],
        quantity=decimal_cleanup(items[schema[Field.QUANTITY]]),
        unit_price_native=decimal_cleanup(items[schema[Field.TRANSACTION_PRICE]]),
    )


def _parse_codes(items: Sequence[str], schema: Dict[str, int]) -> frozenset[str]:
    code_idx = schema.get(CODE_COLUMN)
    if code_idx is None or code_idx >= len(items):
        return frozenset()
    raw = items[code_idx].strip()
    if not raw:
        return frozenset()
    return frozenset(part for part in raw.replace(" ", "").split(";") if part)
