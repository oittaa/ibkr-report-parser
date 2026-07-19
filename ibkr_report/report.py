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
from ibkr_report.tools import date_without_time, decimal_cleanup, get_date
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

    Multiple CSV files may be added (e.g. several tax years). After processing,
    only disposals from the latest calendar year present in the data are kept,
    so earlier-year option premiums can still adjust a later stock sale while
    the MyTax totals reflect a single year.

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
        report_year (Optional[int]): Calendar year of disposals in the report.
        file_count (int): Number of CSV files added.
    """

    prices: Decimal
    gains: Decimal
    losses: Decimal
    details: List[TradeDetails]
    options: ReportOptions
    rates: ExchangeRates
    report_year: Optional[int]
    file_count: int
    _trade: Optional[Trade]
    _rows: List[Tuple[str, ...]]

    def __init__(
        self,
        file: Optional[Iterable[bytes]] = None,
        report_currency: str = CURRENCY,
        use_deemed_acquisition_cost: bool = USE_DEEMED_ACQUISITION_COST,
    ) -> None:
        self.prices = Decimal(0)
        self.gains = Decimal(0)
        self.losses = Decimal(0)
        self.details = []
        self.report_year = None
        self.file_count = 0
        self._rows = []
        self.options = ReportOptions(
            report_currency=report_currency.upper(),
            deemed_acquisition_cost=use_deemed_acquisition_cost,
            fields={},
        )
        self.rates = ExchangeRates()
        self._trade = None
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file.

        Rows are buffered so multiple files can be combined in any order (e.g.
        a 2024 statement uploaded before 2023) and premiums still match.
        """
        try:
            rows = [tuple(items) for items in csv.reader(iterdecode(file, "utf-8"))]
        except UnicodeDecodeError as err:
            raise ValueError("Input data not in UTF-8 text format.") from err
        except csv.Error as err:
            # e.g. binary uploads: "_csv.Error: line contains NUL" (Python 3.10+)
            raise ValueError("Input data is not a valid CSV file.") from err

        self._rows.extend(rows)
        self.file_count += 1
        self._reprocess()

    def _reprocess(self) -> None:
        """Recompute details and totals from all buffered rows."""
        self.prices = Decimal(0)
        self.gains = Decimal(0)
        self.losses = Decimal(0)
        self.details = []
        self.report_year = None
        self.options.fields = {}
        self._trade = None

        premiums = self._collect_assignment_premiums(self._rows)
        for items in self._rows:
            self._handle_one_line(items, premiums)
        self._filter_latest_year()

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

    def _handle_one_line(
        self, items: Tuple[str, ...], premiums: AssignmentPremiumMap
    ) -> None:
        if all(item in items for item in Field):
            self.options.fields = {}
            self._trade = None
            for index, item in enumerate(items):
                self.options.fields[item] = index
            return
        if self.options.fields and self.is_trade(items):
            self._handle_trade(items, premiums)

    def _handle_trade(
        self, items: Tuple[str, ...], premiums: AssignmentPremiumMap
    ) -> None:
        """Parses prices, gains, and losses from trades."""
        discriminator = items[self.options.fields[Field.DATA_DISCRIMINATOR]]
        if discriminator == DataDiscriminator.TRADE:
            self._trade = Trade(items, self.options, self.rates)
            return
        if discriminator != DataDiscriminator.CLOSED_LOT:
            return
        if not self._trade:
            raise ValueError("Tried to close a lot without trades.")
        # Option exercise/assignment: premium is reported on the stock leg (#1191).
        if self._trade.omit_closed_lots:
            log.debug(
                "Skipping option ClosedLot for %s (codes %s) — exercise/assignment",
                self._trade.data.symbol,
                self._trade.codes,
            )
            return

        sell_adj, buy_adj = self._premium_adjustments_for_stock_lot(items, premiums)
        details = self._trade.details_from_closed_lot(
            items,
            sell_price_adjustment=sell_adj,
            buy_price_adjustment=buy_adj,
        )
        # Sum detail prices so the total matches the result table (#1458).
        self.prices += details.price
        if details.realized > 0:
            self.gains += details.realized
        else:
            self.losses -= details.realized
        self.details.append(details)

    def _premium_adjustments_for_stock_lot(
        self, items: Tuple[str, ...], premiums: AssignmentPremiumMap
    ) -> Tuple[Decimal, Decimal]:
        """Return (sell_price_adjustment, buy_price_adjustment) for a stock ClosedLot."""
        if not self._trade or self._trade.asset_category != AssetCategory.STOCKS:
            return Decimal(0), Decimal(0)

        lot_qty = abs(decimal_cleanup(items[self.options.fields[Field.QUANTITY]]))
        symbol = self._trade.data.symbol

        if self._trade.is_stock_exercise_assignment:
            # Same-day assignment/exercise stock disposal (e.g. short call, long put).
            trade_date = date_without_time(self._trade.data.date_str)
            return self._consume_assignment_premium(
                premiums, symbol, trade_date, lot_qty
            )

        # Deferred: stock acquired via option (short put / long call), sold later.
        # ClosedLot quantity > 0 means the lot is a long acquisition cost basis.
        lot_qty_signed = decimal_cleanup(items[self.options.fields[Field.QUANTITY]])
        if lot_qty_signed > 0:
            lot_date = date_without_time(items[self.options.fields[Field.DATE_TIME]])
            return self._consume_assignment_premium(
                premiums, symbol, lot_date, lot_qty
            )
        return Decimal(0), Decimal(0)

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
                mag = trade.option_premium_from_closed_lot(items)
                shares = trade.option_shares_from_closed_lot(items)
                lot_qty = trade.option_closed_lot_quantity(items)
                sell_delta, basis_delta = self._premium_deltas(
                    trade.data.symbol, lot_qty, mag
                )
                key = (
                    Trade.underlying_symbol(trade.data.symbol),
                    date_without_time(trade.data.date_str),
                )
                premiums[key].append(
                    AssignmentPremium(
                        shares=shares,
                        sell_delta=sell_delta,
                        basis_delta=basis_delta,
                    )
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

    @staticmethod
    def _premium_deltas(
        option_symbol: str, closed_lot_qty: Decimal, premium_mag: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """Map option long/short and put/call to sell_delta and basis_delta.

        ClosedLot quantity &lt; 0 is a short option lot (credit premium received).
        Quantity &gt; 0 is a long option lot (debit premium paid).
        """
        right = Trade.option_right(option_symbol)
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

    @staticmethod
    def _consume_assignment_premium(
        premiums: AssignmentPremiumMap, symbol: str, date: str, shares: Decimal
    ) -> Tuple[Decimal, Decimal]:
        """Allocate option premium to a stock lot; return (sell_delta, basis_delta)."""
        pools = premiums.get((symbol, date))
        if not pools:
            return Decimal(0), Decimal(0)

        remaining = shares
        total_sell = Decimal(0)
        total_basis = Decimal(0)
        for pool in pools:
            if remaining <= 0:
                break
            if pool.shares <= 0:
                continue
            take = min(remaining, pool.shares)
            portion_sell = pool.sell_delta * take / pool.shares
            portion_basis = pool.basis_delta * take / pool.shares
            total_sell += portion_sell
            total_basis += portion_basis
            pool.sell_delta -= portion_sell
            pool.basis_delta -= portion_basis
            pool.shares -= take
            remaining -= take
        if total_sell or total_basis:
            log.debug(
                "Applied option premium to %s on %s (%.0f shares): "
                "sell_delta=%.2f basis_delta=%.2f",
                symbol,
                date,
                shares,
                total_sell,
                total_basis,
            )
        return total_sell, total_basis

    def _filter_latest_year(self) -> None:
        """Keep only disposals from the latest sell-date calendar year."""
        if not self.details:
            self.report_year = None
            return

        self.report_year = max(get_date(d.sell_date).year for d in self.details)
        self.details = [
            d for d in self.details if get_date(d.sell_date).year == self.report_year
        ]
        self.prices = Decimal(0)
        self.gains = Decimal(0)
        self.losses = Decimal(0)
        for details in self.details:
            self.prices += details.price
            if details.realized > 0:
                self.gains += details.realized
            else:
                self.losses -= details.realized
        log.debug(
            "Report year %s from %d file(s); %d disposal row(s)",
            self.report_year,
            self.file_count,
            len(self.details),
        )
