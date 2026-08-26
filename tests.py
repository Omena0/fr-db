import pytest
from datetime import datetime

from fr_db import Database, Table, Row, Column


def make_users() -> Table:
    db = Database()

    return Table(
        db,
        "users",
        [
            Row(username="C"),
            Row(username="D"),
            Row(username="C"),
            Row(username="B"),
            Row(username="B"),
            Row(username="A"),
            Row(username="D"),
            Row(username="E"),
            Row(username="A"),
            Row(username="E"),
            Row(username="E"),
        ],
        [
            Column("id", int, ["primary", "autoinc"]),
            Column("username", str),
            Column("created_at", datetime, default=datetime.now),
        ],
    )


def row_by_id(table: Table, value: int) -> Row:
    return next(
        row for row in table.rows.values()
        if row["id"] == value
    )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_table_creation():
    table = make_users()

    assert table.name == "users"
    assert len(table.rows) == 11

    rows = list(table.rows.values())

    assert [row["id"] for row in rows] == list(range(11))
    assert [row["username"] for row in rows] == [
        "C", "D", "C", "B", "B", "A", "D", "E", "A", "E", "E"
    ]

    for row in rows:
        assert row.table is table
        assert isinstance(row["id"], int)
        assert isinstance(row["username"], str)
        assert isinstance(row["created_at"], datetime)


def test_autoincrement():
    table = make_users()

    assert [row["id"] for row in table.rows.values()] == list(range(11))


def test_default_factory():
    table = make_users()

    timestamps = [row["created_at"] for row in table.rows.values()]

    assert len(timestamps) == 11
    assert all(isinstance(value, datetime) for value in timestamps)

def test_default_factory_is_called_per_row():
    calls = 0

    def factory():
        nonlocal calls
        calls += 1
        return calls

    table = Table(
        None,
        "test",
        [Row(), Row(), Row()],
        [
            Column("value", int, default=factory),
        ],
    )

    assert calls == 3
    assert [row["value"] for row in table.rows.values()] == [1, 2, 3]

# ---------------------------------------------------------------------------
# Query operations
# ---------------------------------------------------------------------------

def test_where():
    table = make_users()

    result = table.where(lambda r: r["id"] % 2 == 0)

    assert [row["id"] for row in result.rows.values()] == [
        0, 2, 4, 6, 8, 10
    ]


def test_transform():
    table = make_users()

    result = table.transform(
        lambda r: r.transform("id", lambda value: value + 10)
    )

    assert [row["id"] for row in result.rows.values()] == list(range(10, 21))


def test_transform_multiple_columns():
    table = make_users()

    result = table.transform(
        lambda r: r.transform(
            ["id", "username"],
            lambda value: value + 10
            if isinstance(value, int)
            else value.upper(),
        )
    )

    rows = list(result.rows.values())

    assert rows[0]["id"] == 10
    assert rows[0]["username"] == "C"


def test_select():
    table = make_users()

    result = table.select("id", "username")

    assert list(result.columns.keys()) == ["id", "username" ]

    for row in result.rows.values():
        assert set(row.values.keys()) == {"id", "username"}


def test_limit():
    table = make_users()

    result = table.limit(3)

    assert len(result.rows) == 3
    assert [row["id"] for row in result.rows.values()] == [0, 1, 2]


def test_sort():
    table = make_users()

    result = table.sort(lambda r: r["id"], reverse=True)

    assert [row["id"] for row in result.rows.values()] == list(
        range(10, -1, -1)
    )


def test_distinct():
    table = make_users()

    result = table.distinct("username")

    assert [row["username"] for row in result.rows.values()] == [
        "C", "D", "B", "A", "E"
    ]


