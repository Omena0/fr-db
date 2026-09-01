from ..errors import DuplicateValueError, TypeMismatchError
from typing import Any, Callable, Iterable
from .column import Column
from .table import Table


class Row:
    __slots__ = ('values', 'table', 'columns', 'id')

    def __init__(
        self,
        table: Table | None = None,
        id_: int | None = None,
        **values: Any,
    ):
        self.values = values
        self.table = table
        self.columns: dict[str, Column[Any]] = {}

        self.id = id_ or id(self)

       # If table isnt defined yet then the Table should define it and call _deferred init later.
        if isinstance(self.table, Table):
            self._deferred_init()

    def __repr__(self) -> str:
        return str(self.values)

    def __getitem__(self, key: Any):
        return self.values[key]

    def _deferred_init(self):
        """Register this row with its table's columns and rows."""
        assert isinstance(self.table, Table)

        self.columns = self.table._columns # pyright: ignore[reportPrivateUsage]

        if self.id not in self.table._rows: # pyright: ignore[reportPrivateUsage]
            self.table._rows[self.id] = self # pyright: ignore[reportPrivateUsage]

        for col in self.columns.values():
            if col.name in self.values:
                continue

            self.values[col.name] = self._get_default_value(col)

    def _check_values(
        self,
        rows: Iterable[Row] | None = None,
        exclude: Iterable[Row] = (),
    ):
        """Validate uniqueness and types for this row's values.\n
            :param rows: Rows to check against (defaults to the table's rows)
            :type rows: Iterable[Row] | None
            :param exclude: Rows to skip during uniqueness checks
            :type exclude: Iterable[Row]
            :raises DuplicateValueError: If a unique column value already exists
            :raises TypeMismatchError: If a value's type doesn't match its column
        """
        assert self.columns

        exclude_ids = {row.id for row in exclude}
        exclude_ids.add(self.id)

        if rows is None:
            assert self.table
            rows = self.table._rows.values() # pyright: ignore[reportPrivateUsage]

       # Check uniqueness
        for name, col in self.columns.items():
            if not col.unique:
                continue

            value = self.values[name]

            index = self.table.get_index(name) if self.table else None

            if index is not None and index.values.get(value):
                raise DuplicateValueError(
                    f"Duplicate value {value!r} for "
                    f"{'primary' if col.primary else 'unique'} column {name!r}"
                )

            elif any(
                row.id not in exclude_ids and row.values[name] == value
                for row in rows
            ):
                raise DuplicateValueError(
                    f"Duplicate value {value!r} for "
                    f"{'primary' if col.primary else 'unique'} column {name!r}"
                )

        value_types = {
            name: col.type
            for name, col in self.columns.items()
        }

        for name, value in self.values.items():
            expected = value_types[name]

            if expected is not type(value):
                raise TypeMismatchError(
                    f"Type mismatch in row: {type(value).__name__} "
                    f"!= {expected.__name__}, {name}={value}"
                )

    def _get_default_value(self, col: Column[Any]):
        """Resolve the default value for a column.\n
            :param col: The column to read defaults from
            :type col: Column[Any]
        """
        assert isinstance(self.table, Table)

        if 'autoinc' in col.properties:
            return col.autoinc()

        elif col.default:
            return col.default() if col.default_is_factory else col.default

        return None

    def set_value(self, key: str, value: Any):
        """Set a column value on this row.\n
            :param key: The column name
            :type key: str
            :param value: The value to set
            :type value: Any
        """
        self.values[key] = value
        return self

    def transform(self, keys: str | list[str], func: Callable[[Any], Any]) -> Row:
        """Transform this row's values with a function.\n
            :param keys: Column name(s) to transform
            :type keys: str | list[str]
            :param func: Function applied to each matched value
            :type func: Callable[[Any], Any]
            :return: A new transformed row
            :rtype: Row
        """
        r = Row(None, id_=self.id, **self.values)

        if type(keys) is str:
            keys = [keys]

        for k, v in r.values.items():
            if k in keys:
                r.set_value(k, func(v))

        return r

    def copy(self, table: Table | None = None) -> Row:
        """Create a copy of this row, optionally bound to a table.\n
            :param table: The table for the copied row
            :type table: Table | None
            :return: A new row instance
            :rtype: Row
        """
        row = object.__new__(Row)

        row.table = table
        row.id = self.id
        row.values = self.values.copy()
        row.columns = table._columns if table else self.columns # pyright: ignore[reportPrivateUsage]

        return row

    @property
    def primary_key(self):
        """The column name of this row's primary key."""
        assert self.columns
        return [name for name, col in self.columns.items()
                if 'primary' in col.properties][0]
