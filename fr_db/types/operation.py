from enum import IntEnum, auto
from typing import Any, TYPE_CHECKING, Callable, Iterable, cast, Self
from .rowview import RowView

from ..errors import InvalidOperationType


if TYPE_CHECKING:
    from .table import Table
    from .row import Row


class OpType(IntEnum):
    WHERE = auto()
    TRANSFORM = auto()
    TRANSFORM_ROWS = auto()
    SELECT = auto()
    LIMIT = auto()
    SORT = auto()
    DISTINCT = auto()
    ADD = auto()
    UPDATE = auto()
    DELETE = auto()
    WHERE_TRANSFORM = auto()
    WHERE_SELECT = auto()
    TRANSFORM_SELECT = auto()
    WHERE_TRANSFORM_ROWS = auto()
    TRANSFORM_ROWS_SELECT = auto()
    TRANSFORM_TRANSFORM_ROWS = auto()
    WHERE_TRANSFORM_SELECT = auto()
    WHERE_TRANSFORM_ROWS_SELECT = auto()


_MERGEABLE = frozenset({
    OpType.ADD, OpType.DELETE, OpType.WHERE,
    OpType.TRANSFORM, OpType.TRANSFORM_ROWS, OpType.UPDATE,
})

def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value


def _wrap_filter_view(input_rows: RowView, result: dict[int, Row]) -> RowView:
    """Wrap result in a RowView using same base with non-matching rows marked deleted.

    This avoids copying rows for filtering operations (WHERE, LIMIT, DISTINCT).
    """
    deleted = set(input_rows._base.keys()) - set(result.keys()) # pyright: ignore[reportPrivateUsage]
    return RowView(input_rows._base, result, deleted) # pyright: ignore[reportPrivateUsage]


