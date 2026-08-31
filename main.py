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
        # Empty rows
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

ITERS = 10000

# Add 10k+1 users
with users.transaction() as tx:
    for i in range(ITERS):
        tx.add(Row(username=f'randomuser{i}'))

    tx.add(Row(username='Omena0'))

# Increment 'Omena0's ID 10k times
# Create source table once and reuse - merge logic only evaluates the first source
with users.transaction() as tx:
    source = tx.where('username', 'Omena0').transform_rows(['id'], lambda x: x+1)
    for _ in range(ITERS):
        tx.update(source)

profiler.disable()

stats = pstats.Stats(profiler)
stats.sort_stats("cumtime").print_stats(30)

# Make sure it took effect.
id = users.lookup_one('username', 'Omena0')
assert id, "Omena0 not in DB."

row = users.rows[id]
user_id = row['id']
assert user_id == ITERS*2, f"Invalid user ID: {user_id}, should be {ITERS*2}."

