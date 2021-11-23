"""Extracts details about trades."""

import logging
from decimal import Decimal
from typing import Tuple

from ibkr_report.definitions import (
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
    closed_quantity: Decimal = Decimal(0)
    total_selling_price: Decimal = Decimal(0)
    data: RowData
    options: ReportOptions
    rates: ExchangeRates

    def __init__(
        self, items: Tuple[str, ...], options: ReportOptions, rates: ExchangeRates
    ) -> None:
        """Initializes the Trade and calculates the total selling price from it."""
        self.options = options
        self.rates = rates
        self.data = self._row_data(items)

        fee = decimal_cleanup(items[Field.COMMISSION_AND_FEES + self.options.offset])
        self.fee = fee / self.data.rate

        # Sold stocks have a negative value in the "Quantity" column
        if self.data.quantity < Decimal(0):
            proceeds = decimal_cleanup(items[Field.PROCEEDS + self.options.offset])
            self.total_selling_price = proceeds / self.data.rate
        log.debug(
            'Trade: "%s" "%s" %.2f',
            self.data.date_str,
            self.data.symbol,
            self.data.quantity,
        )

    def details_from_closed_lot(self, items: Tuple[str, ...]) -> TradeDetails:
        """Calculates the realized gains or losses from the ClosedLot related to the Trade."""
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
        multiplier = 100 if items[Field.ASSET_CATEGORY] == AssetCategory.OPTIONS else 1
        lot_sell_price = abs(lot_data.quantity) * unit_sell_price * multiplier
        lot_buy_price = abs(lot_data.quantity) * unit_buy_price * multiplier
        lot_fee = lot_data.quantity * self.fee / self.data.quantity
        realized = lot_sell_price - lot_buy_price - lot_fee
        if self.options.deemed_acquisition_cost:
            deemed_profit = self.deemed_profit(lot_sell_price, buy_date, sell_date)
            realized = min(realized, deemed_profit)

        log.info(
            "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, "
            "Selling price: %.2f, Gains/Losses: %.2f",
            lot_data.symbol,
            abs(lot_data.quantity),
            buy_date,
            sell_date,
            lot_sell_price,
            realized,
        )
        self.closed_quantity += lot_data.quantity
        if self.closed_quantity + self.data.quantity == Decimal(0):
            log.debug("All lots closed")
        return TradeDetails(
            symbol=lot_data.symbol,
            quantity=abs(lot_data.quantity),
            buy_date=buy_date,
            sell_date=sell_date,
            price=lot_sell_price,
            realized=realized,
        )

    def _row_data(self, items: Tuple[str, ...]) -> RowData:
        symbol = items[Field.SYMBOL + self.options.offset]
        date_str = items[Field.DATE_TIME + self.options.offset]
        rate = self.rates.get_rate(
            currency_from=self.options.report_currency,
            currency_to=items[Field.CURRENCY],
            date_str=date_str,
        )
        original_price_per_share = items[Field.TRANSACTION_PRICE + self.options.offset]
        price_per_share = decimal_cleanup(original_price_per_share) / rate
        quantity = decimal_cleanup(items[Field.QUANTITY + self.options.offset])
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
