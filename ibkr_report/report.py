"""
Total selling prices, total capital gains, and total capital losses calculated
from the CSV files.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable, List, Optional, Sequence, Tuple

from ibkr_report.csv_events import RawRow, parse_events, read_csv_rows
from ibkr_report.definitions import (
    CURRENCY,
    USE_DEEMED_ACQUISITION_COST,
    Disposal,
    ReportConfig,
    ReportResult,
    Totals,
)
from ibkr_report.exchangerates import ExchangeRates
from ibkr_report.matching import filter_latest_year, match_disposals

log = logging.getLogger(__name__)


def build_report_result(
    row_buffers: Sequence[Sequence[RawRow]],
    config: ReportConfig,
    rates: ExchangeRates,
    file_count: int,
) -> ReportResult:
    """Run the full pipeline once over all buffered CSV rows."""
    rows: List[RawRow] = [row for buf in row_buffers for row in buf]
    events = parse_events(rows)
    disposals = match_disposals(events, config, rates)
    year, kept = filter_latest_year(disposals)
    totals = Totals.from_disposals(kept)
    log.debug(
        "Report year %s from %d file(s); %d disposal row(s)",
        year,
        file_count,
        len(kept),
    )
    return ReportResult(
        year=year,
        file_count=file_count,
        totals=totals,
        disposals=tuple(kept),
        config=config,
    )


class Report:
    """Total selling prices, total capital gains, and total capital losses
    calculated from the CSV files.

    When calculating the amount of profit or loss, you can deduct the deemed
    acquisition cost from the selling price of the shares, instead of deducting
    the purchase price of the shares as well as the expenses incurred in
    making a profit.

    Multiple CSV files may be added (e.g. several tax years). After processing,
    only disposals from the latest calendar year present in the data are kept
    (by close date: sell for longs, cover for shorts), so earlier-year option
    premiums and short opens can still adjust a later-year close while the
    MyTax totals reflect a single year.

    Args:
        file: The input file in CSV format.
        report_currency: The currency used in the output.
        use_deemed_acquisition_cost: Whether to use the deemed acquisition cost
            if it benefits you.

    Attributes:
        proceeds: Total selling prices.
        gains: Total capital gains.
        losses: Total capital losses.
        disposals: Per-lot disposal details.
        config: Report currency and deemed-acquisition-cost flag.
        rates: Euro foreign exchange rates.
        report_year: Calendar year of disposals in the report.
        file_count: Number of CSV files added.
    """

    config: ReportConfig
    rates: ExchangeRates
    _buffers: List[List[RawRow]]
    _result: Optional[ReportResult]

    def __init__(
        self,
        file: Optional[Iterable[bytes]] = None,
        report_currency: str = CURRENCY,
        use_deemed_acquisition_cost: bool = USE_DEEMED_ACQUISITION_COST,
    ) -> None:
        self.config = ReportConfig(
            report_currency=report_currency.upper(),
            use_deemed_acquisition_cost=use_deemed_acquisition_cost,
        )
        self.rates = ExchangeRates()
        self._buffers = []
        self._result = None
        if file:
            self.add_trades(file)

    def add_trades(self, file: Iterable[bytes]) -> None:
        """Adds trades from a CSV formatted report file.

        Rows are buffered so multiple files can be combined in any order (e.g.
        a 2024 statement uploaded before 2023) and premiums still match.
        Pipeline runs once when results are first read (lazy single pass).
        """
        self._buffers.append(read_csv_rows(file))
        self._result = None

    def result(self) -> ReportResult:
        """Compute (or return cached) report outcome for all buffered files."""
        if self._result is None:
            self._result = build_report_result(
                self._buffers,
                self.config,
                self.rates,
                file_count=len(self._buffers),
            )
        return self._result

    @property
    def file_count(self) -> int:
        """Number of CSV files added."""
        return len(self._buffers)

    @property
    def report_year(self) -> Optional[int]:
        """Calendar year of disposals kept in the report."""
        return self.result().year

    @property
    def proceeds(self) -> Decimal:
        """Total selling prices in report currency."""
        return self.result().totals.proceeds

    @property
    def gains(self) -> Decimal:
        """Total capital gains in report currency."""
        return self.result().totals.gains

    @property
    def losses(self) -> Decimal:
        """Total capital losses in report currency (positive magnitude)."""
        return self.result().totals.losses

    @property
    def disposals(self) -> Tuple[Disposal, ...]:
        """Per-lot disposal rows for the report year."""
        return self.result().disposals
