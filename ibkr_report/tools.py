import logging
import re
from base64 import b64encode
from datetime import date, datetime
from decimal import Decimal
from flask import current_app
from hashlib import sha384
from typing import Dict

from ibkr_report.definitions import _DATE_STR_FORMATS, LOGGING_LEVEL

_cache: Dict = {}
_MAXCACHE = 10


class Cache:
    @staticmethod
    def get(key):
        if key in _cache:
            return _cache[key]
        return None

    @staticmethod
    def set(key, value):
        if key not in _cache and len(_cache) >= _MAXCACHE:
            try:
                del _cache[next(iter(_cache))]
            except (StopIteration, RuntimeError, KeyError):
                pass
        _cache[key] = value

    @staticmethod
    def clear():
        _cache.clear()


def get_date(date_str: str) -> date:
    """Converts a string formatted date to a date object."""
    for date_format in _DATE_STR_FORMATS:
        try:
            return datetime.strptime(date_str, date_format).date()
        except ValueError:
            pass
    raise ValueError("Invalid date '{}'".format(date_str))


def add_years(d: date, years: int) -> date:
    """Return a date that's `years` years after the date (or datetime)
    object `d`. Return the same calendar date (month and day) in the
    destination year, if it exists, otherwise use the previous day
    (thus changing February 29 to February 28).
    """
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d + (date(d.year + years, 3, 1) - date(d.year, 3, 1))


def date_without_time(date_str: str) -> str:
    return re.sub(r"(\d\d\d\d-\d\d-\d\d),? ([0-9:]+)", r"\1", date_str)


def decimal_cleanup(number_str: str) -> Decimal:
    return Decimal(re.sub(r"[,\s]+", "", number_str))


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def get_sri(files: Dict[str, str] = {}) -> Dict[str, str]:
    """Calculate Subresource Integrity for CSS and Javascript files.
    input: {'style.css': 'static/style.css', 'main.js': 'static/main.js', ...}
    output: {'style.css': 'sha384-...', 'main.js': 'sha384-...', ...}
    """
    sri = Cache.get("sri")
    if not sri:
        sri = {}
        for key, file_path in files.items():
            sri[key] = calculate_sri_on_file(file_path)
        Cache.set("sri", sri)
    return sri


def calculate_sri_on_file(filename: str) -> str:
    """Calculate Subresource Integrity string."""
    hash_digest = hash_sum(filename, sha384()).digest()
    hash_base64 = b64encode(hash_digest).decode()
    return "sha384-{}".format(hash_base64)


def hash_sum(filename, hash_func):
    """Compute message digest from a file."""
    byte_array = bytearray(128 * 1024)
    memory_view = memoryview(byte_array)
    with open(filename, "rb", buffering=0) as file:
        for block in iter(lambda: file.readinto(memory_view), 0):
            hash_func.update(memory_view[:block])
    return hash_func


def set_logging() -> None:
    if LOGGING_LEVEL.upper() in logging._nameToLevel.keys():
        current_app.logger.setLevel(logging._nameToLevel[LOGGING_LEVEL.upper()])
    else:
        current_app.logger.setLevel(logging.WARNING)
