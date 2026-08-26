from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .table import Table
    from .row import Row

class Index:
    __slots__ = ['column', 'unique', 'values']
    def __init__(
        self,
        column: str,
        unique: bool = False
    ):
        self.column = column
        self.unique = unique
        self.values: dict[Any, set[int]] = {}

    def __repr__(self) -> str:
        return f'Index({self.column}, {self.values})'

    def add(self, row: Row):
        value = row.values[self.column]

        if self.unique and value in self.values:
            raise ValueError(
                f"Duplicate value {value!r} for unique index {self.column!r}"
            )

        self.values.setdefault(value, set()).add(row.id)

    def remove(self, row: Row):
        value = row.values[self.column]

        ids = self.values.get(value)
        if ids is None:
            return

        ids.discard(row.id)

        if not ids:
            del self.values[value]

    def update(self, old_value: Any, new_value: Any, row_id: int):
        if old_value == new_value:
            return

        ids = self.values.get(old_value)
        if ids is not None:
            ids.discard(row_id)

            if not ids:
                del self.values[old_value]

        if self.unique and new_value in self.values:
            raise ValueError(
                f"Duplicate value {new_value!r} for unique index {self.column!r}"
            )

        self.values.setdefault(new_value, set()).add(row_id)

    def build(self, table: Table):
        """Build the index from all rows currently in the table."""
        self.values.clear()

        for id, row in table._rows.items():  # pyright: ignore[reportPrivateUsage]
            value = row.values[self.column]

            if self.unique and value in self.values:
                raise ValueError(
                    f"Duplicate value {value!r} in unique index {self.column!r}"
                )

            self.values.setdefault(value, set()).add(id)

    def copy(self, table: Table):
        index = Index(self.column, self.unique)
        index.values = {
            value: ids.copy()
            for value, ids in self.values.items()
        }
        return index