def test_query_chaining():
    table = make_users()

    result = (
        table
        .where(lambda r: r["id"] % 2)
        .transform(
            lambda r: r.transform("id", lambda value: value + 6)
        )
        .sort(lambda r: r["id"], reverse=True)
        .select("id", "username")
        .distinct("username")
        .limit(3)
    )

    rows = list(result.rows.values())

    assert [row.values for row in rows] == [
        {"id": 15, "username": "E"},
        {"id": 11, "username": "A"},
        {"id": 9, "username": "B"},
    ]


def test_lazy_evaluation():
    table = make_users()

    result = table.where(lambda r: r["id"] > 5)

    # The query has not been applied yet.
    assert result.operations  # pyright: ignore[reportPrivateUsage]
    assert len(result._rows) == 11  # pyright: ignore[reportPrivateUsage]

    result.rows

    assert len(result._rows) == 5  # pyright: ignore[reportPrivateUsage]
    assert [row["id"] for row in result.rows.values()] == [
        6, 7, 8, 9, 10
    ]


def test_lazy_operations_clear_after_apply():
    table = make_users()

    result = table.where(lambda r: r["id"] > 5)

    assert result.operations  # pyright: ignore[reportPrivateUsage]

    result.rows

    assert not result.operations  # pyright: ignore[reportPrivateUsage]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_add():
    table = make_users()

    with table.transaction() as tx:
        tx.add(Row(username="Z"))

        assert len(tx.rows) == 12

        added = list(tx.rows.values())[-1]

        assert added["id"] == 11
        assert added["username"] == "Z"

    assert len(table.rows) == 12
    assert row_by_id(table, 11)["username"] == "Z"

def test_update():
    table = make_users()

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "Z",
                )
            )
        )

        assert row_by_id(tx, 0)["username"] == "Z"

    assert row_by_id(table, 0)["username"] == "Z"
    assert row_by_id(table, 1)["username"] == "D"

def test_update_multiple_rows():
    table = make_users()

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["username"] == "C")
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "Z",
                )
            )
        )

    assert row_by_id(table, 0)["username"] == "Z"
    assert row_by_id(table, 2)["username"] == "Z"
    assert row_by_id(table, 1)["username"] == "D"

def test_update_partial_row():
    table = make_users()

    original_date = row_by_id(table, 0)["created_at"]

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .select("username")
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "Z",
                )
            )
        )

    row = row_by_id(table, 0)

    assert row["username"] == "Z"
    assert row["id"] == 0
    assert row["created_at"] == original_date

def test_update_can_change_primary_key():
    table = make_users()

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .transform(
                lambda r: r.transform(
                    "id",
                    lambda value: value + 11,
                )
            )
        )

    row = row_by_id(table, 11)

    assert row["id"] == 11
    assert row["username"] == "C"

    # The internal row ID must remain the same.
    assert row.id in table.rows

def test_delete():
    table = make_users()

    with table.transaction() as tx:
        tx.delete(lambda r: r["id"] % 2 == 0)

        assert [row["id"] for row in tx.rows.values()] == [
            1, 3, 5, 7, 9
        ]

    assert [row["id"] for row in table.rows.values()] == [
        1, 3, 5, 7, 9
    ]


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def test_transaction_is_isolated():
    table = make_users()

    with table.transaction() as tx:
        tx.add(Row(username="Z"))

        assert len(tx.rows) == 12
        assert len(table._rows) == 11 # pyright: ignore[reportPrivateUsage]

    assert len(table.rows) == 12


def test_transaction_commit():
    table = make_users()

    with table.transaction() as tx:
        tx.add(Row(username="Z"))

    assert len(table.rows) == 12
    assert row_by_id(table, 11)["username"] == "Z"


def test_transaction_abort():
    table = make_users()

    with table.transaction() as tx:
        tx.add(Row(username="Z"))
        tx.abort()

    assert len(table.rows) == 11
    assert all(
        row["username"] != "Z"
        for row in table.rows.values()
    )


def test_transaction_rollback_on_exception():
    table = make_users()

    with pytest.raises(RuntimeError):
        with table.transaction() as tx:
            tx.add(Row(username="Z"))
            raise RuntimeError("skill issue")

    assert len(table.rows) == 11
    assert all(
        row["username"] != "Z"
        for row in table.rows.values()
    )