class Operation:
    __slots__ = ('type', 'key')
    def __init__(self, type: OpType, *key: Any):
        self.type = type
        self.key  = key

    def __repr__(self) -> str:
        return f'Operation({self.type.name}, *{self.key})'

    # Optimizer
    @classmethod
    def optimize(cls, ops: list[Operation]) -> list[Operation]:
        if len(ops) <= 1:
            return ops

        # Phase 1: Fuse compatible operations
        result = cls._fuse_ops(ops)

        # Phase 2: Merge consecutive same-type operations
        result = cls._merge_consecutive(result)

        # Phase 3: Push down operations for better performance
        result = cls._pushdown(result)

        return result

    @classmethod
    def _pushdown(cls, ops: list[Operation]) -> list[Operation]:
        """Reorder operations to improve performance."""
        result: list[Operation] = []
        i = 0
        n = len(ops)

        while i < n:
            op = ops[i]

            # Push LIMIT before SORT
            if op.type == OpType.LIMIT and i + 1 < n and ops[i + 1].type == OpType.SORT:
                result.extend(
                    (
                        Operation(
                            OpType.SORT, ops[i + 1].key[0], ops[i + 1].key[1]
                        ),
                        op,
                    )
                )
                i += 2
                continue

            # Push LIMIT before DISTINCT
            if op.type == OpType.LIMIT and i + 1 < n and ops[i + 1].type == OpType.DISTINCT:
                result.extend((ops[i + 1], op))
                i += 2
                continue

            result.append(op)
            i += 1

        return result

    @classmethod
    def _fuse_ops(cls, ops: list[Operation]) -> list[Operation]:
        """Fuse compatible operations to reduce passes over data."""
        result: list[Operation] = []
        i = 0
        n = len(ops)

        while i < n:
            op = ops[i]

            # Mutation ops (ADD, UPDATE, DELETE) can't be fused with anything
            if op.type not in (OpType.WHERE, OpType.TRANSFORM, OpType.TRANSFORM_ROWS, OpType.SELECT, OpType.LIMIT, OpType.SORT, OpType.DISTINCT):
                result.append(op)
                i += 1
                continue

            # Eliminate no-op limits (limit of 0 or negative = empty)
            if op.type == OpType.LIMIT and isinstance(op.key[0], int) and op.key[0] <= 0:
                # Return a marker that produces empty result
                return [Operation(OpType.LIMIT, 0)]

            # Try triple fusion: where + transform + select
            if (op.type == OpType.WHERE and i + 2 < n
                and ops[i + 1].type == OpType.TRANSFORM
                and ops[i + 2].type == OpType.SELECT):
                where_op = op
                transform_op = ops[i + 1]
                select_op = ops[i + 2]
                result.append(Operation(
                    OpType.WHERE_TRANSFORM_SELECT,
                    where_op.key[0] if len(where_op.key) == 1 else where_op.key,
                    transform_op.key,
                    select_op.key
                ))
                i += 3
                continue

            # Try triple fusion: where + transform_rows + select
            if (op.type == OpType.WHERE and i + 2 < n
                and ops[i + 1].type == OpType.TRANSFORM_ROWS
                and ops[i + 2].type == OpType.SELECT):
                where_op = op
                transform_rows_op = ops[i + 1]
                select_op = ops[i + 2]
                result.append(Operation(
                    OpType.WHERE_TRANSFORM_ROWS_SELECT,
                    where_op.key[0] if len(where_op.key) == 1 else where_op.key,
                    transform_rows_op.key,
                    select_op.key
                ))
                i += 3
                continue

            # Try to fuse where + transform
            if op.type == OpType.WHERE and i + 1 < n and ops[i + 1].type == OpType.TRANSFORM:
                where_op = op
                transform_op = ops[i + 1]
                result.append(Operation(
                    OpType.WHERE_TRANSFORM,
                    where_op.key[0] if len(where_op.key) == 1 else where_op.key,
                    transform_op.key
                ))
                i += 2
                continue

            # Try to fuse where + transform_rows
            if op.type == OpType.WHERE and i + 1 < n and ops[i + 1].type == OpType.TRANSFORM_ROWS:
                where_op = op
                transform_rows_op = ops[i + 1]
                result.append(Operation(
                    OpType.WHERE_TRANSFORM_ROWS,
                    where_op.key[0] if len(where_op.key) == 1 else where_op.key,
                    transform_rows_op.key
                ))
                i += 2
                continue

            # Try to fuse where + select
            if op.type == OpType.WHERE and i + 1 < n and ops[i + 1].type == OpType.SELECT:
                where_op = op
                select_op = ops[i + 1]
                result.append(Operation(
                    OpType.WHERE_SELECT,
                    where_op.key[0] if len(where_op.key) == 1 else where_op.key,
                    select_op.key
                ))
                i += 2
                continue

            # Try to fuse transform + select
            if op.type == OpType.TRANSFORM and i + 1 < n and ops[i + 1].type == OpType.SELECT:
                transform_op = op
                select_op = ops[i + 1]
                result.append(Operation(
                    OpType.TRANSFORM_SELECT,
                    transform_op.key,
                    select_op.key
                ))
                i += 2
                continue

            # Try to fuse transform_rows + select
            if op.type == OpType.TRANSFORM_ROWS and i + 1 < n and ops[i + 1].type == OpType.SELECT:
                transform_rows_op = op
                select_op = ops[i + 1]
                result.append(Operation(
                    OpType.TRANSFORM_ROWS_SELECT,
                    transform_rows_op.key,
                    select_op.key
                ))
                i += 2
                continue

            # Try to fuse transform + transform_rows
            if op.type == OpType.TRANSFORM and i + 1 < n and ops[i + 1].type == OpType.TRANSFORM_ROWS:
                transform_op = op
                transform_rows_op = ops[i + 1]
                result.append(Operation(
                    OpType.TRANSFORM_TRANSFORM_ROWS,
                    transform_op.key,
                    transform_rows_op.key
                ))
                i += 2
                continue

            # Limit chaining: take minimum
            if op.type == OpType.LIMIT and i + 1 < n and ops[i + 1].type == OpType.LIMIT:
                limit1 = op.key[0]
                limit2 = ops[i + 1].key[0]
                result.append(Operation(OpType.LIMIT, min(limit1, limit2)))
                i += 2
                continue

            # Select chaining: intersect columns
            if op.type == OpType.SELECT and i + 1 < n and ops[i + 1].type == OpType.SELECT:
                cols1 = set(op.key)
                cols2 = set(ops[i + 1].key)

                if intersection := cols1 & cols2:
                    result.append(Operation(OpType.SELECT, *intersection))

                else:
                    # No columns in common - return empty
                    result.append(Operation(OpType.SELECT))

                i += 2
                continue

            result.append(op)
            i += 1

        return result

    @classmethod
    def _merge_consecutive(cls, ops: list[Operation]) -> list[Operation]:
        """Merge consecutive operations of the same type."""
        if len(ops) <= 1:
            return ops

        result: list[Operation] = []
        i = 0
        n = len(ops)

        while i < n:
            op = ops[i]

            if op.type not in _MERGEABLE:
                result.append(op)
                i += 1
                continue

            # Collect all consecutive mergeable operations of the same type
            group = [op]
            j = i + 1
            while j < n and ops[j].type == op.type and (op.type != OpType.WHERE or (len(ops[j].key) == 1)):
                group.append(ops[j])
                j += 1

            if len(group) == 1:
                result.append(op)
            else:
                result.append(cls._merge_group(group))

            i = j

        return result

    @classmethod
    def _merge_group(cls, group: list[Operation]) -> Operation:
        op_type = group[0].type

        if op_type == OpType.ADD:
            rows:list[Row] = []
            for op in group:
                rows.extend(op.key)

            return Operation(OpType.ADD, *rows)

        elif op_type == OpType.DELETE:
            funcs = [op.key[0] for op in group]
            return Operation(OpType.DELETE, lambda r: any(f(r) for f in funcs)) # type: ignore

        elif op_type == OpType.WHERE:
            funcs = [op.key[0] for op in group]
            return Operation(OpType.WHERE, lambda r: all(f(r) for f in funcs)) # type: ignore

        elif op_type == OpType.TRANSFORM:
            funcs: list[Callable[..., Any]] = []
            for op in group:
                funcs.extend(op.key)

            return Operation(OpType.TRANSFORM, *funcs)

        elif op_type == OpType.TRANSFORM_ROWS:
            transforms: list[Any] = []

            transforms.extend(op.key for op in group)

            return Operation(OpType.TRANSFORM_ROWS, transforms)

        elif op_type == OpType.UPDATE:
            # Eagerly combine all source rows from multiple UPDATEs
            # All source tables have the same ops, so we evaluate once
            # For dependent UPDATEs, we apply the transformation N times
            from .tableview import TableView

            base_table: Table | None = None
            source_rows: dict[int, Row] | None = None
            n_updates = len(group)

            for op in group:
                source_table: Table = op.key[0]
                if base_table is None:
                    base_table = source_table
                    # Evaluate once - all source tables have same ops
                    source_rows = source_table.rows

            assert source_rows is not None
            assert base_table is not None

            # Get base rows reference (no copy yet)
            base_rows_ref = base_table._base._rows if isinstance(base_table, TableView) else base_table._rows  # pyright: ignore[reportPrivateUsage]

            # For dependent UPDATEs, we need to compute the final value
            # after applying the transformation N times.
            # We do this by computing the delta from base and multiplying by N
            # (works for additive transforms like x + 1 applied N times)
            combined_values: dict[int, dict[str, Any]] = {}

            for row_id, source_row in source_rows.items():
                base_row = base_rows_ref.get(row_id)
                if base_row is None:
                    continue

                combined_values[row_id] = {}
                for col, new_val in source_row.values.items():
                    base_val = base_row.values.get(col)
                    if base_val != new_val:
                        # Apply the transformation N times
                        # For additive: base + (new - base) * N
                        if isinstance(new_val, (int, float)) and isinstance(base_val, (int, float)):
                            delta = new_val - base_val
                            combined_values[row_id][col] = base_val + delta * n_updates
                        else:
                            # For non-numeric, just use the final value
                            combined_values[row_id][col] = new_val

            # Use RowView to overlay changes on base table's rows (no new Row objects)
            # Use _base._rows to avoid creating a RowView
            merged_rows = RowView(base_rows_ref, combined_values)
            merged_table = TableView(base_table, merged_rows)
            return Operation(OpType.UPDATE, merged_table)

        raise ValueError(f"Cannot merge {op_type}")

    # Normal ops
    def _where(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .rowview import RowView
        is_view = isinstance(rows, RowView)

        if len(self.key) == 1:
            key = self.key[0]
            assert callable(key)

            result = {id: row for id, row in rows.items() if key(row)}
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = self.key

        if callable(key):
            result = {id: row for id, row in rows.items() if key(row.values[column])}
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows:  # pyright: ignore[reportPrivateUsage]
            result = {id: table._rows[id] for id in matching}  # pyright: ignore[reportPrivateUsage]
            return _wrap_filter_view(rows, result) if is_view else result

        result = {id: rows[id] for id in matching if id in rows}
        return _wrap_filter_view(rows, result) if is_view else result

    def _transform(self, table: Table, rows: dict[int, Row] | RowView):
        # Iterate over snapshot to avoid double-applying when rows is a RowView
        for id, row in list(rows.items()):
            rows[id] = apply_all(self.key, row)
        return rows

    def _transform_rows(self, table: Table, rows: dict[int, Row] | RowView):
        from .rowview import RowView
        transforms = self.key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        is_view = isinstance(rows, RowView)
        for keys, func in transforms:
            if isinstance(keys, str):
                keys = [keys]

            for row_id, row in list(rows.items()):
                new_row = row.copy()
                for k in keys:
                    new_row.values[k] = func(new_row.values[k])
                if is_view:
                    rows[row_id] = new_row

        return rows

    def _select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .row import Row
        from .rowview import RowView

        assert all(isinstance(i, str) for i in self.key)

        table._columns = {  # pyright: ignore[reportPrivateUsage]
            key: table._columns[key]  # pyright: ignore[reportPrivateUsage]
            for key in self.key
        }

        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in self.key
        }

        is_view = isinstance(rows, RowView)
        result = {
            id: Row(
                id_=id,
                **{key: row.values[key] for key in self.key},
            )
            for id, row in rows.items()
        }
        return _wrap_filter_view(rows, result) if is_view else result

    def _limit(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .rowview import RowView
        assert isinstance(self.key[0], int)

        is_view = isinstance(rows, RowView)
        result = {
            row.id: row
            for row in list(rows.values())[:self.key[0]]
        }
        return _wrap_filter_view(rows, result) if is_view else result

    def _sort(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .rowview import RowView
        assert callable(self.key[0])
        assert isinstance(self.key[1], bool)

        key, reverse = self.key

        is_view = isinstance(rows, RowView)
        result = {
            row.id: row
            for row in sorted(
                rows.values(),
                key=key,
                reverse=reverse,
            )
        }
        return _wrap_filter_view(rows, result) if is_view else result

    def _distinct(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        from .rowview import RowView
        is_view = isinstance(rows, RowView)
        seen: set[tuple[Any, ...]] = set()
        unique_rows: list[Row] = []

        for row in rows.values():
            values = (
                tuple(row.values[k] for k in self.key)
                if self.key
                else tuple(row.values.values())
            )

            if values not in seen:
                seen.add(values)
                unique_rows.append(row)

        result = {row.id: row for row in unique_rows}
        return _wrap_filter_view(rows, result) if is_view else result

    def _add(self, table: Table, rows: dict[int, Row]) -> RowView:
        view = rows if isinstance(rows, RowView) else RowView(rows)

        from .row import Row as RowClass

        for row in self.key:
            # Use object.__new__ to avoid __init__ overhead and id conflict
            new_row = object.__new__(RowClass)
            new_row.values = row.values.copy()
            new_row.table = table
            new_row.id = row.id
            new_row.columns = table._columns # pyright: ignore[reportPrivateUsage]

            for col in table._default_columns: # pyright: ignore[reportPrivateUsage]
                if col.name not in new_row.values:
                    new_row.values[col.name] = new_row._get_default_value(col) # pyright: ignore[reportPrivateUsage]

            view[new_row.id] = new_row

        return view

    def _update(self, _t: Table,  rows: dict[int, Row]) -> RowView:
        source_table: Table = self.key[0]
        source_rows = source_table.rows

        if not source_rows:
            return rows if type(rows) is RowView else RowView(rows)

        view = rows if type(rows) is RowView else RowView(rows)

        for source_id, source in source_rows.items():
            current = view.get(source_id)
            if current is None:
                continue

            if any(current.values.get(k) != v for k, v in source.values.items()):
                # Store raw values dict in delta instead of copying the row
                # The RowView will lazily merge these values when accessed
                view[source_id] = source.values

        return view

    def _delete(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        key = self.key[0]
        to_delete = {id for id, row in rows.items() if key(row)}

        if isinstance(rows, RowView):
            view = rows
            for id in to_delete:
                row = view.pop(id)
                if not isinstance(row, Row):
                    row = self._materialize_row(table, row, id)
                for index in table.indexes.values():
                    index.remove(row)

            return view

        new_rows = rows.copy()
        for id in to_delete:
            row = new_rows.pop(id)
            for index in table.indexes.values():
                index.remove(row)

        return new_rows

    @staticmethod
    def _materialize_row(table: Table, values: dict[str, Any], row_id: int) -> Row:
        """Materialize a delta dict into a Row object."""
        from .row import Row
        base_row = table._rows.get(row_id)  # pyright: ignore[reportPrivateUsage]
        if base_row is not None:
            merged = base_row.values.copy()
            merged.update(values)
            row = base_row.copy(table)
            row.values = merged
            return row
        row = object.__new__(Row)
        row.values = values
        row.table = table
        row.columns = table._columns # pyright: ignore[reportPrivateUsage]
        row.id = row_id
        return row

    # Fused ops
    def _where_transform(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        """Fused where + transform: filter and transform in one pass."""
        from .rowview import RowView
        where_key, transform_funcs = self.key

        is_view = isinstance(rows, RowView)

        if callable(where_key):
            result = {id: apply_all(transform_funcs, row) for id, row in rows.items() if where_key(row)}
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = where_key
        if callable(key):
            result = {id: apply_all(transform_funcs, row) for id, row in rows.items() if key(row.values[column])}
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            result = {id: apply_all(transform_funcs, table._rows[id]) for id in matching} # pyright: ignore[reportPrivateUsage]
            return _wrap_filter_view(rows, result) if is_view else result

        result = {id: apply_all(transform_funcs, rows[id]) for id in matching if id in rows}
        return _wrap_filter_view(rows, result) if is_view else result

    def _where_select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        """Fused where + select: filter and project in one pass."""
        from .row import Row
        from .rowview import RowView

        where_key, columns = self.key

        table._columns = { # pyright: ignore[reportPrivateUsage]
            key: table._columns[key] # pyright: ignore[reportPrivateUsage]
            for key in columns
        }
        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in columns
        }

        is_view = isinstance(rows, RowView)

        if callable(where_key):
            result = {id: Row(id_=id, **{key: row.values[key] for key in columns}) for id, row in rows.items() if where_key(row)}
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = where_key
        if callable(key):
            result = {id: Row(id_=id, **{key: row.values[key] for key in columns}) for id, row in rows.items() if key(row.values[column])}
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            result = {id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) for id in matching} # pyright: ignore[reportPrivateUsage]
            return _wrap_filter_view(rows, result) if is_view else result

        result = {id: Row(id_=id, **{key: rows[id].values[key] for key in columns}) for id in matching if id in rows}
        return _wrap_filter_view(rows, result) if is_view else result

    def _transform_select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        """Fused transform + select: transform and project in one pass."""
        from .row import Row
        from .rowview import RowView

        transform_funcs, columns = self.key

        table._columns = { # pyright: ignore[reportPrivateUsage]
            key: table._columns[key] # pyright: ignore[reportPrivateUsage]
            for key in columns
        }
        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in columns
        }

        is_view = isinstance(rows, RowView)
        result = {
            id: Row(id_=id, **{key: row.values[key] for key in columns})
            for id, row in rows.items()
            for row in [apply_all(transform_funcs, row)]
        }
        return _wrap_filter_view(rows, result) if is_view else result

    # Triple fused ops
    def _where_transform_rows(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row]:
        """Fused where + transform_rows: filter and transform in one pass."""
        from .rowview import RowView
        where_key, transform_key = self.key

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        is_view = isinstance(rows, RowView)

        def apply_transforms(row: Row) -> Row:
            new_row = row.copy() if is_view else row
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    new_row.values[k] = func(new_row.values[k])
            return new_row

        if callable(where_key):
            result = {id: apply_transforms(row) for id, row in rows.items() if where_key(row)}
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = where_key
        if callable(key):
            result = {id: apply_transforms(row) for id, row in rows.items() if key(row.values[column])}
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            result = {id: apply_transforms(table._rows[id]) for id in matching} # pyright: ignore[reportPrivateUsage]
            return _wrap_filter_view(rows, result) if is_view else result

        result = {id: apply_transforms(rows[id]) for id in matching if id in rows}
        return _wrap_filter_view(rows, result) if is_view else result

    def _transform_rows_select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row]:
        """Fused transform_rows + select: transform and project in one pass."""
        from .row import Row
        from .rowview import RowView

        transform_key, columns = self.key

        table._columns = { # pyright: ignore[reportPrivateUsage]
            key: table._columns[key] # pyright: ignore[reportPrivateUsage]
            for key in columns
        }
        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in columns
        }

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        is_view = isinstance(rows, RowView)
        result: dict[int, Row] = {}
        for id, row in rows.items():
            new_row = row.copy() if is_view else row
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    new_row.values[k] = func(new_row.values[k])
            result[id] = Row(id_=id, **{key: new_row.values[key] for key in columns})

        return _wrap_filter_view(rows, result) if is_view else result

    def _transform_transform_rows(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row]:
        """Fused transform + transform_rows: apply both transforms in one pass."""
        from .rowview import RowView
        transform_funcs, transform_key = self.key

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        is_view = isinstance(rows, RowView)
        result: dict[int, Row] = {}
        for id, row in rows.items():
            row = apply_all(transform_funcs, row)
            if is_view and row is rows.get(id):
                    row = row.copy()
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    row.values[k] = func(row.values[k])
            result[id] = row

        return _wrap_filter_view(rows, result) if is_view else result

    def _where_transform_select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row] | RowView:
        """Fused where + transform + select: filter, transform, project in one pass."""
        from .row import Row
        from .rowview import RowView

        where_key, transform_funcs, columns = self.key

        table._columns = { # pyright: ignore[reportPrivateUsage]
            key: table._columns[key] # pyright: ignore[reportPrivateUsage]
            for key in columns
        }
        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in columns
        }

        is_view = isinstance(rows, RowView)

        if callable(where_key):
            result = {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if where_key(row)
                for row in [apply_all(transform_funcs, row)]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = where_key
        if callable(key):
            result = {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if key(row.values[column])
                for row in [apply_all(transform_funcs, row)]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            result = {
                id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) # pyright: ignore[reportPrivateUsage]
                for id in matching
                for _ in [apply_all(transform_funcs, table._rows[id])] # pyright: ignore[reportPrivateUsage]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        result = {
            id: Row(id_=id, **{key: rows[id].values[key] for key in columns})
            for id in matching
            if id in rows
            for _ in [apply_all(transform_funcs, rows[id])]
        }
        return _wrap_filter_view(rows, result) if is_view else result

    def _where_transform_rows_select(self, table: Table, rows: dict[int, Row] | RowView) -> dict[int, Row]:
        """Fused where + transform_rows + select: filter, transform, project in one pass."""
        from .row import Row
        from .rowview import RowView

        where_key, transform_key, columns = self.key

        table._columns = { # pyright: ignore[reportPrivateUsage]
            key: table._columns[key] # pyright: ignore[reportPrivateUsage]
            for key in columns
        }
        table.indexes = {
            column: index
            for column, index in table.indexes.items()
            if column in columns
        }

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        is_view = isinstance(rows, RowView)

        def apply_transforms(row: Row) -> Row:
            new_row = row.copy() if is_view else row
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    new_row.values[k] = func(new_row.values[k])
            return new_row

        if callable(where_key):
            result = {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if where_key(row)
                for row in [apply_transforms(row)]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        column, key = where_key
        if callable(key):
            result = {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if key(row.values[column])
                for row in [apply_transforms(row)]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            result = {
                id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) # pyright: ignore[reportPrivateUsage]
                for id in matching
                for _row in [apply_transforms(table._rows[id])] # pyright: ignore[reportPrivateUsage]
            }
            return _wrap_filter_view(rows, result) if is_view else result

        result = {
            id: Row(id_=id, **{key: rows[id].values[key] for key in columns})
            for id in matching
            if id in rows
            for _row in [apply_transforms(rows[id])]
        }
        return _wrap_filter_view(rows, result) if is_view else result

    map: dict[OpType, Callable[[Self, Table, dict[int, Row]], dict[int, Row] | RowView]] = {
        OpType.WHERE: _where,
        OpType.TRANSFORM: _transform,
        OpType.TRANSFORM_ROWS: _transform_rows,
        OpType.SELECT: _select,
        OpType.LIMIT: _limit,
        OpType.SORT: _sort,
        OpType.DISTINCT: _distinct,
        OpType.ADD: _add,
        OpType.UPDATE: _update,
        OpType.DELETE: _delete,
        OpType.WHERE_TRANSFORM: _where_transform,
        OpType.WHERE_SELECT: _where_select,
        OpType.TRANSFORM_SELECT: _transform_select,
        OpType.WHERE_TRANSFORM_ROWS: _where_transform_rows,
        OpType.TRANSFORM_ROWS_SELECT: _transform_rows_select,
        OpType.TRANSFORM_TRANSFORM_ROWS: _transform_transform_rows,
        OpType.WHERE_TRANSFORM_SELECT: _where_transform_select,
        OpType.WHERE_TRANSFORM_ROWS_SELECT: _where_transform_rows_select,
    }

    def apply(self, table: Table):
        rows = table._rows  # pyright: ignore[reportPrivateUsage]

        func = Operation.map.get(self.type)

        if not func:
            raise InvalidOperationType(f"Unknown operation type: {self.type}")

        new_rows = func(self, table, rows)

        # Collapse RowView to actual dict for storage
        if isinstance(new_rows, RowView):
            new_rows = new_rows.collapse()

        table._rows = new_rows  # type: ignore

