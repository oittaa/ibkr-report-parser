"""
Total selling prices, total capital gains, and total capital losses calculated
from the CSV files.
"""

import csv
from codecs import iterdecode
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from ibkr_report.definitions import (
    _FIELD_COUNT,
    _OFFSET_DICT,
    AssetCategory,
    DataDiscriminator,
    Field,
    FieldValue,
    ReportOptions,
    TradeDetails,
)
from ibkr_report.trade import Trade


class Report:
    """Total selling prices, total capital gains, and total capital losses
    calculated from the CSV files.
    """

    prices: Decimal = Decimal(0)
    gains: Decimal = Decimal(0)
    losses: Decimal = Decimal(0)
    details: List[TradeDetails]
    options: Dict
    _trade: Optional[Trade] = None

    def __init__(
        self,
        file: Iterable[bytes] = None,
        report_currency: str = "EUR",
        use_deemed_acquisition_cost: bool = True,
    ) -> None:
        self.details = []
        self.options = {
            ReportOptions.REPORT_CURRENCY: report_currency,
            ReportOptions.DEEMED_ACQUISITION_COST: use_deemed_acquisition_cost,
            ReportOptions.OFFSET: 0,
        }
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file."""
        try:
            for items_list in csv.reader(iterdecode(file, "utf-8")):
                items = tuple(items_list)
                offset = _OFFSET_DICT.get(items)
                if offset is not None:
                    self.options[ReportOptions.OFFSET] = offset
                    self._trade = None
                    continue
                if self.is_stock_or_options_trade(items):
                    self._handle_trade(items)
        except UnicodeDecodeError as err:
            raise ValueError("Input data not in UTF-8 text format.") from err

    def is_stock_or_options_trade(self, items: Tuple[str, ...]) -> bool:
        """Checks whether the current row is part of a trade or not."""
        if (
            len(items) == _FIELD_COUNT + self.options[ReportOptions.OFFSET]
            and items[Field.TRADES] == FieldValue.TRADES
            and items[Field.HEADER] == FieldValue.HEADER
            and items[Field.DATA_DISCRIMINATOR]
            in (DataDiscriminator.TRADE, DataDiscriminator.CLOSED_LOT)
            and items[Field.ASSET_CATEGORY]
            in (AssetCategory.STOCKS, AssetCategory.OPTIONS)
        ):
            return True
        return False

    def _handle_trade(self, items: Tuple[str, ...]) -> None:
        """Parses prices, gains, and losses from trades."""
        if items[Field.DATA_DISCRIMINATOR] == DataDiscriminator.TRADE:
            self._trade = Trade(items, self.options)
            self.prices += self._trade.total_selling_price
        elif items[Field.DATA_DISCRIMINATOR] == DataDiscriminator.CLOSED_LOT:
            if not self._trade:
                raise ValueError("Tried to close a lot without trades.")
            details = self._trade.details_from_closed_lot(items)
            if details.realized > 0:
                self.gains += details.realized
            else:
                self.losses -= details.realized
            self.details.append(details)
