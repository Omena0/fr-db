from typing import Any, TYPE_CHECKING, Callable, Iterable, cast


if TYPE_CHECKING:
    from .table import Table
    from .row import Row

def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value

class Operation:
    __slots__ = ['type', 'key']
    def __init__(self, type: str, *key: Any):
        self.type = type
        self.key  = key

    def __repr__(self) -> str:
        return f'Operation({self.type}, *{self.key})'

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

    def _transform(self, rows: dict[int, Row]):
        for id, row in rows.items():
            rows[id] = apply_all(self.key, row)

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

    def _limit(self, rows: dict[int, Row]) -> dict[int, Row]:
        assert isinstance(self.key[0], int)

        return {
            row.id: row
            for row in list(rows.values())[:self.key[0]]
        }

    def _sort(self, rows: dict[int, Row]) -> dict[int, Row]:
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

    def _distinct(self, rows: dict[int, Row]) -> dict[int, Row]:
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

    def apply(self, table: Table):
        rows = table._rows  # pyright: ignore[reportPrivateUsage]

        if self.type == "where":
            rows = self._where(table, rows)

        elif self.type == "transform":
            rows = self._transform(rows)

        elif self.type == "select":
            rows = self._select(table, rows)

        elif self.type == "limit":
            rows = self._limit(rows)

        elif self.type == "sort":
            rows = self._sort(rows)

        elif self.type == "distinct":
            rows = self._distinct(rows)

        else:
            raise ValueError(f"Unknown operation type: {self.type}")

        table._rows = rows  # pyright: ignore[reportPrivateUsage]

