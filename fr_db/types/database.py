from .table import Table

class Database:
    __slots__ = ['tables']
    def __init__(self):
        self.tables: dict[str, Table] = {}
