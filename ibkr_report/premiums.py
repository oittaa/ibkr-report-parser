"""Build and consume option assignment/exercise premium pools."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Dict, List, Sequence, Tuple

from ibkr_report.definitions import (
    EXERCISE_ASSIGNMENT_CODES,
    OPTION_MULTIPLIER,
    AssetCategory,
    ClosedLot,
    PremiumLot,
    ReportConfig,
    TradeOpen,
)
from ibkr_report.exchangerates import ExchangeRates

log = logging.getLogger(__name__)

PremiumKey = Tuple[str, date]
PremiumIndex = Dict[PremiumKey, List[PremiumLot]]


def omit_closed_lots(trade: TradeOpen) -> bool:
    """True when an option trade is closed by exercise or assignment (#1191)."""
    return trade.asset_category == AssetCategory.OPTIONS and bool(
        trade.codes & EXERCISE_ASSIGNMENT_CODES
    )


def is_stock_exercise_assignment(trade: TradeOpen) -> bool:
    """True when a stock trade results from option exercise or assignment."""
    return trade.asset_category == AssetCategory.STOCKS and bool(
        trade.codes & EXERCISE_ASSIGNMENT_CODES
    )


def underlying_symbol(option_symbol: str) -> str:
    """IBKR option symbols start with the underlying ticker (e.g. 'ARKK 19SEP25 80 C')."""
    return option_symbol.split()[0]


def option_right(option_symbol: str) -> str:
    """Return 'C' or 'P' from an IBKR option symbol, or '' if unknown."""
    parts = option_symbol.split()
    if not parts:
        return ""
    right = parts[-1].upper()
    return right if right in ("C", "P") else ""


def premium_deltas(
    option_symbol: str, closed_lot_qty: Decimal, premium_mag: Decimal
) -> Tuple[Decimal, Decimal]:
    """Map option long/short and put/call to (sell_delta, basis_delta).

    ClosedLot quantity < 0 is a short option lot (credit premium received).
    Quantity > 0 is a long option lot (debit premium paid).
    """
    right = option_right(option_symbol)
    is_credit = closed_lot_qty < 0
    sell_delta = Decimal(0)
    basis_delta = Decimal(0)
    if right == "C":
        if is_credit:
            sell_delta = premium_mag  # short call assigned
        else:
            basis_delta = premium_mag  # long call exercised
    elif right == "P":
        if is_credit:
            basis_delta = -premium_mag  # short put assigned
        else:
            sell_delta = -premium_mag  # long put exercised
    return sell_delta, basis_delta


def build_premium_index(
    events: Sequence[TradeOpen | ClosedLot],
    config: ReportConfig,
    rates: ExchangeRates,
) -> PremiumIndex:
    """Index option premiums from exercise/assignment ClosedLots by underlier + date."""
    premiums: PremiumIndex = defaultdict(list)
    open_trade: TradeOpen | None = None

    for event in events:
        if isinstance(event, TradeOpen):
            open_trade = (
                event if event.asset_category == AssetCategory.OPTIONS else None
            )
            continue
        if (
            open_trade is None
            or not omit_closed_lots(open_trade)
            or not isinstance(event, ClosedLot)
        ):
            continue

        premium_mag = _option_premium_report(open_trade, event, config, rates)
        shares = abs(event.quantity) * OPTION_MULTIPLIER
        sell_delta, basis_delta = premium_deltas(
            open_trade.symbol, event.quantity, premium_mag
        )
        key = (underlying_symbol(open_trade.symbol), open_trade.trade_date)
        premiums[key].append(
            PremiumLot(shares=shares, sell_delta=sell_delta, basis_delta=basis_delta)
        )
        log.debug(
            "Recorded assignment premium for %s shares of %s on %s "
            "(sell_delta=%s, basis_delta=%s)",
            shares,
            key[0],
            key[1],
            sell_delta,
            basis_delta,
        )
    return premiums


def consume_premium(
    premiums: PremiumIndex, symbol: str, on: date, shares: Decimal
) -> Tuple[Decimal, Decimal]:
    """Allocate option premium to a stock lot; return (sell_delta, basis_delta).

    Mutates remaining pool entries for this pipeline run only.
    """
    pools = premiums.get((symbol, on))
    if not pools:
        return Decimal(0), Decimal(0)

    remaining = shares
    total_sell = Decimal(0)
    total_basis = Decimal(0)
    for i, pool in enumerate(pools):
        if remaining <= 0:
            break
        if pool.shares <= 0:
            continue
        take = min(remaining, pool.shares)
        portion_sell = pool.sell_delta * take / pool.shares
        portion_basis = pool.basis_delta * take / pool.shares
        total_sell += portion_sell
        total_basis += portion_basis
        # Replace with reduced pool (PremiumLot is frozen).
        pools[i] = PremiumLot(
            shares=pool.shares - take,
            sell_delta=pool.sell_delta - portion_sell,
            basis_delta=pool.basis_delta - portion_basis,
        )
        remaining -= take

    if total_sell or total_basis:
        log.debug(
            "Applied option premium to %s on %s (%.0f shares): "
            "sell_delta=%.2f basis_delta=%.2f",
            symbol,
            on,
            shares,
            total_sell,
            total_basis,
        )
    return total_sell, total_basis


def _option_premium_report(
    trade: TradeOpen,
    lot: ClosedLot,
    config: ReportConfig,
    rates: ExchangeRates,
) -> Decimal:
    """Premium magnitude in report currency for an option ClosedLot."""
    # Use the assignment/exercise trade date rate (same day as stock leg).
    rate = rates.get_rate(config.report_currency, trade.currency, trade.trade_date)
    premium_native = abs(lot.quantity) * lot.unit_price_native * OPTION_MULTIPLIER
    return premium_native / rate
