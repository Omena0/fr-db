"""Benchmark for _update optimization."""
import time
from fr_db import Table, Row, Column


def make_large_table(n_rows: int) -> Table:
    """Create a table with many rows and an indexed column."""
    return Table(
        None,
        "bench",
        [Row(username=f"user_{i}", age=i % 100) for i in range(n_rows)],
        [
            Column("id", int, ["primary", "autoinc"]),
            Column("username", str),
            Column("age", int),
        ],
    )


def bench_sequential_updates_simple(n_rows: int, n_updates: int, n_iters: int = 5) -> float:
    """Benchmark sequential UPDATEs with simple source tables (no pending ops)."""
    times = []
    for _ in range(n_iters):
        table = make_large_table(n_rows)

        with table.transaction() as tx:
            start = time.perf_counter()
            # Create source tables with no pending operations
            chunk_size = n_rows // n_updates
            for u in range(n_updates):
                s = u * chunk_size
                e = s + chunk_size
                source_rows = {
                    row.id: Row(
                        None, id_=row.id, username=f"updated_{row['username']}"
                    )
                    for row in tx.where(
                        lambda r, s=s, e=e: s <= r["id"] < e
                    ).rows.values()
                }
                source_table = Table(None, f"source_{u}", rows=source_rows, _data_is_valid=True)
                tx.update(source_table)
            # Force evaluation
            _ = len(tx.rows)
            end = time.perf_counter()

        times.append(end - start)

    return min(times)


def bench_sequential_updates_with_ops(n_rows: int, n_updates: int, n_iters: int = 5) -> float:
    """Benchmark sequential UPDATEs with source tables that have pending ops."""
    times = []
    for _ in range(n_iters):
        table = make_large_table(n_rows)

        with table.transaction() as tx:
            start = time.perf_counter()
            chunk_size = n_rows // n_updates
            for u in range(n_updates):
                s = u * chunk_size
                e = s + chunk_size
                tx.update(
                    tx.where(lambda r, s=s, e=e: s <= r["id"] < e)
                    .transform(
                        lambda r: r.transform("username", lambda v: f"updated_{v}"),
                    )
                )
            # Force evaluation
            _ = len(tx.rows)
            end = time.perf_counter()

        times.append(end - start)

    return min(times)


def bench_update_no_changes(n_rows: int, n_iters: int = 5) -> float:
    """Benchmark update where no values actually change."""
    times = []
    for _ in range(n_iters):
        table = make_large_table(n_rows)

        with table.transaction() as tx:
            start = time.perf_counter()
            tx.update(
                tx.where(lambda r: True)
                .transform(
                    lambda r: r.transform("username", lambda v: v),
                )
            )
            _ = len(tx.rows)
            end = time.perf_counter()

        times.append(end - start)

    return min(times)


def bench_single_update(n_rows: int, n_iters: int = 5) -> float:
    """Benchmark a single UPDATE operation."""
    times = []
    for _ in range(n_iters):
        table = make_large_table(n_rows)

        with table.transaction() as tx:
            start = time.perf_counter()
            tx.update(
                tx.where(lambda r: r["id"] < n_rows // 2)
                .transform(
                    lambda r: r.transform("username", lambda v: f"updated_{v}"),
                )
            )
            _ = len(tx.rows)
            end = time.perf_counter()

        times.append(end - start)

    return min(times)


if __name__ == "__main__":
    print("Benchmarking _update optimization...")
    print()

    for n_rows in [1000, 5000, 10000]:
        print(f"Table size: {n_rows} rows")

        # Single update
        t = bench_single_update(n_rows)
        print(f"  Single update (50% rows):      {t*1000:.2f} ms")

        # No-op update
        t = bench_update_no_changes(n_rows)
        print(f"  No-op update (identity):       {t*1000:.2f} ms")

        # Sequential updates with pending ops (WHERE + TRANSFORM)
        for n_updates in [3, 5, 10]:
            t = bench_sequential_updates_with_ops(n_rows, n_updates)
            print(f"  {n_updates} updates (with ops):     {t*1000:.2f} ms")

        # Sequential updates with simple source tables (no pending ops)
        for n_updates in [3, 5, 10]:
            t = bench_sequential_updates_simple(n_rows, n_updates)
            print(f"  {n_updates} updates (simple src):   {t*1000:.2f} ms")

        print()
