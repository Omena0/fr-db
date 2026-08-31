from ..errors import NotInATransactionError
from .table import Table
from typing import Self


class Transaction(Table):
    __slots__ = ['_table', '_active', 'aborted', '_catch_exc', '_in_transaction']

    def __init__(self, table: Table, catch_exc: bool = False):
        super().__init__(None, "Transaction")

        self._table    = table
        self._active  = False
        self.aborted = False
        self._catch_exc = catch_exc

    def __enter__(self) -> Self:
        self._in_transaction = True
        self.rclone(self._table)
        self._active = True
        self.aborted = False

        return self

    def __exit__(self, _exc_type, _exc_val, _exc_traceback): # type: ignore
        if not self._active:
            raise NotInATransactionError('Not in a transaction. __enter__ first.')

        if _exc_type:
            self.abort()

        # Only apply ops on success
        # If validation fails, abort.
        if not self.aborted:
            try:
                self._apply_ops()
                self._table._validate_data()

            except Exception as e:
                self.aborted = True
                if not self._catch_exc:
                    raise e

            else:
                self._table.rclone(self)

        self._active = False
        self._table._transaction = None

        return self._catch_exc

    def abort(self):
        self.aborted = True

    def clone(self) -> Table:
        from .tableview import TableView
        return TableView(self)
