from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .table import Table

class Index:
    def __init__(self, ):
        ...

    def copy(self, table: Table) -> Index:
        ...
