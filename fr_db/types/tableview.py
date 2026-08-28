from __future__ import annotations
from typing import TYPE_CHECKING, Any

from fr_db.types.column import Column

if TYPE_CHECKING:
    from .operation import Operation
    from .rowview import RowView
    from .table import Table


class TableView:
    """View overlaying a delta on top of a base table.

    Avoids copying the entire table when only a few rows change.
    Reads check _rows (a RowView) which overlays changes on the base table's rows.
    """
    __slots__ = ('_base', '_rows')

    def __init__(self, base: Table, rows: RowView):
        self._base = base
        self._rows = rows

    @property
    def rows(self) -> RowView:
        return self._rows

    @property
    def operations(self) -> list[Operation]:
        return []

    @property
    def indexes(self):
        return self._base.indexes

    @property
    def _columns(self) -> dict[str, Column[Any]]:
        return self._base._columns # pyright: ignore[reportPrivateUsage]

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
