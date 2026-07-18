"""Extracts details about trades."""

import logging
from decimal import Decimal
from typing import Set, Tuple

from ibkr_report.definitions import (
    CODE_COLUMN,
    EXERCISE_ASSIGNMENT_CODES,
    OPTION_MULTIPLIER,
    AssetCategory,
    Field,
    ReportOptions,
    RowData,
    TradeDetails,
)
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.tools import (
    add_years,
    date_without_time,
    decimal_cleanup,
    get_date,
)

log = logging.getLogger(__name__)


class Trade:
    """Trade which might be related to several ClosedLot rows."""

    fee: Decimal = Decimal(0)
    data: RowData
    options: ReportOptions
    rates: ExchangeRates
    asset_category: str
    codes: Set[str]

    def __init__(
        self, items: Tuple[str, ...], options: ReportOptions, rates: ExchangeRates
    ) -> None:
        """Initializes the Trade from a CSV Trade row."""
        self.options = options
        self.rates = rates
        self.data = self._row_data(items)
        self.asset_category = items[self.options.fields[Field.ASSET_CATEGORY]]
        self.codes = self._parse_codes(items)

        fee = decimal_cleanup(items[self.options.fields[Field.COMMISSION_AND_FEES]])
        self.fee = fee / self.data.rate
        log.debug(
            'Trade: "%s" "%s" %.2f codes=%s',
            self.data.date_str,
            self.data.symbol,
            self.data.quantity,
            self.codes,
        )

    @property
    def omit_closed_lots(self) -> bool:
        """True when this option trade is closed by exercise or assignment (#1191)."""
        return self.asset_category == AssetCategory.OPTIONS and bool(
            self.codes & EXERCISE_ASSIGNMENT_CODES
        )

    @property
    def is_stock_exercise_assignment(self) -> bool:
        """True when this stock trade results from option exercise or assignment."""
        return self.asset_category == AssetCategory.STOCKS and bool(
            self.codes & EXERCISE_ASSIGNMENT_CODES
        )

    def details_from_closed_lot(
        self,
        items: Tuple[str, ...],
        assignment_premium: Decimal = Decimal(0),
    ) -> TradeDetails:
        """Calculates the realized gains or losses from the ClosedLot related to the Trade.

        Args:
            assignment_premium: Option premium in report currency to include in the
                selling price when this stock lot was closed by assignment/exercise.
        """
        lot_data = self._row_data(items)
        self._validate_lot(lot_data)

        sell_date = date_without_time(self.data.date_str)
        unit_sell_price = self.data.price_per_share
        buy_date = date_without_time(lot_data.date_str)
        unit_buy_price = lot_data.price_per_share

        # Swap if closing a short position
        if lot_data.quantity < Decimal(0):
            sell_date, buy_date = buy_date, sell_date
            unit_sell_price, unit_buy_price = unit_buy_price, unit_sell_price

        # One option represents 100 shares of the underlying stock
        multiplier = (
            OPTION_MULTIPLIER
            if items[self.options.fields[Field.ASSET_CATEGORY]] == AssetCategory.OPTIONS
            else 1
        )
        lot_sell_price = abs(lot_data.quantity) * unit_sell_price * multiplier
        lot_buy_price = abs(lot_data.quantity) * unit_buy_price * multiplier
        # Premium from a related option is part of the stock disposal price (#1191).
        lot_sell_price += assignment_premium
        lot_fee = lot_data.quantity * self.fee / self.data.quantity
        realized = lot_sell_price - lot_buy_price - lot_fee
        if self.options.deemed_acquisition_cost:
            deemed_profit = self.deemed_profit(lot_sell_price, buy_date, sell_date)
            realized = min(realized, deemed_profit)

        log.debug(
            "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, "
            "Selling price: %.2f, Gains/Losses: %.2f",
            lot_data.symbol,
            abs(lot_data.quantity),
            buy_date,
            sell_date,
            lot_sell_price,
            realized,
        )
        return TradeDetails(
            symbol=lot_data.symbol,
            quantity=abs(lot_data.quantity),
            buy_date=buy_date,
            sell_date=sell_date,
            price=lot_sell_price,
            realized=realized,
        )

    def option_premium_from_closed_lot(self, items: Tuple[str, ...]) -> Decimal:
        """Premium (report currency) locked in an option ClosedLot row."""
        quantity = decimal_cleanup(items[self.options.fields[Field.QUANTITY]])
        unit_price = decimal_cleanup(
            items[self.options.fields[Field.TRANSACTION_PRICE]]
        )
        # Convert with the assignment/exercise trade date rate (same day as stock leg).
        premium_native = abs(quantity) * unit_price * OPTION_MULTIPLIER
        return premium_native / self.data.rate

    def option_shares_from_closed_lot(self, items: Tuple[str, ...]) -> Decimal:
        """Underlying share count represented by an option ClosedLot."""
        quantity = decimal_cleanup(items[self.options.fields[Field.QUANTITY]])
        return abs(quantity) * OPTION_MULTIPLIER

    def _parse_codes(self, items: Tuple[str, ...]) -> Set[str]:
        code_idx = self.options.fields.get(CODE_COLUMN)
        if code_idx is None or code_idx >= len(items):
            return set()
        raw = items[code_idx].strip()
        if not raw:
            return set()
        return {part for part in raw.replace(" ", "").split(";") if part}

    def _row_data(self, items: Tuple[str, ...]) -> RowData:
        symbol = items[self.options.fields[Field.SYMBOL]]
        date_str = items[self.options.fields[Field.DATE_TIME]]
        rate = self.rates.get_rate(
            currency_from=self.options.report_currency,
            currency_to=items[self.options.fields[Field.CURRENCY]],
            date_str=date_str,
        )
        original_price_per_share = items[self.options.fields[Field.TRANSACTION_PRICE]]
        price_per_share = decimal_cleanup(original_price_per_share) / rate
        quantity = decimal_cleanup(items[self.options.fields[Field.QUANTITY]])
        return RowData(symbol, date_str, rate, price_per_share, quantity)

    def _validate_lot(self, lot_data: RowData) -> None:
        error_msg = ""

        if self.data.symbol != lot_data.symbol:
            error_msg = (
                f"Symbol mismatch! Date: {lot_data.date_str}, "
                f"Trade: {self.data.symbol}, ClosedLot: {lot_data.symbol}"
            )
        elif abs(self.data.quantity + lot_data.quantity) > abs(self.data.quantity):
            error_msg = (
                'Invalid data. "Trade" and "ClosedLot" quantities do not match. '
                f"Date: {lot_data.date_str}, Symbol: {lot_data.symbol}"
            )
        if error_msg:
            log.debug(lot_data)
            raise ValueError(error_msg)

    @staticmethod
    def deemed_profit(sell_price: Decimal, buy_date: str, sell_date: str) -> Decimal:
        """If you have owned the shares you sell for less than 10 years, the deemed
        acquisition cost is 20% of the selling price of the shares.
        If you have owned the shares you sell for at least 10 years, the deemed
        acquisition cost is 40% of the selling price of the shares.

        https://www.vero.fi/en/individuals/property/investments/selling-shares/
        """
        multiplier = Decimal(0.8)
        if get_date(buy_date) <= add_years(get_date(sell_date), -10):
            multiplier = Decimal(0.6)
        return multiplier * sell_price

    @staticmethod
    def underlying_symbol(option_symbol: str) -> str:
        """IBKR option symbols start with the underlying ticker (e.g. 'ARKK 19SEP25 80 C')."""
        return option_symbol.split()[0]
