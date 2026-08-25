from .table import Table

class Database:
    def __init__(self):
        self.tables: dict[str, Table] = {}
