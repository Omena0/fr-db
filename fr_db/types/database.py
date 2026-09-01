from __future__ import annotations

from .table import Table


class Database:
    """A database containing named tables."""
    __slots__ = ('tables',)

    def __init__(self):
        self.tables: dict[str, Table] = {}
