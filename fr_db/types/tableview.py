from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fr_db.types.column import Column
from fr_db.types.rowview import RowView
from fr_db.types.table import Table

if TYPE_CHECKING:
    from .index import Index
    from .operation import Operation
    from .row import Row


class TableView(Table):
    """View overlaying a delta on top of a base table.

    Avoids copying the entire table when only a few rows change.
    Reads delegate through a RowView that lazily merges changes on the base.
    """
    __slots__ = ('_base', '_columns_override', '_indexes_override', '_rows_data')

    def __init__(self, base: Table, rows: RowView | None = None, operations: list[Operation] | None = None):
        self.database = base.database
        self.name = base.name
        self._rows = base._rows  # pyright: ignore[reportIncompatibleVariableOverride]
        self._columns = base._columns  # pyright: ignore[reportIncompatibleVariableOverride]
        self.indexes = base.indexes  # pyright: ignore[reportIncompatibleVariableOverride]
        self._transaction = None
        self._in_transaction = False
        self.operations = operations if operations is not None else []
        self._default_columns = base._default_columns
        self._query_cache: dict[tuple[Any, ...], TableView] = {}

        self._base = base
        self._rows_data = rows
        self._columns_override = None
        self._indexes_override = None

    @property  # pyright: ignore[reportIncompatibleVariableOverride]
    def _rows(self) -> RowView | dict[int, Row]:
        if self._rows_data is None:
            self._rows_data = RowView(self._base._rows)
        return self._rows_data

    @_rows.setter
    def _rows(self, value: RowView | dict[int, Row]) -> None:
        self._rows_data = value

    @property
    def rows(self) -> RowView | dict[int, Row]:
        self._apply_ops()
        return self._rows

    @rows.setter
    def rows(self, value: RowView | dict[int, Row]) -> None:
        from ..errors import NoTransactionError
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.rows.')
        self._rows = value

    @property  # pyright: ignore[reportIncompatibleVariableOverride]
    def _columns(self) -> dict[str, Column[Any]]:
        if self._columns_override is not None:
            return self._columns_override
        return self._base._columns

    @_columns.setter
    def _columns(self, value: dict[str, Column[Any]]) -> None:
        self._columns_override = value

    @property
    def columns(self) -> dict[str, Column[Any]]:
        self._apply_ops()
        return self._columns

    @columns.setter
    def columns(self, value: dict[str, Column[Any]] | list[Column[Any]]) -> None:
        from ..errors import NoTransactionError
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.columns.')
        if type(value) is list:
            value = {col.name: col for col in value}
        self._columns = value  # pyright: ignore[reportIncompatibleVariableOverride, reportAttributeAccessIssue]

    @property  # pyright: ignore[reportIncompatibleVariableOverride]
    def indexes(self) -> dict[str, Index]:
        if self._indexes_override is not None:
            return self._indexes_override
        return self._base.indexes

    @indexes.setter
    def indexes(self, value: dict[str, Index]) -> None:
        self._indexes_override = value

    def _apply_ops_to_rows(self, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .operation import Operation
        for op in self.operations:
            if func := Operation.map.get(op.type):
                rows = func(op, self, rows)
            else:
                from ..errors import InvalidOperationType
                raise InvalidOperationType(f"Unknown operation type: {op.type}")
        return rows

    def _apply_ops(self) -> None:
        if not self.operations:
            return
        self._rows = self._apply_ops_to_rows(self._rows)  # pyright: ignore[reportIncompatibleVariableOverride]
        self.operations = []

    def clone(self) -> TableView:
        """Create a new TableView sharing the same base table and pending operations."""
        return TableView(self._base, None, self.operations.copy())

    def collapse(self) -> Table:
        """Materialize this view into an independent Table."""
        materialized = self._rows
        collapsed_rows = materialized.collapse() if isinstance(materialized, RowView) else dict(materialized)
        return Table(
            None,
            self._base.name,
            rows=collapsed_rows,
            columns=self._base._columns.values(),
            indexes=self._base.indexes.values(),
            _data_is_valid=True,
        )
