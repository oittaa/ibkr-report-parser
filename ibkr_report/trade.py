import logging
from datetime import datetime
from decimal import Decimal
from typing import Tuple

from ibkr_report.definitions import _DATE, AssetCategory, Field, RowData, TradeDetails
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.tools import (
    Cache,
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
    offset: int = 0
    data: RowData

    def __init__(self, items: Tuple[str, ...], offset: int) -> None:
        """Initializes the Trade and calculates the total selling price from it."""
        self.offset = offset
        self.data = self._row_data(items)
        self.fee = (
            decimal_cleanup(items[Field.COMMISSION_AND_FEES + offset]) / self.data.rate
        )
        # Sold stocks have a negative value in the "Quantity" column
        if self.data.quantity < Decimal(0):
            self.total_selling_price = (
                decimal_cleanup(items[Field.PROCEEDS + offset]) / self.data.rate
            )
        log.debug(
            'Trade: "%s" "%s" %.2f',
            self.data.date_str,
            self.data.symbol,
            self.data.quantity,
        )

    def details_from_closed_lot(self, items: Tuple[str, ...]) -> TradeDetails:
        """Calculates the realized gains or losses from the ClosedLot related to the Trade."""
        error_msg = ""
        lot_data = self._row_data(items)
        if self.data.symbol != lot_data.symbol:
            error_msg = "Symbol mismatch! Date: {}, Trade: {}, ClosedLot: {}".format(
                lot_data.date_str, self.data.symbol, lot_data.symbol
            )
        elif abs(self.data.quantity + lot_data.quantity) > abs(self.data.quantity):
            error_msg = 'Invalid data. "Trade" and "ClosedLot" quantities do not match. Date: {}, Symbol: {}'.format(
                lot_data.date_str, lot_data.symbol
            )
        if error_msg:
            log.debug(items)
            raise ValueError(error_msg)

        sell_date = date_without_time(self.data.date_str)
        sell_price = self.data.price_per_share
        buy_date = date_without_time(lot_data.date_str)
        buy_price = lot_data.price_per_share

        # Swap if closing a short position
        if lot_data.quantity < Decimal(0):
            sell_date, buy_date = buy_date, sell_date
            sell_price, buy_price = buy_price, sell_price

        # One option represents 100 shares of the underlying stock
        multiplier = 100 if items[Field.ASSET_CATEGORY] == AssetCategory.OPTIONS else 1

        realized = (
            abs(lot_data.quantity) * (sell_price - buy_price) * multiplier
            - lot_data.quantity * self.fee / self.data.quantity
        )
        total_sell_price = abs(lot_data.quantity) * sell_price * multiplier
        realized = min(
            realized,
            self.deemed_profit(total_sell_price, buy_date, sell_date),
        )
        log.info(
            "Symbol: %s, Quantity: %.2f, Buy date: %s, Sell date: %s, Selling price: %.2f, Gains/Losses: %.2f",
            lot_data.symbol,
            abs(lot_data.quantity),
            buy_date,
            sell_date,
            total_sell_price,
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
            price=total_sell_price,
            realized=realized,
        )

    def _row_data(self, items: Tuple[str, ...]) -> RowData:
        symbol = items[Field.SYMBOL + self.offset]
        date_str = items[Field.DATE_TIME + self.offset]
        rate = self.currency_rate(
            items[Field.CURRENCY], items[Field.DATE_TIME + self.offset]
        )
        price_per_share = (
            decimal_cleanup(items[Field.TRANSACTION_PRICE + self.offset]) / rate
        )
        quantity = decimal_cleanup(items[Field.QUANTITY + self.offset])
        return RowData(symbol, date_str, rate, price_per_share, quantity)

    @staticmethod
    def currency_rate(currency: str, date_str: str) -> Decimal:
        """Currency's exchange rate on a given day. Caches results."""
        cache_key = datetime.now().strftime(_DATE)
        rates = Cache.get(cache_key)
        if not rates:
            log.debug("Cache miss: %s", cache_key)
            rates = ExchangeRates()
            Cache.set(key=cache_key, value=rates)
        return rates.eur_exchange_rate(currency, date_str)

    @staticmethod
    def deemed_profit(sell_price: Decimal, buy_date: str, sell_date: str) -> Decimal:
        """If you have owned the shares you sell for less than 10 years, the deemed
        acquisition cost is 20% of the selling price of the shares.
        If you have owned the shares you sell for at least 10 years, the deemed
        acquisition cost is 40% of the selling price of the shares.
        """
        multiplier = Decimal(0.8)
        if get_date(buy_date) <= add_years(get_date(sell_date), -10):
            multiplier = Decimal(0.6)
        return multiplier * sell_price
