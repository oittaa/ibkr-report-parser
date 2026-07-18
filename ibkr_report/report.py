"""
Total selling prices, total capital gains, and total capital losses calculated
from the CSV files.
"""

import csv
import logging
from codecs import iterdecode
from collections import defaultdict
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from ibkr_report.definitions import (
    CURRENCY,
    USE_DEEMED_ACQUISITION_COST,
    AssignmentPremium,
    AssetCategory,
    DataDiscriminator,
    Field,
    FieldValue,
    ReportOptions,
    TradeDetails,
)
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.tools import date_without_time, decimal_cleanup
from ibkr_report.trade import Trade

log = logging.getLogger(__name__)

# (underlying symbol, assignment/exercise date) -> premium pools
AssignmentPremiumMap = Dict[Tuple[str, str], List[AssignmentPremium]]


class Report:
    """Total selling prices, total capital gains, and total capital losses
    calculated from the CSV files.

    When calculating the amount of profit or loss, you can deduct the deemed
    acquisition cost from the selling price of the shares, instead of deducting
    the purchase price of the shares as well as the expenses incurred in
    making a profit.

    Args:
        file (Iterable[bytes]): The input file in CSV format.
        report_currency (str): The currency used in the output.
        use_deemed_acquisition_cost (bool): Whether to use the deemed acquisition cost
                                            if it benefits you.

    Attributes:
        prices (Decimal): Total selling prices.
        gains (Decimal): Total capital gains.
        losses (Decimal): Total capital losses.
        details(List[TradeDetails]): Details from trades such as dates and quantities.
        options (ReportOptions): Report currency, whether to use the deemed
                                 acquisition cost.
        rates (ExchangeRates): Euro foreign exchange rates.
    """

    prices: Decimal = Decimal(0)
    gains: Decimal = Decimal(0)
    losses: Decimal = Decimal(0)
    details: List[TradeDetails]
    options: ReportOptions
    rates: ExchangeRates
    _trade: Optional[Trade] = None
    _assignment_premiums: AssignmentPremiumMap

    def __init__(
        self,
        file: Optional[Iterable[bytes]] = None,
        report_currency: str = CURRENCY,
        use_deemed_acquisition_cost: bool = USE_DEEMED_ACQUISITION_COST,
    ) -> None:
        self.details = []
        self.options = ReportOptions(
            report_currency=report_currency.upper(),
            deemed_acquisition_cost=use_deemed_acquisition_cost,
            fields={},
        )
        self.rates = ExchangeRates()
        self._assignment_premiums = defaultdict(list)
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file."""
        try:
            rows = [tuple(items) for items in csv.reader(iterdecode(file, "utf-8"))]
        except UnicodeDecodeError as err:
            raise ValueError("Input data not in UTF-8 text format.") from err

        # Stocks often appear before options in IBKR statements; scan premiums first.
        self._assignment_premiums = self._collect_assignment_premiums(rows)
        self.options.fields = {}
        self._trade = None
        for items in rows:
            self._handle_one_line(items)

    def is_trade(self, items: Tuple[str, ...]) -> bool:
        """Checks whether the current row is part of a trade or not."""
        if (
            len(self.options.fields) == len(items)
            and items[self.options.fields[Field.TRADES]] == FieldValue.TRADES
            and items[self.options.fields[Field.HEADER]] == FieldValue.HEADER
            and items[self.options.fields[Field.DATA_DISCRIMINATOR]]
            in (DataDiscriminator.TRADE, DataDiscriminator.CLOSED_LOT)
            and items[self.options.fields[Field.ASSET_CATEGORY]]
            in (AssetCategory.STOCKS, AssetCategory.OPTIONS, AssetCategory.WARRANTS)
        ):
            return True
        return False

    def _handle_one_line(self, items: Tuple[str, ...]) -> None:
        if all(item in items for item in Field):
            self.options.fields = {}
            self._trade = None
            for index, item in enumerate(items):
                self.options.fields[item] = index
            return
        if self.options.fields and self.is_trade(items):
            self._handle_trade(items)

    def _handle_trade(self, items: Tuple[str, ...]) -> None:
        """Parses prices, gains, and losses from trades."""
        if (
            items[self.options.fields[Field.DATA_DISCRIMINATOR]]
            == DataDiscriminator.TRADE
        ):
            self._trade = Trade(items, self.options, self.rates)
        if (
            items[self.options.fields[Field.DATA_DISCRIMINATOR]]
            == DataDiscriminator.CLOSED_LOT
        ):
            if not self._trade:
                raise ValueError("Tried to close a lot without trades.")
            # Option exercise/assignment: premium is reported on the stock leg (#1191).
            if self._trade.omit_closed_lots:
                log.info(
                    "Skipping option ClosedLot for %s (codes %s) — exercise/assignment",
                    self._trade.data.symbol,
                    self._trade.codes,
                )
                return

            premium = Decimal(0)
            if self._trade.is_stock_exercise_assignment:
                sell_date = date_without_time(self._trade.data.date_str)
                lot_qty = abs(
                    decimal_cleanup(items[self.options.fields[Field.QUANTITY]])
                )
                premium = self._consume_assignment_premium(
                    self._trade.data.symbol, sell_date, lot_qty
                )

            details = self._trade.details_from_closed_lot(
                items, assignment_premium=premium
            )
            # Sum detail prices so the total matches the result table (#1458).
            self.prices += details.price
            if details.realized > 0:
                self.gains += details.realized
            else:
                self.losses -= details.realized
            self.details.append(details)

    def _collect_assignment_premiums(
        self, rows: List[Tuple[str, ...]]
    ) -> AssignmentPremiumMap:
        """Index option premiums from exercise/assignment ClosedLots by underlying + date."""
        premiums: AssignmentPremiumMap = defaultdict(list)
        fields: Dict[str, int] = {}
        trade: Optional[Trade] = None
        # Use a throwaway options config for the scan (same currency / deemed cost).
        scan_options = ReportOptions(
            report_currency=self.options.report_currency,
            deemed_acquisition_cost=self.options.deemed_acquisition_cost,
            fields={},
        )

        for items in rows:
            if all(item in items for item in Field):
                fields = {item: index for index, item in enumerate(items)}
                scan_options.fields = fields
                trade = None
                continue
            if not fields or len(fields) != len(items):
                continue
            if (
                items[fields[Field.TRADES]] != FieldValue.TRADES
                or items[fields[Field.HEADER]] != FieldValue.HEADER
            ):
                continue
            disc = items[fields[Field.DATA_DISCRIMINATOR]]
            if disc == DataDiscriminator.TRADE:
                if items[fields[Field.ASSET_CATEGORY]] == AssetCategory.OPTIONS:
                    trade = Trade(items, scan_options, self.rates)
                else:
                    trade = None
                continue
            if (
                disc == DataDiscriminator.CLOSED_LOT
                and trade
                and trade.omit_closed_lots
            ):
                premium = trade.option_premium_from_closed_lot(items)
                shares = trade.option_shares_from_closed_lot(items)
                key = (
                    Trade.underlying_symbol(trade.data.symbol),
                    date_without_time(trade.data.date_str),
                )
                premiums[key].append(AssignmentPremium(shares=shares, premium=premium))
                log.debug(
                    "Recorded assignment premium %s for %s shares of %s on %s",
                    premium,
                    shares,
                    key[0],
                    key[1],
                )
        return premiums

    def _consume_assignment_premium(
        self, symbol: str, date: str, shares: Decimal
    ) -> Decimal:
        """Allocate option premium to a stock lot closed by assignment/exercise."""
        pools = self._assignment_premiums.get((symbol, date))
        if not pools:
            return Decimal(0)

        remaining = shares
        total = Decimal(0)
        for pool in pools:
            if remaining <= 0:
                break
            if pool.shares <= 0:
                continue
            take = min(remaining, pool.shares)
            portion = pool.premium * take / pool.shares
            total += portion
            pool.premium -= portion
            pool.shares -= take
            remaining -= take
        if total:
            log.info(
                "Applied option premium %.2f to %s stock assignment on %s (%.0f shares)",
                total,
                symbol,
                date,
                shares,
            )
        return total
