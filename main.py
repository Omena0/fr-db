from datetime import datetime
from time import perf_counter

from fr_db import Database, Table, Row, Column, Index


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
    for i in range(ITERS*4):
        tx.add(Row(username=f'randomuser{i}'))

    tx.add(Row(username='Omena0'))

start = perf_counter()

# Increment 'Omena0's ID 10k times
# Create source table once and reuse - merge logic only evaluates the first source
with users.transaction() as tx:
    for _ in range(ITERS):
        tx.update(
            tx.where('username', 'Omena0')
                .transform_rows(['id'], lambda x: x+1)
        )

took = perf_counter() - start
print(f'Took {took:.4f} seconds')

# Make sure it took effect.
id = users.lookup_one('username', 'Omena0')
assert id, "Omena0 not in DB."

row = users.rows[id]
user_id = row['id']
assert user_id == ITERS*5, f"Invalid user ID: {user_id}, should be {ITERS*5}."


