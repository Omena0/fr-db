from typing import Any, TYPE_CHECKING, Callable

from ..errors import NoTransactionError, TableAlreadyExistsError
from ..display import display_table
from .operation import Operation

if TYPE_CHECKING:
    from .transaction import Transaction
    from .database import Database
    from .column import Column
    from .index import Index
    from .row import Row

class Table:
    def __init__(
            self,
            database: Database | None,
            name: str,
            rows: list[Row] = [],
            columns: list[Column[Any]] = [],
            indexes: list[Index] = [],
            operations: list[Operation] = []
        ):
        self.database = database
        self.name = name

        self._rows: list[Row] = rows
        self._columns: list[Column[Any]] = columns
        self.indexes: list[Index] = indexes

        self._transaction = None

        self.operations: list[Operation] = operations

        for row in self.rows:
            if row.table != self:
                row.table = self
                row._deferred_init() # pyright: ignore[reportPrivateUsage]

        for row in self.rows:
            row._check_values() # pyright: ignore[reportPrivateUsage]

        for col in self.columns:
            if col.table != self:
                col.table = self

        if self.database and self not in self.database.tables:
            if name in self.database.tables:
                raise TableAlreadyExistsError(f'Table {name} already exists.')

            self.database.tables[name] = self

    def __repr__(self) -> str:
        return display_table(self, width=100, sort=False)

    def _apply_ops(self):
        if not self.operations:
            return

        for op in self.operations:
            op.apply(self)

        self.operations.clear()

    @property
    def rows(self) -> list[Row]:
        if self._transaction:
            return self._transaction.rows

        self._apply_ops()
        return self._rows

    @rows.setter
    def rows(self, value: list[Row]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transacion.rows.')

        self._rows = value

    @property
    def columns(self) -> list[Column[Any]]:
        if self._transaction:
            return self._transaction.columns

        self._apply_ops()
        return self._columns

    @columns.setter
    def columns(self, value: list[Column[Any]]):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.columns.')

        self._columns = value

    # Querying
    def where(self, key: Callable[[Row], bool]) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('where', key)
        t.operations.append(op)
        return t

    def transform(self, *key: Callable[[Row], Row]) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('transform', *key)
        t.operations.append(op)
        return t

    def select(self, *key: str) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('select', *key)
        t.operations.append(op)
        return t

    def limit(self, key: int) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('limit', key)
        t.operations.append(op)
        return t

    def sort(self, key: Callable[[Row], Any], reverse: bool = False) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('sort', key, reverse)
        t.operations.append(op)
        return t

    def distinct(self, *key: str) -> Table:
        t = Table(None, self.name, self._rows, self._columns, operations=self.operations.copy())
        op = Operation('distinct', *key)
        t.operations.append(op)
        return t

    # Mutation
    def transaction(self, catch_exc: bool = False) -> Transaction:
        from .transaction import Transaction
        if not self._transaction:
            self._transaction = Transaction(self, catch_exc)

        return self._transaction

    def add(self, row: Row):
        if self.database:
            raise NoTransactionError('You must be in a transaction to mutate a table. Write to transaction.columns.')

        self.rows.append(row)

        if row.table != self:
            row.table = self
            row._deferred_init() # pyright: ignore[reportPrivateUsage]
        row._check_values() # pyright: ignore[reportPrivateUsage]

    def update(self, table: Table):
        """Updates keys based on keys in table.

        Based on key order, so do not sort or remove keys from source table.

        :param table: _description_
        :type table: Table
        :raises NoTransactionError: _description_
        """
        if self.database:
            raise NoTransactionError(
                "You must be in a transaction to mutate a table."
            )

        for r1 in self.rows:
            for r2 in table.rows:
                if r1.id == r2.id:
                    r1.values.update(r2.values)
                    break

    def delete(self, key: Callable[[Row], bool]):
        if self.database:
            raise NoTransactionError(
                "You must be in a transaction to mutate a table."
            )

        self._rows[:] = [
            row for row in self.rows
            if not key(row)
        ]

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
        )

        table._columns = [
            col.copy(table)
            for col in self._columns
        ]

        table._rows = [
            row.copy(table)
            for row in self._rows
        ]

        table.indexes = [
            index.copy(table)
            for index in self.indexes
        ]

        return table

    def rcopy(self, table: Table):
        """Replace this table's state with an independent copy of another table."""
        self._rows = [
            row.copy(self)
            for row in table._rows
        ]

        self._columns = [
            col.copy(self)
            for col in table._columns
        ]

        self.indexes = [
            index.copy(self)
            for index in table.indexes
        ]

        self.operations = table.operations.copy()
