from ..errors import MutuallyExclusiveError
from typing import Any, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from .table import Table

_MISSING = object()


class Column[T]():
    """
        A column definition for a table.

        Defines the type, defaults, and properties (primary, unique, autoinc)
        of a single column.
    """
    __slots__ = (
        'name',
        'type',
        'default',
        'properties',
        'primary',
        'unique',
        'table',
        '_next_autoinc',
        'default_is_factory'
    )

    def __init__(
        self,
        name: str,
        val_type: type[T],
        properties: list[str] = [],
        default: T | Callable[[], Any] = _MISSING,
        table: Table | None = None,
    ):
        self.name = name
        self.type = val_type

        self.default: T | Callable[[], Any] = default
        self.default_is_factory = callable(self.default)

        self.properties: list[str] = properties
        self.primary = 'primary' in properties
        self.unique  = 'unique'  in properties or self.primary

        self._next_autoinc = 0

        if self.unique and self.default is not _MISSING:
            raise MutuallyExclusiveError('Column cannot be unique and have a default value.')

        self.table = table

        if self.table and self not in self.table.columns:
            self.table.columns[self.name] = self

    def __repr__(self) -> str:
        return f'Column({self.name}, {self.type.__name__}, {self.default}, {self.properties})'

    # Internal
    def autoinc(self):
        """Generate the next auto-incremented value."""
        self._next_autoinc += 1
        return self._next_autoinc-1

    def copy(self, table: Table | None = None) -> Column[T]:
        """Create a copy of this column, optionally bound to a table.\n
            :param table: The table for the copied column
            :type table: Table | None
        """
        column = Column(
            self.name,
            self.type,
            self.properties.copy(),
            self.default,
            None,
        )

        column.table = table

        if table is not None:
            table._columns[self.name] = column # pyright: ignore[reportPrivateUsage]

        return column
