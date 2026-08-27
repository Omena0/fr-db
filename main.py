from fr_db import Database, Table, Row, Column, Index
from datetime import datetime
import cProfile
import pstats

profiler = cProfile.Profile()
profiler.enable()

db = Database()

users = Table(
    db,
    "users",
    [
    ],
    [
        Column('id', int, ['primary', 'autoinc']),
        Column('username', str, ['unique']),
        Column('created_at', datetime, default=datetime.now)
    ],
    [
        Index('id', True),
        Index('username', True)
    ]
)

with users.transaction() as tx:
    for i in range(10000):
        tx.add(Row(username=f'randomuser{i}'))

    tx.add(Row(username='Omena0'))


ITERS = 10000
with users.transaction() as tx:
    for _ in range(ITERS):
        tx.update(
            tx.where('username', 'Omena0')
                .transform_rows(['id'], lambda x: x+1)
        )

profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats("cumtime").print_stats()


