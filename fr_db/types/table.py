from typing import TYPE_CHECKING, Any, cast, overload
from collections.abc import Iterable, Callable

from .operation import Operation, OpType
from ..display import display_table

from ..errors import (
    NoTransactionError,
    TableAlreadyExistsError,
    InATransactionError,
    TypeMismatchError,
    InvalidOperationType
)

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
    if type(value) is dict:
        return cast(dict[K, T], value)

    value = cast(Iterable[T], value)

    return {key(item): item for item in value}

class Table:
    __slots__ = ['database', 'name', '_rows', '_columns', 'indexes', '_transaction', 'operations', '_default_columns', '_in_transaction']
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

        self.operations: list[Operation] = list(operations)

        if not _data_is_valid:
            self._check_data()

        self._default_columns = tuple(
            col for col in self._columns.values()
            if 'autoinc' in col.properties or col.default is not None
        )

    def _check_data(self):
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
        for row in self._rows.values():
            value_types = {
                name: col.type
                for name, col in row.columns.items()
            }

            for name, value in row.values.items():
                expected = value_types[name]

                if expected is not type(value):
                    raise TypeMismatchError(
                        f"Type mismatch in row: {type(value).__name__} "
                        f"!= {expected.__name__}, {name}={value}"
                    )

    def __str__(self) -> str:
        return display_table(self, width=100, sort=False)

    def __repr__(self) -> str:
        return f'Table({self.name}, ...)'

    def _apply_ops(self):
        if not self.operations:
            return

        optimized: list[Operation] = Operation.optimize(self.operations)

        self.operations = []

        for op in optimized:
            op.apply(self)

    def _apply_ops_to_rows(self, rows: dict[int, Row]) -> dict[int, Row]:
        for op in self.operations:
            if func := Operation.map.get(op.type):
                rows = func(op, self, rows)

            else:
                raise InvalidOperationType(f"Unknown operation type: {op.type}")

        return rows

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

        if type(value) is list:
            value = {col.name: col for col in value}

        self._columns = cast(dict[str, Column[Any]], value)

    # Auto-indexed lookups
    def get_index(self, column: str) -> Index | None:
        """Return the index associated with a column, or None if no index exists.

        Used by lookup helpers to determine whether an indexed lookup is
        available for the requested column.
        """
        return self.indexes.get(column, None)

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

    # Querying
    @overload
    def where(self, column: Callable[[Row], bool]) -> Table: ...
    @overload
    def where(self, column: str, key: Any) -> Table: ...
    def where(self, column: str | Callable[[Row], bool], key: Any = _MISSING) -> Table:
        t = self.clone()

        if key is _MISSING:
            assert callable(column)
            op = Operation(OpType.WHERE, column)
        else:
            assert type(column) is str
            op = Operation(OpType.WHERE, column, key)

        t.operations.append(op)
        return t

    def transform(self, *keys: Callable[[Row], Row]) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.TRANSFORM, *keys))
        return t

    def transform_rows(self, keys: str | list[str], func: Callable[[Any], Any]) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.TRANSFORM_ROWS, keys, func))
        return t

    def select(self, *columns: str) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.SELECT, *columns))
        return t

    def limit(self, count: int) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.LIMIT, count))
        return t

    def sort(
        self,
        key: Callable[[Row], Any],
        reverse: bool = False,
    ) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.SORT, key, reverse))
        return t

    def distinct(self, *columns: str) -> Table:
        t = self.clone()
        t.operations.append(Operation(OpType.DISTINCT, *columns))
        return t

    # Mutation
    def transaction(self, catch_exc: bool = False) -> Transaction:
        from .transaction import Transaction
        if not self._transaction:
            self._transaction = Transaction(self, catch_exc)

        return self._transaction

    def add(self, row: Row) -> Table:
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        self.operations.append(Operation(OpType.ADD, row))
        return self

    def update(self, table: Table) -> Table:
        if self.database:
            raise NoTransactionError(
                'You must be in a transaction to mutate a table.'
            )

        self.operations.append(Operation(OpType.UPDATE, table))
        return self

    def delete(self, key: Callable[[Row], bool]) -> Table:
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
        if not self._in_transaction:
            self._apply_ops()
        # Return a TableView instead of copying rows
        from .tableview import TableView
        return TableView(self)

    def rclone(self, table: Table):
        self._rows = table._rows.copy()
        self._columns = table._columns.copy()
        self.operations = table.operations.copy()
        self.indexes = {
            name: index.clone()
            for name, index in table.indexes.items()
        }
        self._default_columns = tuple(
            col for col in self._columns.values()
            if 'autoinc' in col.properties or col.default is not None
        )

