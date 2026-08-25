from ..errors import NotInATransactionError
from .table import Table
from typing import Self


class Transaction(Table):
    def __init__(self, table: Table, catch_exc: bool = False):
        super().__init__(None, "Transaction")

        self._table    = table
        self._active  = False
        self._aborted = False
        self._catch_exc = catch_exc

    def __enter__(self) -> Self:
        self.rcopy(self._table)
        self._active = True
        self._aborted = False

        return self

    def __exit__(self, _exc_type, _exc_val, _exc_traceback): # type: ignore
        if not self._active:
            raise NotInATransactionError('Not in a transaction. __enter__ first.')

        if _exc_type:
            self.abort()

        if not self._aborted:
            self._table.rcopy(self)

        self._active = False
        self._table._transaction = None

        return self._catch_exc

    def abort(self):
        self._aborted = True
