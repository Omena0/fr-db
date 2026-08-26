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

    def _add(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        row = self.key[0]
        row = row.copy(table)
        row.table = table

        for col in table._default_columns: # pyright: ignore[reportPrivateUsage]
            if col.name not in row.values:
                row.values[col.name] = row._get_default_value(col) # pyright: ignore[reportPrivateUsage]

        new_rows = rows.copy()
        new_rows[row.id] = row

        for index in table.indexes.values():
            index.add(row)

        return new_rows

    def _update(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        source_table = self.key[0]
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

        elif self.type == "add":
            rows = self._add(table, rows)

        elif self.type == "update":
            rows = self._update(table, rows)

        elif self.type == "delete":
            rows = self._delete(table, rows)

        else:
            raise ValueError(f"Unknown operation type: {self.type}")

        table._rows = rows  # pyright: ignore[reportPrivateUsage]

