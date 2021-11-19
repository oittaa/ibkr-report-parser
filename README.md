# ibkr-report-parser

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

### Option 3: Build yourself

#### Python
```shell
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
pip install -r requirements.txt
python main.py
```

#### Docker
```shell
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
docker build -t ibkr-report-parser:latest .
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ibkr-report-parser
```

### Use the app

Browse to http://127.0.0.1:8080/

## Python API

```python
from ibkr_report import Report

FILE_1 = "test-data/data_single_account.csv"
FILE_2 = "test-data/data_multi_account.csv"

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
from ibkr_report import ExchangeRates

rates = ExchangeRates()
print(rates.get_rate("EUR", "USD", "2020-06-20"))
print(rates.get_rate("GBP", "SEK", "2015-12-31"))
```
