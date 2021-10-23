# ibkr-report-parser

[![CI](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml/badge.svg)](https://github.com/oittaa/ibkr-report-parser/actions/workflows/main.yml)
[![codecov](https://codecov.io/gh/oittaa/ibkr-report-parser/branch/main/graph/badge.svg?token=BV211C3GE5)](https://codecov.io/gh/oittaa/ibkr-report-parser)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

## How to run locally

### 1. Clone the repository

```
git clone https://github.com/oittaa/ibkr-report-parser.git
cd ibkr-report-parser
```

### 2. a) Build and run the Docker container

```
docker build -t ibkr-report-parser:latest .
docker run --rm -d -p 8080:8080 --name ibkr-report-parser ibkr-report-parser
```

### 2. b) Or just run the Python app

```
pip3 install -r requirements.txt
python3 main.py
```

### 3. Use the app

Browse to http://127.0.0.1:8080/
