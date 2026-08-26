from ..errors import DuplicateValueError, TypeMismatchError
from typing import Any, Callable, Iterable
from .column import Column
from .table import Table

class Row:
    __slots__ = ['values', 'table', 'value_types', 'columns', 'id']
    def __init__(
            self,
            table: Table | None = None,
            id_: int | None = None,
            **values: Any
        ):
        self.values = values
        self.table = table
        self.value_types: dict[str, type[Any]] = {}
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
        assert self.columns

        exclude_ids = {row.id for row in exclude}
        exclude_ids.add(self.id)

        if rows is None:
            assert self.table
            rows = self.table._rows.values()  # pyright: ignore[reportPrivateUsage]

        for name, col in self.columns.items():
            if not col.unique:
                continue

            value = self.values[name]

            index = self.table.get_index(name) if self.table else None

            if index is not None:
                matching = index.values.get(value, set())

                if any(id not in exclude_ids for id in matching):
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

        value_types = self.value_types or {
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
        assert isinstance(self.table, Table)

        if 'autoinc' in col.properties:
            return col.autoinc()

        elif col.default:
            return col.default() if callable(col.default) else col.default

        return None

    def set_value(self, key: str, value: Any):
        self.values[key] = value
        return self

    def transform(self, keys: str | list[str], func: Callable[[Any], Any]) -> Row:
        r = Row(None, id_=self.id, **self.values)

        if isinstance(keys, str):
            keys = [keys]

        for k, v in r.values.items():
            if k in keys:
                r.set_value(k, func(v))

        return r

    def copy(self, table: Table | None = None) -> Row:
        row = object.__new__(Row)

        row.table = table
        row.id = self.id
        row.values = self.values.copy()
        row.columns = table._columns if table else self.columns # pyright: ignore[reportPrivateUsage]
        row.value_types = self.value_types.copy()

        return row

    @property
    def primary_key(self):
        assert self.columns
        return [
            name for name, col in self.columns.items()
            if 'primary' in col.properties
        ][0]
