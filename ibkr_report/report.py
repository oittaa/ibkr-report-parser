"""
Total selling prices, total capital gains, and total capital losses calculated
from the CSV files.
"""

import csv
from codecs import iterdecode
from decimal import Decimal
from typing import Iterable, List, Optional, Tuple

from ibkr_report.definitions import (
    CURRENCY,
    FIELD_COUNT,
    OFFSET_DICT,
    USE_DEEMED_ACQUISITION_COST,
    AssetCategory,
    DataDiscriminator,
    Field,
    FieldValue,
    ReportOptions,
    TradeDetails,
)
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.trade import Trade


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

    def __init__(
        self,
        file: Iterable[bytes] = None,
        report_currency: str = CURRENCY,
        use_deemed_acquisition_cost: bool = USE_DEEMED_ACQUISITION_COST,
    ) -> None:
        self.details = []
        self.options = ReportOptions(
            report_currency=report_currency.upper(),
            deemed_acquisition_cost=use_deemed_acquisition_cost,
            offset=0,
        )
        self.rates = ExchangeRates()
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file."""
        try:
            for items_list in csv.reader(iterdecode(file, "utf-8")):
                items = tuple(items_list)
                self._handle_one_line(items)
        except UnicodeDecodeError as err:
            raise ValueError("Input data not in UTF-8 text format.") from err

    def is_stock_or_options_trade(self, items: Tuple[str, ...]) -> bool:
        """Checks whether the current row is part of a trade or not."""
        if (
            len(items) == FIELD_COUNT + self.options.offset
            and items[Field.TRADES] == FieldValue.TRADES
            and items[Field.HEADER] == FieldValue.HEADER
            and items[Field.DATA_DISCRIMINATOR]
            in (DataDiscriminator.TRADE, DataDiscriminator.CLOSED_LOT)
            and items[Field.ASSET_CATEGORY]
            in (AssetCategory.STOCKS, AssetCategory.OPTIONS)
        ):
            return True
        return False

    def _handle_one_line(self, items: Tuple[str, ...]) -> None:
        offset = OFFSET_DICT.get(items)
        if offset is not None:
            self.options.offset = offset
            self._trade = None
            return
        if self.is_stock_or_options_trade(items):
            self._handle_trade(items)

    def _handle_trade(self, items: Tuple[str, ...]) -> None:
        """Parses prices, gains, and losses from trades."""
        if items[Field.DATA_DISCRIMINATOR] == DataDiscriminator.TRADE:
            self._trade = Trade(items, self.options, self.rates)
            self.prices += self._trade.total_selling_price
        if items[Field.DATA_DISCRIMINATOR] == DataDiscriminator.CLOSED_LOT:
            if not self._trade:
                raise ValueError("Tried to close a lot without trades.")
            details = self._trade.details_from_closed_lot(items)
            if details.realized > 0:
                self.gains += details.realized
            else:
                self.losses -= details.realized
            self.details.append(details)
