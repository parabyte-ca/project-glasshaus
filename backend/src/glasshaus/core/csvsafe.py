"""CSV for spreadsheets: every text cell that a spreadsheet would run as a formula is neutralised.

Done in one place, for every cell and header, so a tag, a status name, a person's name or a report
label typed as ``=HYPERLINK(...)`` cannot slip through a column someone forgot.
"""

import csv
from collections.abc import Iterable
from typing import Any, TextIO

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def safe(value: str) -> str:
    return "'" + value if value[:1] in _TRIGGERS else value


class Writer:
    def __init__(self, out: TextIO) -> None:
        self._w = csv.writer(out)

    def writerow(self, row: Iterable[Any]) -> None:
        self._w.writerow([safe(v) if isinstance(v, str) else v for v in row])


def writer(out: TextIO) -> Writer:
    return Writer(out)
