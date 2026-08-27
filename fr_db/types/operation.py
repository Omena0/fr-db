from typing import Any, TYPE_CHECKING, Callable, Iterable, cast, Self
from ..errors import InvalidOperationType


if TYPE_CHECKING:
    from .table import Table
    from .row import Row

def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value

_MERGEABLE = frozenset({'add', 'delete', 'where', 'transform', 'transform_rows'})

class Operation:
    __slots__ = ['type', 'key']
    def __init__(self, type: str, *key: Any):
        self.type = type
        self.key  = key

    def __repr__(self) -> str:
        return f'Operation({self.type}, *{self.key})'

    @classmethod
    def optimize(cls, ops: list[Operation]) -> list[Operation]:
        if len(ops) <= 1:
            return ops

        result: list[Operation] = []
        i = 0
        n = len(ops)

        while i < n:
            op = ops[i]

            if op.type not in _MERGEABLE:
                result.append(op)
                i += 1
                continue

            # Collect all consecutive mergeable operations of the same type
            group = [op]
            j = i + 1
            while j < n and ops[j].type == op.type and (op.type != 'where' or (len(ops[j].key) == 1)):
                group.append(ops[j])
                j += 1

            if len(group) == 1:
                result.append(op)
            else:
                result.append(cls._merge_group(group))

            i = j

        return result

    @classmethod
    def _merge_group(cls, group: list[Operation]) -> Operation:
        op_type = group[0].type

        if op_type == 'add':
            rows:list[Row] = []
            for op in group:
                rows.extend(op.key)

            return Operation('add', *rows)

        elif op_type == 'delete':
            funcs = [op.key[0] for op in group]
            return Operation('delete', lambda r: any(f(r) for f in funcs)) # type: ignore

        elif op_type == 'where':
            funcs = [op.key[0] for op in group]
            return Operation('where', lambda r: all(f(r) for f in funcs)) # type: ignore

        elif op_type == 'transform':
            funcs: list[Callable[..., Any]] = []
            for op in group:
                funcs.extend(op.key)

            return Operation('transform', *funcs)

        elif op_type == 'transform_rows':
            transforms: list[Any] = []

            for op in group:
                transforms.append(op.key)

            return Operation('transform_rows', transforms)

        raise ValueError(f"Cannot merge {op_type}")

    def _where(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        if len(self.key) == 1:
            key = self.key[0]
            assert callable(key)

            return {
                id: row
                for id, row in rows.items()
                if key(row)
            }

        column, key = self.key

        if callable(key):
            return {
                id: row
                for id, row in rows.items()
                if key(row.values[column])
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows:  # pyright: ignore[reportPrivateUsage]
            return {id: table._rows[id] for id in matching}  # pyright: ignore[reportPrivateUsage]

        return {
            id: rows[id]
            for id in matching
            if id in rows
        }

    def _transform(self, table: Table, rows: dict[int, Row]):
        for id, row in rows.items():
            rows[id] = apply_all(self.key, row)

        return rows

    def _transform_rows(self, table: Table, rows: dict[int, Row]):
        transforms = self.key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        for keys, func in transforms:
            if isinstance(keys, str):
                keys = [keys]

            for row in rows.values():
                for k in keys:
                    row.values[k] = func(row.values[k])

        return rows

    def _select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        from .row import Row

        assert all(isinstance(i, str) for i in self.key)

        table._columns = {  # pyright: ignore[reportPrivateUsage]
            key: table._columns[key]  # pyright: ignore[reportPrivateUsage]
            for key in self.key
        }

        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in self.key
        }

        return {
            id: Row(
                id_=id,
                **{key: row.values[key] for key in self.key},
            )
            for id, row in rows.items()
        }

    def _limit(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        assert isinstance(self.key[0], int)

        return {
            row.id: row
            for row in list(rows.values())[:self.key[0]]
        }

    def _sort(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        assert callable(self.key[0])
        assert isinstance(self.key[1], bool)

        key, reverse = self.key

        return {
            row.id: row
            for row in sorted(
                rows.values(),
                key=key,
                reverse=reverse,
            )
        }

    def _distinct(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        seen: set[tuple[Any, ...]] = set()
        unique_rows: list[Row] = []

        for row in rows.values():
            values = (
                tuple(row.values[k] for k in self.key)
                if self.key
                else tuple(row.values.values())
            )

            if values not in seen:
                seen.add(values)
                unique_rows.append(row)

        return {
            row.id: row
            for row in unique_rows
        }

    def _add(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        new_rows = rows.copy()
        for row in self.key:
            row = row.copy(table)
            row.table = table

            for col in table._default_columns: # pyright: ignore[reportPrivateUsage]
                if col.name not in row.values:
                    row.values[col.name] = row._get_default_value(col) # pyright: ignore[reportPrivateUsage]

            new_rows[row.id] = row

            for index in table.indexes.values():
                index.add(row)

        return new_rows

    def _update(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        source_table: Table = self.key[0]
        source_rows = source_table.rows

        new_rows = rows.copy()

        for source_id, source in source_rows.items():
            current = new_rows.get(source_id)
            if current is None:
                continue

            current = current.copy(table)
            new_rows[source_id] = current

            old_values = {
                column: current.values[column]
                for column in table.indexes
                if column in source.values
            }

            current.values.update(source.values)

            for column, old_value in old_values.items():
                new_value = current.values[column]
                if old_value != new_value:
                    table.indexes[column].update(
                        old_value,
                        new_value,
                        current.id,
                    )

        return new_rows

    def _delete(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        key = self.key[0]
        to_delete = {id for id, row in rows.items() if key(row)}

        new_rows = rows.copy()
        for id in to_delete:
            row = new_rows.pop(id)
            for index in table.indexes.values():
                index.remove(row)

        return new_rows

    map: dict[str, Callable[[Self, Table, dict[int, Row]], dict[int, Row]]] = {
        "where": _where,
        "transform": _transform,
        "transform_rows": _transform_rows,
        "select": _select,
        "limit": _limit,
        "sort": _sort,
        "distinct": _distinct,
        "add": _add,
        "update": _update,
        "delete": _delete
    }

    def apply(self, table: Table):
        rows = table._rows  # pyright: ignore[reportPrivateUsage]

        func = Operation.map.get(self.type)

        if not func:
            raise InvalidOperationType(f"Unknown operation type: {self.type}")

        rows = func(self, table, rows)

        table._rows = rows  # pyright: ignore[reportPrivateUsage]

