from fr_db import Database, Table, Row, Column
from datetime import datetime

db = Database()

users = Table(
    db,
    "users",
    [
        Row(username='randomuser'),
        Row(username='Omena0')
    ],
    [
        Column('id', int, ['primary', 'autoinc']),
        Column('username', str, ['unique']),
        Column('created_at', datetime, default=datetime.now)
    ]
)

with users.transaction() as tx:
    tx.update(
        users.where(lambda r: r['id'] == 1)
            .transform(lambda r: r.transform(['id'], lambda x: x+10))
    )

print(users)
