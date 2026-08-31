from __future__ import annotations
from typing import TYPE_CHECKING, Any

from fr_db.types.column import Column

if TYPE_CHECKING:
    from .operation import Operation
    from .rowview import RowView
    from .table import Table

_MISSING = object()

class TableView:
    """View overlaying a delta on top of a base table.

    Avoids copying the entire table when only a few rows change.
    Reads check _rows (a RowView) which overlays changes on the base table's rows.
    """
    __slots__ = ('_base', '_rows_data', '_operations', '_columns_override', '_indexes_override')

    def __init__(self, base: Table, rows: RowView | None = None, operations: list[Operation] | None = None):
        self._base = base
        # Store base rows reference for lazy RowView creation
        self._rows_data = rows  # Can be None, created lazily on access
        self._operations = operations if operations is not None else []
        self._columns_override = None
        self._indexes_override = None

    @property
    def _rows(self) -> RowView | dict[int, Any]:
        """Lazily create RowView on first access."""
        if self._rows_data is None:
            from .rowview import RowView
            self._rows_data = RowView(self._base._rows)  # pyright: ignore[reportPrivateUsage]
        return self._rows_data

    @_rows.setter
    def _rows(self, value: RowView | dict[int, Any]):
        self._rows_data = value

    @property
    def rows(self) -> RowView | dict[int, Any]:
        self._apply_ops()
        return self._rows

    @property
    def operations(self) -> list[Operation]:
        return self._operations

    @operations.setter
    def operations(self, value: list[Operation]):
        self._operations = value

    @property
    def indexes(self):
        if self._indexes_override is not None:
            return self._indexes_override
        return self._base.indexes

    @indexes.setter
    def indexes(self, value):
        self._indexes_override = value

    @property
    def _columns(self) -> dict[str, Column[Any]]:
        if self._columns_override is not None:
            return self._columns_override
        return self._base._columns # pyright: ignore[reportPrivateUsage]

    @_columns.setter
    def _columns(self, value):
        self._columns_override = value

    @property
    def columns(self) -> dict[str, Column[Any]]:
        self._apply_ops()
        return self._columns

    @property
    def _rows_dict(self) -> dict[int, Any]:
        """Access the base table's _rows for internal use."""
        return self._base._rows  # pyright: ignore[reportPrivateUsage]

    def _apply_ops_to_rows(self, rows: dict[int, Any]) -> dict[int, Any]:
        """Apply operations to rows without modifying the base table."""
        from .operation import Operation
        for op in self._operations:
            if func := Operation.map.get(op.type):
                rows = func(op, self, rows)
            else:
                from ..errors import InvalidOperationType
                raise InvalidOperationType(f"Unknown operation type: {op.type}")
        return rows

    def _apply_ops(self):
        """Apply operations and update the RowView."""
        if not self._operations:
            return
        # Apply operations to the RowView (changes go into delta, no full copy)
        self._rows = self._apply_ops_to_rows(self._rows)
        self._operations = []

    def clone(self) -> TableView:
        """Create a new TableView sharing the same base table."""
        return TableView(self._base, None, self._operations.copy())

    def where(self, column, key=_MISSING):
        from .operation import Operation, OpType
        t = self.clone()
        if key is _MISSING:
            t._operations.append(Operation(OpType.WHERE, column))
        else:
            t._operations.append(Operation(OpType.WHERE, column, key))
        return t

    def transform(self, *keys):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.TRANSFORM, *keys))
        return t

    def transform_rows(self, keys, func):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.TRANSFORM_ROWS, keys, func))
        return t

    def select(self, *columns):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.SELECT, *columns))
        return t

    def limit(self, count):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.LIMIT, count))
        return t

    def sort(self, key, reverse=False):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.SORT, key, reverse))
        return t

    def distinct(self, *columns):
        from .operation import Operation, OpType
        t = self.clone()
        t._operations.append(Operation(OpType.DISTINCT, *columns))
        return t

    def collapse(self) -> Table:
        """Convert this view to an actual Table object.

        This materializes all lazy operations and returns a concrete Table.
        Use this when you need an actual Table (e.g., for indexing, validation).
        """
        from .table import Table
        collapsed_rows = self._rows.collapse()
        return Table(
            None,
            self._base.name,
            rows=collapsed_rows,
            columns=self._base._columns.values(),
            indexes=self._base.indexes.values(),
            _data_is_valid=True,
        )

    def __getattr__(self, name: str):
        return getattr(self._base, name)
