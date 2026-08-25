from ..errors import TypeMismatchError, MutuallyExclusiveError
from typing import TYPE_CHECKING, Callable, Any

if TYPE_CHECKING:
    from .table import Table

class Column[T]():
    def __init__(
        self,
        name: str,
        val_type: type[T],
        properties: list[str] = [],
        default: T | Callable[[], Any] = None,
        table: Table | None = None,
    ) -> None:
        if default and not isinstance(default, val_type) and not callable(default):
            raise TypeMismatchError(f'Default must be type of val_type: {default}')

        self.name = name
        self.type = val_type
        self.default: T | Callable[[], Any] = default
        self.properties: list[str] = properties
        self.primary = 'primary' in properties
        self.unique  = 'unique'  in properties or self.primary

        if self.unique and self.default is not None:
            raise MutuallyExclusiveError('Column cannot be unique and have a default value.')

        self.table = table

        if self.table and self not in self.table.columns:
            self.table.columns.append(self)

    def __repr__(self) -> str:
        return f'Column({self.name}, {self.type.__name__}, {self.default}, {self.properties})'

    def copy(self, table: Table | None = None) -> Column[T]:
        column = Column(
            self.name,
            self.type,
            self.properties.copy(),
            self.default,
            None,
        )

        column.table = table

        if table is not None:
            table._columns.append(column) # pyright: ignore[reportPrivateUsage]

        return column

