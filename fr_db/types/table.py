from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast, overload
from collections.abc import Callable, Iterable

from .operation import Operation, OpType
from ..display import display_table
from ..errors import (
    TableAlreadyExistsError,
    InvalidOperationType,
    InATransactionError,
    NoTransactionError,
    TypeMismatchError
)

if TYPE_CHECKING:
    from .database import Database
    from .tableview import TableView
    from .column import Column
    from .index import Index
    from .row import Row
    from .transaction import Transaction

_MISSING = object()


def _to_dict[K,T](
    value: dict[K, T] | Iterable[T],
    key: Callable[[T], K],
) -> dict[K, T]:
    if type(value) is dict:
        return cast(dict[K, T], value)

    value = cast(Iterable[T], value)

    return {key(item): item for item in value}


class Table:
    """A relational table with columns, rows, indexes, and operations."""
    __slots__ = (
        'database',
        'name',
        '_rows',
        '_columns',
        'indexes',
        '_transaction',
        'operations',
        '_default_columns',
        '_in_transaction',
        '_query_cache'
    )

    def __init__(
        self,
        database: Database | None,
        name: str,
        rows: dict[int, Row] | Iterable[Row] = (),
        columns: dict[str, Column[Any]] | Iterable[Column[Any]] = (),
        indexes: dict[str, Index] | Iterable[Index] = (),
        operations: Iterable[Operation] = (),
        _data_is_valid: bool = False
    ):
        self.database = database
        self.name = name

        self._rows: dict[int, Row] = _to_dict(rows, lambda row: row.id)
        self._columns: dict[str, Column[Any]] = _to_dict(columns, lambda column: column.name)
        self.indexes: dict[str, Index] = _to_dict(indexes, lambda index: index.column)

        self._transaction = None
        self._in_transaction = False
        self._query_cache: dict[tuple[Any, ...], TableView] = {}

        self.operations: list[Operation] = list(operations)

        if not _data_is_valid:
            self._check_data()

        self._default_columns = tuple(
            col for col in self._columns.values()
            if 'autoinc' in col.properties or col.default is not None
        )

    def __str__(self) -> str:
        return display_table(self, width=100, sort=False)

    def __repr__(self) -> str:
        return f'Table({self.name}, ...)'

    # Internal
    def _check_data(self):
        """Validate and wire up rows, columns, and indexes."""
        for row in self._rows.values():
            if row.table != self:
                row.table = self
                row._deferred_init() # pyright: ignore[reportPrivateUsage]

        self._validate_data()

        for col in self._columns.values():
            if col.table != self:
                col.table = self

        if self.database and self not in self.database.tables.values():
            if self.name in self.database.tables:
                raise TableAlreadyExistsError(f'Table {self.name} already exists.')

            self.database.tables[self.name] = self

        for idx in self.indexes.values():
            idx.build(self)

    def _validate_data(self):
        """Check that all row values match their column types."""
        columns = self._columns
        for row in self._rows.values():
            for name, value in row.values.items():
                expected = columns.get(name)
                if expected is not None and expected.type is not type(value):
                    raise TypeMismatchError(
                        f"Type mismatch in row: {type(value).__name__} "
                        f"!= {expected.type.__name__}, {name}={value}"
                    )

    def _apply_ops(self):
        """Apply pending operations and mark indexes dirty."""
        if not self.operations:
            return

        optimized: list[Operation] = Operation.optimize(self.operations)

        self.operations = []

        for op in optimized:
            op.apply(self)

        self._query_cache.clear()

        # Mark indexes dirty - they will be rebuilt lazily on first access
        for index in self.indexes.values():
            index._mark_dirty() # pyright: ignore[reportPrivateUsage]

    def _apply_ops_to_rows(self, rows: dict[int, Row]) -> dict[int, Row]:
        """Apply pending operations to a given set of rows.\n
            :param rows: The rows to transform
            :type rows: dict[int, Row]
        """
        for op in self.operations:
            if func := Operation.map.get(op.type):
                rows = func(op, self, rows)

            else:
                raise InvalidOperationType(f"Unknown operation type: {op.type}")

        return rows

    # Properties
    @property
    def rows(self) -> dict[int, Row]:
        """Return the table's rows, applying pending operations first."""
        if self._transaction:
            raise InATransactionError(f'You cannot access {self.name}.rows while in a transaction. Use tx.rows.')

        self._apply_ops()
        return self._rows

    @rows.setter
    def rows(self, value: dict[int, Row]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.rows.')

        self._rows = value

    @property
    def columns(self) -> dict[str, Column[Any]]:
        """Return the table's columns, applying pending operations first."""
        if self._transaction:
            raise InATransactionError(f'You cannot access {self.name}.columns while in a transaction. Use tx.columns.')

        self._apply_ops()
        return self._columns

    @columns.setter
    def columns(self, value: dict[str, Column[Any]] | list[Column[Any]]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.columns.')

        if type(value) is list:
            value = {col.name: col for col in value}

        self._columns = cast(dict[str, Column[Any]], value)

    # Auto-indexed lookups
    def get_index(self, column: str) -> Index | None:
        """Return the index associated with a column, or None if no index exists."""
        return self.indexes.get(column, None)

    def lookup(self, column: str, value: Any) -> set[int]:
        """Return all row IDs whose column has the given value."""
        if idx := self.get_index(column):
            return idx.values[value]

        return {
            id for id, row in self._rows.items()
            if row.values[column] == value
        }

    def lookup_one(self, column: str, value: Any) -> int | None:
        """Return first row whose column has the given value, or None."""
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

    # Querying
    @overload
    def where(self, column: Callable[[Row], bool]) -> TableView: ...
    @overload
    def where(self, column: str, key: Any) -> TableView: ...
    def where(self, column: str | Callable[[Row], bool], key: Any = _MISSING) -> TableView:
        """Return a filtered view where the predicate or column condition is true."""
        cache_key = (OpType.WHERE, column, key)
        if cached := self._query_cache.get(cache_key):
            return cached

        t = self.clone()

        if key is _MISSING:
            assert callable(column)
            op = Operation(OpType.WHERE, column)
        else:
            assert type(column) is str
            op = Operation(OpType.WHERE, column, key)

        t.operations.append(op)
        self._query_cache[cache_key] = t
        return t

    def transform(self, *keys: Callable[[Row], Row]) -> TableView:
        """Return a view with row-transforming operations applied."""
        cache_key = (OpType.TRANSFORM, tuple(id(k.__code__) for k in keys))
        if cached := self._query_cache.get(cache_key):
            return cached

        t = self.clone()
        t.operations.append(Operation(OpType.TRANSFORM, *keys))
        self._query_cache[cache_key] = t
        return t

    def transform_rows(self, keys: str | list[str], func: Callable[[Any], Any]) -> TableView:
        """Return a view that transforms specific column values."""
        key = tuple(keys) if type(keys) is list else keys
        cache_key = (OpType.TRANSFORM_ROWS, key, id(func.__code__))
        if cached := self._query_cache.get(cache_key):
            return cached

        t = self.clone()
        t.operations.append(Operation(OpType.TRANSFORM_ROWS, keys, func))
        self._query_cache[cache_key] = t
        return t

    def select(self, *columns: str) -> TableView:
        """Return a view projecting only the specified columns."""
        t = self.clone()
        t.operations.append(Operation(OpType.SELECT, *columns))
        return t

    def limit(self, count: int) -> TableView:
        """Return a view limited to the first ``count`` rows."""
        t = self.clone()
        t.operations.append(Operation(OpType.LIMIT, count))
        return t

    def sort(
        self,
        key: Callable[[Row], Any],
        reverse: bool = False,
    ) -> TableView:
        """Return a view with rows sorted by the given key function."""
        t = self.clone()
        t.operations.append(Operation(OpType.SORT, key, reverse))
        return t

    def distinct(self, *columns: str) -> TableView:
        """Return a view with duplicate rows removed."""
        t = self.clone()
        t.operations.append(Operation(OpType.DISTINCT, *columns))
        return t

    # Mutation
    def transaction(self, catch_exc: bool = False) -> Transaction:
        """Begin a transaction on this table."""
        from .transaction import Transaction
        if not self._transaction:
            self._transaction = Transaction(self, catch_exc)

        return self._transaction

    def add(self, row: Row) -> Table:
        """Add a row to this table (must be in a transaction)."""
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        self.operations.append(Operation(OpType.ADD, row))
        return self

    def update(self, table: Table) -> Table:
        """Update this table from another table (must be in a transaction)."""
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        self.operations.append(Operation(OpType.UPDATE, table))
        return self

    def delete(self, key: Callable[[Row], bool]) -> Table:
        """Delete rows matching the predicate (must be in a transaction)."""
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        self.operations.append(Operation(OpType.DELETE, key))
        return self

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
        """Replace this table's data with a deep copy of another table's."""
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
        self._query_cache = {}

    def clone(self) -> TableView:
        """Return a TableView that lazily applies pending operations."""
        if not self._in_transaction:
            self._apply_ops()

        # Return a TableView instead of copying rows
        from .tableview import TableView

        return TableView(self)

    def rclone(self, table: Table):
        """Replace this table's data with a shallow copy of another table's."""
        self._rows = table._rows.copy()
        self._columns = table._columns.copy()
        self.operations = table.operations.copy()
        self._query_cache = {}
        self.indexes = {
            name: index.clone()
            for name, index in table.indexes.items()
        }
        self._default_columns = tuple(
            col for col in self._columns.values()
            if 'autoinc' in col.properties or col.default is not None
        )