def test_transaction_catches_exception():
    table = make_users()

    with table.transaction(catch_exc=True) as tx:
        tx.add(Row(username="Z"))
        raise RuntimeError("skill issue")

    assert len(table.rows) == 11
    assert all(
        row["username"] != "Z"
        for row in table.rows.values()
    )


def test_transaction_commit_after_multiple_mutations():
    table = make_users()

    with table.transaction() as tx:
        tx.add(Row(username="Z"))

        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "X",
                )
            )
        )

        tx.delete(lambda r: r["id"] == 1)

    assert len(table.rows) == 11
    assert row_by_id(table, 0)["username"] == "X"
    assert 1 not in table.rows
    assert row_by_id(table, 11)["username"] == "Z"


# ---------------------------------------------------------------------------
# Copying
# ---------------------------------------------------------------------------

def test_copy():
    table = make_users()
    copied = table.copy()

    assert copied is not table
    assert copied.database is None
    assert copied.rows is not table.rows
    assert copied.columns is not table.columns

    assert [row.values for row in copied.rows.values()] == [
        row.values for row in table.rows.values()
    ]


def test_copy_preserves_row_identity():
    table = make_users()
    copied = table.copy()

    original_rows = list(table.rows.values())
    copied_rows = list(copied.rows.values())

    assert [row.id for row in copied_rows] == [
        row.id for row in original_rows
    ]


def test_copy_is_independent():
    table = make_users()
    copied = table.copy()

    copied.rows[next(iter(copied.rows))].values["username"] = "CHANGED"

    assert row_by_id(table, 0)["username"] == "C"
    assert row_by_id(copied, 0)["username"] == "CHANGED"


def test_rcopy():
    table = make_users()
    copied = Table(None, "copied")

    copied.rcopy(table)

    assert [row.values for row in copied.rows.values()] == [
        row.values for row in table.rows.values()
    ]


def test_rcopy_preserves_row_identity():
    table = make_users()
    copied = Table(None, "copied")

    copied.rcopy(table)

    assert set(copied.rows) == set(table.rows)
    assert [row.id for row in copied.rows.values()] == [
        row.id for row in table.rows.values()
    ]


def test_rcopy_is_independent():
    table = make_users()
    copied = Table(None, "copied")

    copied.rcopy(table)

    copied.rows[next(iter(copied.rows))].values["username"] = "CHANGED"

    assert row_by_id(table, 0)["username"] == "C"
    assert row_by_id(copied, 0)["username"] == "CHANGED"


# ---------------------------------------------------------------------------
# Regression tests
# ---------------------------------------------------------------------------

def test_update_does_not_update_wrong_row_after_filter():
    table = make_users()

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "Z",
                )
            )
        )

    assert row_by_id(table, 0)["username"] == "Z"
    assert row_by_id(table, 1)["username"] == "D"


def test_update_does_not_depend_on_primary_key():
    table = make_users()

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .transform(
                lambda r: r.transform(
                    "id",
                    lambda _: 999,
                )
            )
        )

    assert row_by_id(table, 999)["id"] == 999
    assert row_by_id(table, 999)["username"] == "C"
    assert row_by_id(table, 1)["id"] == 1


def test_update_preserves_unselected_columns():
    table = make_users()

    before = row_by_id(table, 0)["created_at"]

    with table.transaction() as tx:
        tx.update(
            tx.where(lambda r: r["id"] == 0)
            .select("username")
            .transform(
                lambda r: r.transform(
                    "username",
                    lambda _: "Z",
                )
            )
        )

    row = row_by_id(table, 0)

    assert row["username"] == "Z"
    assert row["id"] == 0
    assert row["created_at"] == before


# ---------------------------------------------------------------------------
# Progress / execution
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main(
        [
            __file__,
            '-q'
        ]
    )
