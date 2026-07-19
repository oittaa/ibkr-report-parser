"""Pure functions: match trades to closed lots and compute disposals."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import List, NamedTuple, Optional, Sequence, Tuple

from ibkr_report.definitions import (
    OPTION_MULTIPLIER,
    AssetCategory,
    ClosedLot,
    Disposal,
    ReportConfig,
    TradeOpen,
)
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.premiums import (
    PremiumIndex,
    build_premium_index,
    consume_premium,
    is_stock_exercise_assignment,
    omit_closed_lots,
    option_right,
    underlying_symbol,
)
from ibkr_report.tools import add_years

log = logging.getLogger(__name__)


def deemed_profit(sell_price: Decimal, buy_date: date, sell_date: date) -> Decimal:
    """Deemed acquisition cost profit (20% or 40% cost depending on holding period).

    https://www.vero.fi/en/individuals/property/investments/selling-shares/
    """
    multiplier = Decimal("0.8")
    if buy_date <= add_years(sell_date, -10):
        multiplier = Decimal("0.6")
    return multiplier * sell_price


def match_disposals(
    events: Sequence[TradeOpen | ClosedLot],
    config: ReportConfig,
    rates: ExchangeRates,
) -> List[Disposal]:
    """Walk events in order: pair ClosedLots with the current TradeOpen."""
    premiums = build_premium_index(events, config, rates)
    disposals: List[Disposal] = []
    open_trade: Optional[TradeOpen] = None

    for event in events:
        if isinstance(event, TradeOpen):
            open_trade = event
            continue
        if open_trade is None:
            raise ValueError("Tried to close a lot without trades.")
        disposal = _closed_lot_to_disposal(open_trade, event, premiums, config, rates)
        if disposal is not None:
            disposals.append(disposal)
    return disposals


def disposal_report_year(disposal: Disposal) -> int:
    """Calendar year a disposal belongs to for MyTax year filtering.

    For long stock the later date is the sell. For shorts the form fields still
    use open as sell and cover as buy (so ``disposed_on`` can be earlier than
    ``acquired_on``); the taxable close is the later of the two dates.
    """
    return max(disposal.acquired_on, disposal.disposed_on).year


def filter_latest_year(
    disposals: Sequence[Disposal],
) -> Tuple[Optional[int], List[Disposal]]:
    """Keep only disposals from the latest report-year present in the data."""
    if not disposals:
        return None, []
    year = max(disposal_report_year(d) for d in disposals)
    kept = [d for d in disposals if disposal_report_year(d) == year]
    return year, kept


def _closed_lot_to_disposal(
    trade: TradeOpen,
    lot: ClosedLot,
    premiums: PremiumIndex,
    config: ReportConfig,
    rates: ExchangeRates,
) -> Optional[Disposal]:
    if omit_closed_lots(trade):
        log.debug(
            "Skipping option ClosedLot for %s (codes %s) — exercise/assignment",
            trade.symbol,
            trade.codes,
        )
        return None

    _validate_lot(trade, lot)
    return disposal_from_lot(
        trade,
        lot,
        config=config,
        rates=rates,
        premium_adj=_premium_adjustments(trade, lot, premiums),
    )


def _premium_adjustments(
    trade: TradeOpen, lot: ClosedLot, premiums: PremiumIndex
) -> Tuple[Decimal, Decimal]:
    if trade.asset_category != AssetCategory.STOCKS:
        return Decimal(0), Decimal(0)

    lot_qty = abs(lot.quantity)
    if is_stock_exercise_assignment(trade):
        return consume_premium(premiums, trade.symbol, trade.trade_date, lot_qty)
    # Deferred: stock acquired via option (short put / long call), sold later.
    if lot.quantity > 0:
        return consume_premium(premiums, trade.symbol, lot.lot_date, lot_qty)
    return Decimal(0), Decimal(0)


def disposal_from_lot(
    trade: TradeOpen,
    lot: ClosedLot,
    *,
    config: ReportConfig,
    rates: ExchangeRates,
    premium_adj: Tuple[Decimal, Decimal] = (Decimal(0), Decimal(0)),
) -> Disposal:
    """Calculate realized gains/losses for a ClosedLot related to a Trade.

    ``premium_adj`` is ``(sell_price_adjustment, buy_price_adjustment)`` in
    report currency.
    """
    disposal = _build_disposal(trade, lot, config, rates, premium_adj)
    log.debug(
        "Symbol: %s, Quantity: %.2f, Buy date: %s, Buy price: %.2f, "
        "Sell date: %s, Selling price: %.2f, Gains/Losses: %.2f, deemed=%s",
        disposal.symbol,
        disposal.quantity,
        disposal.acquired_on,
        disposal.acquisition_cost,
        disposal.disposed_on,
        disposal.proceeds,
        disposal.realized,
        disposal.used_deemed_acquisition_cost,
    )
    return disposal


def _build_disposal(
    trade: TradeOpen,
    lot: ClosedLot,
    config: ReportConfig,
    rates: ExchangeRates,
    premium_adj: Tuple[Decimal, Decimal],
) -> Disposal:
    """Core money math for one matched Trade + ClosedLot pair."""
    sides = _position_sides(trade, lot, config, rates)
    qty = abs(lot.quantity)
    mult = OPTION_MULTIPLIER if lot.asset_category == AssetCategory.OPTIONS else 1
    proceeds = qty * sides.unit_sell * mult + premium_adj[0]
    cost = max(qty * sides.unit_buy * mult + premium_adj[1], Decimal(0))
    fee = _allocated_fee(trade, lot, sides.trade_rate)
    realized, used_deemed = _apply_deemed(
        proceeds - cost - fee,
        proceeds,
        sides.acquired_on,
        sides.disposed_on,
        config,
    )
    return Disposal(
        symbol=lot.symbol,
        quantity=qty,
        acquired_on=sides.acquired_on,
        acquisition_cost=cost,
        disposed_on=sides.disposed_on,
        proceeds=proceeds,
        realized=realized,
        used_deemed_acquisition_cost=used_deemed,
    )


class _Sides(NamedTuple):
    """Unit prices and dates after long/short orientation."""

    unit_sell: Decimal
    unit_buy: Decimal
    disposed_on: date
    acquired_on: date
    trade_rate: Decimal


def _position_sides(
    trade: TradeOpen,
    lot: ClosedLot,
    config: ReportConfig,
    rates: ExchangeRates,
) -> _Sides:
    trade_rate = rates.get_rate(
        config.report_currency, trade.currency, trade.trade_date
    )
    lot_rate = rates.get_rate(config.report_currency, lot.currency, lot.lot_date)
    unit_sell = trade.unit_price_native / trade_rate
    unit_buy = lot.unit_price_native / lot_rate
    disposed_on, acquired_on = trade.trade_date, lot.lot_date
    if lot.quantity < 0:
        disposed_on, acquired_on = acquired_on, disposed_on
        unit_sell, unit_buy = unit_buy, unit_sell
    return _Sides(unit_sell, unit_buy, disposed_on, acquired_on, trade_rate)


def _allocated_fee(trade: TradeOpen, lot: ClosedLot, trade_rate: Decimal) -> Decimal:
    if not trade.quantity:
        return Decimal(0)
    return lot.quantity * (trade.fee_native / trade_rate) / trade.quantity


def _apply_deemed(
    realized: Decimal,
    proceeds: Decimal,
    acquired_on: date,
    disposed_on: date,
    config: ReportConfig,
) -> Tuple[Decimal, bool]:
    if not config.use_deemed_acquisition_cost:
        return realized, False
    deemed = deemed_profit(proceeds, acquired_on, disposed_on)
    if deemed < realized:
        return deemed, True
    return realized, False


def _validate_lot(trade: TradeOpen, lot: ClosedLot) -> None:
    if trade.symbol != lot.symbol:
        raise ValueError(
            f"Symbol mismatch! Date: {lot.lot_date}, "
            f"Trade: {trade.symbol}, ClosedLot: {lot.symbol}"
        )
    if abs(trade.quantity + lot.quantity) > abs(trade.quantity):
        raise ValueError(
            'Invalid data. "Trade" and "ClosedLot" quantities do not match. '
            f"Date: {lot.lot_date}, Symbol: {lot.symbol}"
        )


__all__ = [
    "deemed_profit",
    "disposal_from_lot",
    "disposal_report_year",
    "filter_latest_year",
    "is_stock_exercise_assignment",
    "match_disposals",
    "omit_closed_lots",
    "option_right",
    "underlying_symbol",
]
