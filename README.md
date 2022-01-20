# ibkr-report-parser

[![Python versions supported](https://img.shields.io/pypi/pyversions/ibkr-report-parser.svg?logo=python)](https://pypi.org/project/ibkr-report-parser/)
[![PyPI status](https://badge.fury.io/py/ibkr-report-parser.svg)](https://pypi.org/project/ibkr-report-parser/)
[![CI](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml/badge.svg)](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/oittaa/ibkr-report-parser/branch/main/graph/badge.svg?token=BV211C3GE5)](https://codecov.io/gh/oittaa/ibkr-report-parser)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Interactive Brokers (IBKR) Report Parser for MyTax (vero.fi) - not affiliated with either service

## Example

![Example](https://user-images.githubusercontent.com/8972248/141529794-55226165-f844-405f-a251-a91b07701efa.png)

## How to run locally

### Option 1: pip
```shell
pip install ibkr-report-parser
ibkr-report-parser
```

### Option 2: Docker
````shell
docker pull ghcr.io/oittaa/ibkr-report-parser
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ghcr.io/oittaa/ibkr-report-parser
````

### Use the app

Browse to http://127.0.0.1:8080/

## Environment variables

* `TITLE` The title of the website. Default `IBKR Report Parser`
* `CURRENCY` The currency used in the report output. Default `EUR`
* `USE_DEEMED_ACQUISITION_COST` Whether to use the [deemed acquisition cost][selling shares], if it benefits you. Default `TRUE`
* `STORAGE_TYPE` The storage to save the fetched daily Euro exchange rates, if set to anything other than `DISABLED`. Currently supported types are `LOCAL`, `AWS`, and `GCP`. Default `DISABLED`
* `STORAGE_DIR` The directory used when `STORAGE_TYPE` is set to `LOCAL`. Default `.ibkr_storage`
* `BUCKET_ID` The storage bucket used when `STORAGE_TYPE` is set to `AWS` or `GCP`. Default `""`

### Testing and debugging
* `DEBUG` Flask debug. Default `FALSE`
* `LOGGING_LEVEL` Python logging level. Default `INFO`
* `EXCHANGE_RATES_URL` URL for the Euro exchange rates from European Central Bank. Default `https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip`

## How to build yourself

### Python
```shell
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
pip install .
ibkr-report-parser
```

### Docker
```shell
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
docker build -t ibkr-report-parser:latest .
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ibkr-report-parser
```

## Python API

```python
from ibkr_report import Report

FILE_1 = "tests/test-data/data_single_account.csv"
FILE_2 = "tests/test-data/data_multi_account.csv"

with open(FILE_1, "rb") as file:
    report = Report(file=file, report_currency="EUR", use_deemed_acquisition_cost=True)

with open(FILE_2, "rb") as file:
    report.add_trades(file=file)

print(f"Total selling prices: {report.prices}")
print(f"Total capital gains: {report.gains}")
print(f"Total capital losses: {report.losses}")

for item in report.details:
    print(
        f"{item.symbol=}, {item.quantity=}, {item.buy_date=}, "
        f"{item.sell_date=}, {item.price=}, {item.realized=}"
    )

```

```python
from ibkr_report import ExchangeRates, StorageType

rates = ExchangeRates(storage_type=StorageType.LOCAL, storage_dir="/tmp/my_storage")
print(rates.get_rate("EUR", "USD", "2020-06-20"))
print(rates.get_rate("GBP", "SEK", "2015-12-31"))
```

[selling shares]: https://www.vero.fi/en/individuals/property/investments/selling-shares/
