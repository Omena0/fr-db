from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .table import Table
    from .row import Row


class Index:
    __slots__ = ['column', 'unique', 'values', '_shared']

    def __init__(
        self,
        column: str,
        unique: bool = False,
    ):
        self.column = column
        self.unique = unique
        self.values: dict[Any, set[int]] = {}
        self._shared = False

    def __repr__(self) -> str:
        return f'Index({self.column}, {self.values})'

    def _detach(self):
        if not self._shared:
            return

        self.values = self.values.copy()
        self._shared = False

    def add(self, row: Row):
        value = row.values[self.column]
        ids = self.values.get(value)

        if self.unique and ids:
            raise ValueError(
                f"Duplicate value {value!r} "
                f"for unique index {self.column!r}"
            )

        self._detach()

        if ids is None:
            self.values[value] = {row.id}
        else:
            ids = ids.copy()
            ids.add(row.id)
            self.values[value] = ids

    def remove(self, row: Row):
        value = row.values[self.column]
        ids = self.values.get(value)

        if ids is None or row.id not in ids:
            return

        self._detach()

        ids = ids.copy()
        ids.remove(row.id)

        if ids:
            self.values[value] = ids
        else:
            del self.values[value]

    def update(
        self,
        old_value: Any,
        new_value: Any,
        row_id: int,
    ):
        if old_value == new_value:
            return

        new_ids = self.values.get(new_value)

        if self.unique and new_ids and (
            new_ids != {row_id}
        ):
            raise ValueError(
                f"Duplicate value {new_value!r} "
                f"for unique index {self.column!r}"
            )

        self._detach()

        old_ids = self.values.get(old_value)

        if old_ids is not None:
            old_ids = old_ids.copy()
            old_ids.discard(row_id)

            if old_ids:
                self.values[old_value] = old_ids
            else:
                del self.values[old_value]

        new_ids = self.values.get(new_value)

        if new_ids is None:
            self.values[new_value] = {row_id}
        else:
            new_ids = new_ids.copy()
            new_ids.add(row_id)
            self.values[new_value] = new_ids

    def build(self, table: Table):
        self.values.clear()
        self._shared = False

        for row_id, row in table._rows.items(): # pyright: ignore[reportPrivateUsage]
            value = row.values[self.column]
            ids = self.values.get(value)

            if self.unique and ids:
                raise ValueError(
                    f"Duplicate value {value!r} "
                    f"in unique index {self.column!r}"
                )

            if ids is None:
                self.values[value] = {row_id}
            else:
                ids.add(row_id)

    def copy(self, table: Table):
        index = Index(self.column, self.unique)
        index.values = {
            value: ids.copy()
            for value, ids in self.values.items()
        }
        return index

    def clone(self) -> Index:
        index = Index(self.column, self.unique)
        index.values = self.values
        index._shared = True
        return index
