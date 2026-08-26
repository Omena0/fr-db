from collections.abc import Iterable, Callable
from typing import TYPE_CHECKING, Any, cast

from ..errors import NoTransactionError, TableAlreadyExistsError, InATransactionError
from ..display import display_table
from .operation import Operation

if TYPE_CHECKING:
    from .transaction import Transaction
    from .database import Database
    from .column import Column
    from .index import Index
    from .row import Row

_MISSING = object()

def _to_dict[K,T](
    value: dict[K, T] | Iterable[T],
    key: Callable[[T], K],
) -> dict[K, T]:
    if isinstance(value, dict):
        return cast(dict[K, T], value)

    return {key(item): item for item in value}

class Table:
    __slots__ = ['database', 'name', '_rows', '_columns', 'indexes', '_transaction', 'operations']
    def __init__(
            self,
            database: Database | None,
            name: str,
            rows: dict[int, Row] | Iterable[Row] = {},
            columns: dict[str, Column[Any]] | Iterable[Column[Any]] = {},
            indexes: dict[str, Index] | Iterable[Index] = {},
            operations: list[Operation] = [],
            _data_is_valid: bool = False
        ):
        self.database = database
        self.name = name

        self._rows: dict[int, Row] = _to_dict(rows, lambda row: row.id)
        self._columns: dict[str, Column[Any]] = _to_dict(columns, lambda column: column.name)
        self.indexes: dict[str, Index] = _to_dict(indexes, lambda index: index.column)

        self._transaction = None

        self.operations: list[Operation] = operations

        if not _data_is_valid:
            self._check_data()

    def _check_data(self):
        for row in self.rows.values():
            if row.table != self:
                row.table = self
                row._deferred_init() # pyright: ignore[reportPrivateUsage]

        for row in self.rows.values():
            row._check_values() # pyright: ignore[reportPrivateUsage]

        for col in self.columns.values():
            if col.table != self:
                col.table = self

        if self.database and self not in self.database.tables:
            if self.name in self.database.tables:
                raise TableAlreadyExistsError(f'Table {self.name} already exists.')

            self.database.tables[self.name] = self

        for idx in self.indexes.values():
            idx.build(self)

    def __str__(self) -> str:
        return display_table(self, width=100, sort=False)

    def __repr__(self) -> str:
        return f'Table({self.name}, ...)'

    def _apply_ops(self):
        if not self.operations:
            return

        for op in self.operations:
            op.apply(self)

        self.operations.clear()

    @property
    def rows(self) -> dict[int, Row]:
        if self._transaction:
            raise InATransactionError(f'You cannot access {self.name}.rows while in a transaction. Use tx.rows.')

        self._apply_ops()
        return self._rows

    @rows.setter
    def rows(self, value: dict[int, Row]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transacion.rows.')

        self._rows = value

    @property
    def columns(self) -> dict[str, Column[Any]]:
        if self._transaction:
            raise InATransactionError(f'You cannot access {self.name}.columns while in a transaction. Use tx.columns.')

        self._apply_ops()
        return self._columns

    @columns.setter
    def columns(self, value: dict[str, Column[Any]] | list[Column[Any]]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.columns.')

        if isinstance(value, list):
            value = {col.name: col for col in value}

        self._columns = value

    # Auto-indexed lookups
    def get_index(self, column: str) -> Index | None:
        """Return the index associated with a column, or None if no index exists.

        Used by lookup helpers to determine whether an indexed lookup is
        available for the requested column.
        """
        return self.indexes.get(column)

    def lookup(self, column: str, value: Any) -> set[int]:
        """Return all row IDs whose column has the given value.

        This is the general-purpose equality lookup operation and should be used
        by other table operations instead of implementing index checks themselves.
        """
        if idx := self.get_index(column):
            return idx.values[value]

        return {
            id for id, row in self._rows.items()
            if row.values[column] == value
        }

    def lookup_one(self, column: str, value: Any) -> int | None:
        """Return first row whose column has the given value, or None.

        This is primarily useful for unique columns/indexes where at most one row
        is expected to match.
        """
        if idx := self.get_index(column):
            return next(iter(idx.values[value]), None)

        for id, row in self._rows.items():
            if row.values[column] == value:
                return id

    def lookup_many(self, column: str, values: Iterable[Any]) -> list[int]:
        """Return all rows whose column value is contained in values."""
        matching: list[int] = []

        for value in values:
            matching.extend(self.lookup(column, value))

        return matching

    def contains(self, column: str, value: Any) -> bool:
        """Return whether at least one row has the given value in a column."""
        if idx := self.get_index(column):
            return bool(idx.values.get(value))

        return any(row.values[column] == value for row in self._rows.values())

    # Sync indexes
    def _sync_indexes(
        self,
        old_rows: dict[int, Row],
        new_rows: dict[int, Row],
    ):
        for column, index in self.indexes.items():
            old_ids = old_rows.keys()
            new_ids = new_rows.keys()

            # Rows that disappeared.
            for id in old_ids - new_ids:
                index.remove(old_rows[id])

            # Rows that were added.
            for id in new_ids - old_ids:
                index.add(new_rows[id])

            # Rows that still exist but may have changed indexed values.
            for id in old_ids & new_ids:
                old_value = old_rows[id].values[column]
                new_value = new_rows[id].values[column]

                if old_value != new_value:
                    index.update(old_value, new_value, id)

    # Querying
    def where(self, column: str | Callable[[Row], bool], key: Any = _MISSING) -> Table:
        t = self.clone()

        if key is _MISSING:
            assert callable(column)
            op = Operation("where", column)
        else:
            assert isinstance(column, str)
            op = Operation("where", column, key)

        t.operations.append(op)
        return t

    def transform(self, *keys: Callable[[Row], Row]) -> Table:
        t = self.clone()
        t.operations.append(Operation("transform", *keys))
        return t

    def select(self, *columns: str) -> Table:
        t = self.clone()
        t.operations.append(Operation("select", *columns))
        return t

    def limit(self, count: int) -> Table:
        t = self.clone()
        t.operations.append(Operation("limit", count))
        return t

    def sort(
        self,
        key: Callable[[Row], Any],
        reverse: bool = False,
    ) -> Table:
        t = self.clone()
        t.operations.append(Operation("sort", key, reverse))
        return t

    def distinct(self, *columns: str) -> Table:
        t = self.clone()
        t.operations.append(Operation("distinct", *columns))
        return t

    # Mutation
    def transaction(self, catch_exc: bool = False) -> Transaction:
        from .transaction import Transaction
        if not self._transaction:
            self._transaction = Transaction(self, catch_exc)

        return self._transaction

    def add(self, row: Row):
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        if row.table != self:
            row.table = self
            row._deferred_init()  # pyright: ignore[reportPrivateUsage]

        row._check_values()  # pyright: ignore[reportPrivateUsage]

        self._rows[row.id] = row

        for index in self.indexes.values():
            index.add(row)

    def update(self, table: Table):
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        source_rows = table.rows

        for source_id, source in source_rows.items():
            current = self._rows.get(source_id)

            if current is None:
                continue

            old_indexed_values = {
                column: current.values[column]
                for column in self.indexes
            }

            current.values.update(source.values)

            current._check_values( # pyright: ignore[reportPrivateUsage]
                self._rows.values(),
                exclude=[current],
            )

            for column, old_value in old_indexed_values.items():
                new_value = current.values[column]

                if old_value != new_value:
                    self.indexes[column].update(
                        old_value,
                        new_value,
                        current.id,
                    )

    def delete(self, key: Callable[[Row], bool]):
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        to_delete = {
            id
            for id, row in self._rows.items()
            if key(row)
        }

        for id in to_delete:
            row = self._rows.pop(id)

            for index in self.indexes.values():
                index.remove(row)

    # Copying
    def copy(self) -> Table:
        """Return an independent copy of this table."""
        table = Table(
            None,
            self.name,
            rows=[],
            columns=[],
            indexes=[],
            operations=self.operations.copy(),
            _data_is_valid=True
        )

        table._columns = {
            name: col.copy(table)
            for name, col in self._columns.items()
        }

        table._rows = {
            id: row.copy(table)
            for id, row in self._rows.items()
        }

        table.indexes = {
            name: index.copy(table)
            for name, index in self.indexes.items()
        }

        return table

    def rcopy(self, table: Table):
        self._rows = {
            id: row.copy(self)
            for id, row in table._rows.items()
        }

        self._columns = {
            name: col.copy(self)
            for name, col in table._columns.items()
        }

        self.indexes = {
            name: index.copy(self)
            for name, index in table.indexes.items()
        }

        self.operations = table.operations.copy()

    def clone(self) -> Table:
        """Clone the table, but not the values."""
        return Table(
            None,
            self.name,
            self._rows,
            self._columns,
            indexes=self.indexes,
            operations=self.operations.copy(),
            _data_is_valid=True,
        )

    def rclone(self, table: Table):
        self._rows = table._rows.copy()
        self._columns = table._columns.copy()
        self.operations = table.operations.copy()

        self.indexes = {
            name: index.copy(self)
            for name, index in table.indexes.items()
        }

