# ibkr-report-parser

[![CI](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml/badge.svg)](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/oittaa/ibkr-report-parser/branch/main/graph/badge.svg?token=BV211C3GE5)](https://codecov.io/gh/oittaa/ibkr-report-parser)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

Interactive Brokers (IBKR) Report Parser for MyTax (vero.fi)

## Example

![Example](https://user-images.githubusercontent.com/8972248/141529794-55226165-f844-405f-a251-a91b07701efa.png)

## How to run locally

### Option 1: pip
```
pip install ibkr-report-parser
ibkr-report-parser
```

### Option 2: Docker
````
docker pull ghcr.io/oittaa/ibkr-report-parser
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ibkr-report-parser
````

### Option 3: Build yourself

#### Python
```
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
pip install -r requirements.txt
python main.py
```

#### Docker
```
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
docker build -t ibkr-report-parser:latest .
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ibkr-report-parser
```

### Use the app

Browse to http://127.0.0.1:8080/
