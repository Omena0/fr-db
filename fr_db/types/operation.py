from typing import Any, TYPE_CHECKING, Callable, Iterable

if TYPE_CHECKING:
    from .table import Table

def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value

class Operation:
    def __init__(self, type: str, *key: Any):
        self.type = type
        self.key  = key

    def __repr__(self) -> str:
        return f'Operation({self.type}, *{self.key})'

    def apply(self, table: Table):
        rows = table._rows # pyright: ignore[reportPrivateUsage]

        if self.type == 'where':
            assert callable(self.key[0])
            rows = [i for i in rows if all([p(i) for p in self.key])]

        elif self.type == 'transform':
            assert all([callable(i) for i in self.key])
            rows = [apply_all(self.key, i) for i in rows]

        elif self.type == "select":
            from .row import Row
            assert all(isinstance(i, str) for i in self.key)

            table._columns = [ # pyright: ignore[reportPrivateUsage]
                next(col for col in table._columns if col.name == key) # pyright: ignore[reportPrivateUsage]
                for key in self.key
            ]

            rows = [
                Row(
                    id_ = row.id
                    **{
                        key: row.values[key]
                        for key in self.key
                    },
                    columns=table._columns # pyright: ignore[reportPrivateUsage]
                )
                for row in rows
            ]

        elif self.type == 'limit':
            assert isinstance(self.key[0], int)
            rows = rows[:self.key[0]]

        elif self.type == "sort":
            assert callable(self.key[0]) and isinstance(self.key[1], bool)

            key, reverse = self.key

            rows = sorted(
                rows,
                key=key,
                reverse=reverse,
            )

        elif self.type == "distinct":
            seen: set[tuple[Any, ...]] = set()
            unique_rows: list[Row] = []

            for row in rows:
                values = (
                    tuple(row.values[k] for k in self.key)
                    if self.key
                    else tuple(row.values.values())
                )

                if values not in seen:
                    seen.add(values)
                    unique_rows.append(row)

            rows = unique_rows

        table._rows = rows # pyright: ignore[reportPrivateUsage]

