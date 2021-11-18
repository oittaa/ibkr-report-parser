"""Tools and utility functions."""

import logging
import os
import re
from base64 import b64encode
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha384
from typing import Any, Dict

from flask import current_app

from ibkr_report.definitions import _DATE_STR_FORMATS, LOGGING_LEVEL

_cache: Dict = {}
_MAXCACHE = 10


class Cache:
    """Simple cache in memory"""

    @staticmethod
    def get(key: Any) -> Any:
        """Get value from cache, None if not found"""
        if key in _cache:
            return _cache[key]
        return None

    @staticmethod
    def set(key: Any, value: Any) -> None:
        """Set value into cache"""
        if key not in _cache and len(_cache) >= _MAXCACHE:
            try:
                del _cache[next(iter(_cache))]
            except (StopIteration, RuntimeError, KeyError):
                pass
        _cache[key] = value

    @staticmethod
    def clear() -> None:
        """Clear cache"""
        _cache.clear()


def get_date(date_str: str) -> date:
    """Converts a string formatted date to a date object."""
    for date_format in _DATE_STR_FORMATS:
        try:
            return datetime.strptime(date_str, date_format).date()
        except ValueError:
            pass
    raise ValueError(f"Invalid date '{date_str}'")


def add_years(d_obj: date, years: int) -> date:
    """Return a date that's `years` years after the date (or datetime)
    object `d_obj`. Return the same calendar date (month and day) in the
    destination year, if it exists, otherwise use the previous day
    (thus changing February 29 to February 28).
    """
    try:
        return d_obj.replace(year=d_obj.year + years)
    except ValueError:
        return d_obj + (date(d_obj.year + years, 3, 1) - date(d_obj.year, 3, 1))


def date_without_time(date_str: str) -> str:
    """Strips away hours, minutes, and seconds from a string."""
    return re.sub(r"(\d\d\d\d-\d\d-\d\d),? ([0-9:]+)", r"\1", date_str)


def decimal_cleanup(number_str: str) -> Decimal:
    """Converts a string to a decimal while ignoring spaces and commas."""
    return Decimal(re.sub(r"[,\s]+", "", number_str))


def is_number(number_str: str) -> bool:
    """Checks if a string can be converted into a number"""
    try:
        float(number_str)
        return True
    except ValueError:
        return False


def calculate_sri_on_file(filename: str) -> str:
    """Calculate Subresource Integrity string."""
    hash_digest = hash_sum(filename, sha384()).digest()
    hash_base64 = b64encode(hash_digest).decode()
    return f"sha384-{hash_base64}"


# TODO: mypy 0.910 "BinaryIO" has no attribute "readinto"
def hash_sum(filename, hash_func):
    """Compute message digest from a file."""
    byte_array = bytearray(128 * 1024)
    memory_view = memoryview(byte_array)
    with open(filename, "rb", buffering=0) as file:
        for block in iter(lambda: file.readinto(memory_view), 0):
            hash_func.update(memory_view[:block])
    return hash_func


def set_logging() -> None:
    """Set logging level according to the ENV variable LOGGING_LEVEL."""
    if not current_app.debug:
        level = logging.getLevelName(LOGGING_LEVEL.upper())
        if isinstance(level, int):
            current_app.logger.setLevel(level)
        else:
            current_app.logger.setLevel(logging.WARNING)
    log_level = logging.getLevelName(current_app.logger.level)
    current_app.logger.debug(f"Logging level: {log_level}")


def sri(files: Dict[str, str]) -> Dict[str, str]:
    """Calculate Subresource Integrity for CSS and Javascript files.

    input: {'style.css': 'static/style.css', 'main.js': 'static/main.js', ...}
    output: {'style.css': 'sha384-...', 'main.js': 'sha384-...', ...}
    """
    cache_key = tuple(sorted(files.items()))
    sri_dict = Cache.get(cache_key)
    if not sri_dict:
        sri_dict = {}
        for key, file_path in files.items():
            sri_dict[key] = calculate_sri_on_file(file_path)
        Cache.set(cache_key, sri_dict)
    return sri_dict


def _sri() -> Dict[str, str]:
    return sri(
        {
            "main.css": os.path.join(
                current_app.root_path, "static", "css", "main.css"
            ),
            "main.js": os.path.join(current_app.root_path, "static", "js", "main.js"),
        }
    )
