from ..errors import DuplicateValueError, TypeMismatchError
from typing import Any, Callable
from .column import Column
from .table import Table

class Row:
    def __init__(
            self,
            table: Table | None = None,
            id_: int | None = None,
            **values: Any
        ):
        self.values = values
        self.table = table
        self.value_types: dict[str, type[Any]] = {}
        self.columns = None

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

        self.columns: list[Column[Any]] | None = self.table._columns # pyright: ignore[reportPrivateUsage]

        for col in self.columns:
            # Try to initialize missing values to default or autoinc
            if col.name not in self.values:
                val = self._get_default_value(col)
                self.values[col.name] = val

    def _check_values(self):
        assert isinstance(self.table, Table) and self.columns

        for col in [c for c in self.columns if c.unique]:
            value = self.values[col.name]

            if any(
                    row is not self and
                    row.values[col.name] == value
                    for row in self.table.rows
                ):
                raise DuplicateValueError(
                    f"Duplicate value {value!r} for {'primary' if col.primary else 'unique'} column {col.name!r}"
                )

        types = {c.name: c.type for c in self.columns}
        for name, val in self.values.items():
            if types[name] is not type(val):
                raise TypeMismatchError(f'Type mismatch in row: {type(val).__name__} != {types[name].__name__}, {name}={val}')

        if self not in self.table.rows:
            self.table.rows.append(self)

    def _get_default_value(self, col: Column[Any]):
        assert isinstance(self.table, Table)
        value = None

        if 'autoinc' in col.properties:
            return self.table.rows.index(self)

        if col.default:
            if callable(col.default):
                return col.default()
            return col.default

        return value

    def set_value(self, key: str, value: Any):
        self.values[key] = value
        return self

    def transform(self, keys: list[str], func: Callable[[Any], Any]) -> Row:
        r = Row(None, id_=self.id, **self.values)

        for k, v in r.values.items():
            if k in keys:
                r.set_value(k, func(v))

        return r

    def copy(self, table: Table | None = None) -> Row:
        row = Row(table, self.id, **self.values.copy())

        if hasattr(self, "columns") and self.columns:
            row.columns = self.columns.copy()

        if hasattr(self, "value_types"):
            row.value_types = self.value_types.copy()

        return row

    @property
    def primary_key(self):
        assert self.columns
        return [col.name for col in self.columns if 'primary' in col.properties][0]
