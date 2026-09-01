from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .table import Table
    from .row import Row


class Index:
    """
        Index for fast lookups on a column.
        Supports unique constraints and lazy rebuilding.
    """
    __slots__ = ('column', 'unique', '_values', '_shared', '_dirty', '_table')

    def __init__(self, column: str, unique: bool = False):
        """Initialize an index on the given column.
            :param column: The column name to index
            :type column: str
            :param unique: Whether the index enforces uniqueness
            :type unique: bool
        """
        self.column = column
        self.unique = unique
        self._values: dict[Any, set[int]] = {}
        self._shared = False
        self._dirty = False
        self._table: Table | None = None

    def __repr__(self) -> str:
        self._ensure_built()
        return f'Index({self.column}, {self._values})'

    # Internal
    def _ensure_built(self):
        """Lazy rebuild index if dirty.\n
            :raises ValueError: If a duplicate value is found in a unique index
        """
        if not self._dirty:
            return

        self._dirty = False
        self._values.clear()
        self._shared = False

        table = self._table

        if table is None:
            return

        for row_id, row in table._rows.items(): # pyright: ignore[reportPrivateUsage]
            value = row.values[self.column]
            ids = self._values.get(value)

            if self.unique and ids:
                raise ValueError(
                    f"Duplicate value {value!r} "
                    f"in unique index {self.column!r}"
                )

            if ids is None:
                self._values[value] = {row_id}

            else:
                ids.add(row_id)

    def _mark_dirty(self):
        """Mark index as needing rebuild."""
        self._dirty = True

    # Properties
    @property
    def values(self) -> dict[Any, set[int]]:
        """Access index values, rebuilding if dirty.\n
            :return: Index value to row IDs mapping
            :rtype: dict[Any, set[int]]
        """
        self._ensure_built()
        return self._values

    # Index operations
    def add(self, row: Row):
        """Add a row to the index.\n
            :param row: The row to add
            :type row: Row
            :raises ValueError: If a duplicate value is found in a unique index
        """
        self._ensure_built()

        value = row.values[self.column]
        ids = self._values.get(value)

        if self.unique and ids:
            raise ValueError(
                f"Duplicate value {value!r} "
                f"for unique index {self.column!r}"
            )

        if ids is None:
            self._values[value] = {row.id}

        elif self._shared:
            ids = ids.copy()
            ids.add(row.id)
            self._values[value] = ids

        else:
            ids.add(row.id)

    def remove(self, row: Row):
        """Remove a row from the index.\n
            :param row: The row to remove
            :type row: Row
        """
        self._ensure_built()

        value = row.values[self.column]
        ids = self._values.get(value)

        if ids is None or row.id not in ids:
            return

        if self._shared:
            # Copy-on-write
            ids = ids.copy()
            ids.remove(row.id)

            if ids:
                self._values[value] = ids

            else:
                del self._values[value]

        else:
            ids.remove(row.id)
            if not ids:
                del self._values[value]

    def update(self, old_value: Any, new_value: Any, row_id: int):
        """Update a value in the index.\n
            :param old_value: The previous value
            :type old_value: Any
            :param new_value: The new value
            :type new_value: Any
            :param row_id: The row ID to update
            :type row_id: int
            :raises ValueError: If a duplicate value is found in a unique index
        """
        if old_value == new_value:
            return

        self._ensure_built()

        new_ids = self._values.get(new_value)

        if self.unique and new_ids and new_ids != {row_id}:
            raise ValueError(
                f"Duplicate value {new_value!r} "
                f"for unique index {self.column!r}"
            )

        old_ids = self._values.get(old_value)

        if old_ids is not None:
            if self._shared:
                # Copy-on-write
                old_ids = old_ids.copy()
                old_ids.discard(row_id)

                if old_ids:
                    self._values[old_value] = old_ids

                else:
                    del self._values[old_value]

            else:
                old_ids.discard(row_id)

                if not old_ids:
                    del self._values[old_value]

        new_ids = self._values.get(new_value)

        if new_ids is None:
            self._values[new_value] = {row_id}

        elif self._shared:
            new_ids = new_ids.copy()
            new_ids.add(row_id)
            self._values[new_value] = new_ids

        else:
            new_ids.add(row_id)

    # Lifecycle
    def build(self, table: Table):
        """Build the index for a table.\n
            :param table: The table to index
            :type table: Table
        """
        self._table = table
        self._dirty = True
        self._ensure_built()

    def copy(self, table: Table) -> Index:
        """Create a copy of this index for a new table.\n
            :param table: The table for the copied index
            :type table: Table
            :return: A new index instance
            :rtype: Index
        """
        self._ensure_built()
        index = Index(self.column, self.unique)
        index._values = {
            value: ids.copy()
            for value, ids in self._values.items()
        }
        return index

    def clone(self) -> Index:
        """Clone index, preserving dirty state.\n
            :return: A new index sharing the same underlying data
            :rtype: Index
        """
        index = Index(self.column, self.unique)
        index._values = self._values
        index._shared = True
        index._dirty = self._dirty
        index._table = self._table

        return index


