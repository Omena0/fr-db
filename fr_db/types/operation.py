from enum import IntEnum, auto
from typing import Any, TYPE_CHECKING, Callable, Generator, Iterable, cast, Self

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
    OpType.TRANSFORM, OpType.TRANSFORM_ROWS,
})

class _RowView:
    """Dict-like view overlaying a delta on top of a base dict.

    Avoids copying the entire rows dict when only a few rows change.
    Reads check _delta first, then fall back to _base.
    """
    __slots__ = ('_base', '_delta', '_deleted', '_len')

    def __init__(self, base: dict[int, Row], delta: dict[int, Row] | None = None, deleted: set[int] | None = None):
        self._base = base
        self._delta = delta if delta is not None else {}
        self._deleted: set[int] = deleted if deleted is not None else set()

        # Track length incrementally to avoid O(n) computation
        self._len = len(base) + len(self._delta) - len(self._deleted)

    def __getitem__(self, key: int) -> Row:
        if key in self._deleted:
            raise KeyError(key)

        return self._delta[key] if key in self._delta else self._base[key]

    def __setitem__(self, key: int, value: Row) -> None:
        in_base = key in self._base
        in_deleted = key in self._deleted

        self._delta[key] = value
        self._deleted.discard(key)

        # Length changes only when adding a new key or restoring a deleted one
        if in_deleted or not in_base:
            self._len += 1

    def __delitem__(self, key: int) -> None:
        in_delta = key in self._delta
        in_base = key in self._base

        if in_delta:
            del self._delta[key]
        self._deleted.add(key)

        # Length changes when removing a visible key
        if in_delta or in_base:
            self._len -= 1

    def __contains__(self, key: int) -> bool:
        if key in self._deleted:
            return False
        return key in self._delta or key in self._base

    def __len__(self) -> int:
        return self._len

    def __iter__(self):
        seen: set[int] = set()
        for key in self._base:
            if key not in self._deleted and key not in self._delta:
                seen.add(key)
                yield key
        for key in self._delta:
            if key not in seen:
                yield key

    def get(self, key: int, default: Row | None = None) -> Row | None:
        if key in self._deleted:
            return default

        return self._delta[key] if key in self._delta else self._base.get(key, default)

    def items(self) -> Generator[tuple[int, Row], Any, None]:
        for key in self:
            yield key, self[key]

    def values(self):
        for key in self:
            yield self[key]

    def keys(self):
        result = set(self._base.keys()) - self._deleted
        result |= set(self._delta.keys())
        return result

    def copy(self) -> dict[int, Row]:
        return dict(self.items())

    def pop(self, key: int, *args: Any) -> Row:
        if key in self._delta:
            value = self._delta.pop(key)
            self._deleted.discard(key)
            return value

        if key in self._deleted:
            if args:
                return args[0]
            raise KeyError(key)

        if key in self._base:
            self._deleted.add(key)
            return self._base[key]

        if args:
            return args[0]

        raise KeyError(key)

def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value

class Operation:
    __slots__ = ['type', 'key']
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

        raise ValueError(f"Cannot merge {op_type}")

    # Normal ops
    def _where(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        if len(self.key) == 1:
            key = self.key[0]
            assert callable(key)

            return {
                id: row
                for id, row in rows.items()
                if key(row)
            }

        column, key = self.key

        if callable(key):
            return {
                id: row
                for id, row in rows.items()
                if key(row.values[column])
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows:  # pyright: ignore[reportPrivateUsage]
            return {id: table._rows[id] for id in matching}  # pyright: ignore[reportPrivateUsage]

        return {
            id: rows[id]
            for id in matching
            if id in rows
        }

    def _transform(self, table: Table, rows: dict[int, Row]):
        for id, row in rows.items():
            rows[id] = apply_all(self.key, row)

        return rows

    def _transform_rows(self, table: Table, rows: dict[int, Row]):
        transforms = self.key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        for keys, func in transforms:
            if isinstance(keys, str):
                keys = [keys]

            for row in rows.values():
                for k in keys:
                    row.values[k] = func(row.values[k])

        return rows

    def _select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        from .row import Row

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

        return {
            id: Row(
                id_=id,
                **{key: row.values[key] for key in self.key},
            )
            for id, row in rows.items()
        }

    def _limit(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        assert isinstance(self.key[0], int)

        return {
            row.id: row
            for row in list(rows.values())[:self.key[0]]
        }

    def _sort(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        assert callable(self.key[0])
        assert isinstance(self.key[1], bool)

        key, reverse = self.key

        return {
            row.id: row
            for row in sorted(
                rows.values(),
                key=key,
                reverse=reverse,
            )
        }

    def _distinct(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
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

        return {
            row.id: row
            for row in unique_rows
        }

    def _add(self, table: Table, rows: dict[int, Row]) -> _RowView:
        view = rows if isinstance(rows, _RowView) else _RowView(rows)

        for row in self.key:
            row = row.copy(table)
            row.table = table

            for col in table._default_columns: # pyright: ignore[reportPrivateUsage]
                if col.name not in row.values:
                    row.values[col.name] = row._get_default_value(col) # pyright: ignore[reportPrivateUsage]

            view[row.id] = row

            for index in table.indexes.values():
                index.add(row)

        return view

    def _update(self, table: Table, rows: dict[int, Row]) -> _RowView:
        source_table: Table = self.key[0]
        source_rows = source_table.rows

        view = rows if isinstance(rows, _RowView) else _RowView(rows)

        for source_id, source in source_rows.items():
            current = view.get(source_id)
            if current is None:
                continue

            current = current.copy(table)
            view[source_id] = current

            old_values = {
                column: current.values[column]
                for column in table.indexes
            }

            current.values.update(source.values)

            for column, old_value in old_values.items():
                new_value = current.values[column]
                if old_value != new_value:
                    table.indexes[column].update(
                        old_value,
                        new_value,
                        current.id,
                    )

        return view

    def _delete(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        key = self.key[0]
        to_delete = {id for id, row in rows.items() if key(row)}

        if isinstance(rows, _RowView):
            view = rows
            for id in to_delete:
                row = view.pop(id)
                for index in table.indexes.values():
                    index.remove(row)
            return view

        new_rows = rows.copy()
        for id in to_delete:
            row = new_rows.pop(id)
            for index in table.indexes.values():
                index.remove(row)

        return new_rows

    # Fused ops
    def _where_transform(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused where + transform: filter and transform in one pass."""
        where_key, transform_funcs = self.key

        if callable(where_key):
            return {
                id: apply_all(transform_funcs, row)
                for id, row in rows.items()
                if where_key(row)
            }

        column, key = where_key
        if callable(key):
            return {
                id: apply_all(transform_funcs, row)
                for id, row in rows.items()
                if key(row.values[column])
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            return {id: apply_all(transform_funcs, table._rows[id]) for id in matching} # pyright: ignore[reportPrivateUsage]

        return {
            id: apply_all(transform_funcs, rows[id])
            for id in matching
            if id in rows
        }

    def _where_select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused where + select: filter and project in one pass."""
        from .row import Row

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

        if callable(where_key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if where_key(row)
            }

        column, key = where_key
        if callable(key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if key(row.values[column])
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            return {
                id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) # pyright: ignore[reportPrivateUsage]
                for id in matching
            }

        return {
            id: Row(id_=id, **{key: rows[id].values[key] for key in columns})
            for id in matching
            if id in rows
        }

    def _transform_select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused transform + select: transform and project in one pass."""
        from .row import Row

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

        return {
            id: Row(id_=id, **{key: row.values[key] for key in columns})
            for id, row in rows.items()
            for row in [apply_all(transform_funcs, row)]
        }

    # Triple fused ops
    def _where_transform_rows(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused where + transform_rows: filter and transform in one pass."""
        where_key, transform_key = self.key

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        def apply_transforms(row: Row) -> Any:
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    row.values[k] = func(row.values[k])
            return row

        if callable(where_key):
            return {
                id: apply_transforms(row)
                for id, row in rows.items()
                if where_key(row)
            }

        column, key = where_key
        if callable(key):
            return {
                id: apply_transforms(row)
                for id, row in rows.items()
                if key(row.values[column])
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            return {id: apply_transforms(table._rows[id]) for id in matching} # pyright: ignore[reportPrivateUsage]

        return {
            id: apply_transforms(rows[id])
            for id in matching
            if id in rows
        }

    def _transform_rows_select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused transform_rows + select: transform and project in one pass."""
        from .row import Row

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

        result: dict[int, Row] = {}
        for id, row in rows.items():
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    row.values[k] = func(row.values[k])
            result[id] = Row(id_=id, **{key: row.values[key] for key in columns})

        return result

    def _transform_transform_rows(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused transform + transform_rows: apply both transforms in one pass."""
        transform_funcs, transform_key = self.key

        transforms = transform_key
        if len(transforms) == 2 and not isinstance(transforms[0], tuple):
            transforms = [transforms]

        result: dict[int, Row] = {}
        for id, row in rows.items():
            row = apply_all(transform_funcs, row)
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    row.values[k] = func(row.values[k])
            result[id] = row

        return result

    def _where_transform_select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused where + transform + select: filter, transform, project in one pass."""
        from .row import Row

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

        if callable(where_key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if where_key(row)
                for row in [apply_all(transform_funcs, row)]
            }

        column, key = where_key
        if callable(key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if key(row.values[column])
                for row in [apply_all(transform_funcs, row)]
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            return {
                id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) # pyright: ignore[reportPrivateUsage]
                for id in matching
                for _ in [apply_all(transform_funcs, table._rows[id])] # pyright: ignore[reportPrivateUsage]
            }

        return {
            id: Row(id_=id, **{key: rows[id].values[key] for key in columns})
            for id in matching
            if id in rows
            for _ in [apply_all(transform_funcs, rows[id])]
        }

    def _where_transform_rows_select(self, table: Table, rows: dict[int, Row]) -> dict[int, Row]:
        """Fused where + transform_rows + select: filter, transform, project in one pass."""
        from .row import Row

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

        def apply_transforms(row: Row) -> Row:
            for keys, func in transforms:
                if isinstance(keys, str):
                    keys = [keys]
                for k in keys:
                    row.values[k] = func(row.values[k])
            return row

        if callable(where_key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if where_key(row)
                for row in [apply_transforms(row)]
            }

        column, key = where_key
        if callable(key):
            return {
                id: Row(id_=id, **{key: row.values[key] for key in columns})
                for id, row in rows.items()
                if key(row.values[column])
                for row in [apply_transforms(row)]
            }

        if isinstance(key, Iterable) and not isinstance(key, (str, bytes, dict)):
            matching = table.lookup_many(column, cast(Iterable[Any], key))
        else:
            matching = table.lookup(column, key)

        if rows is table._rows: # pyright: ignore[reportPrivateUsage]
            return {
                id: Row(id_=id, **{key: table._rows[id].values[key] for key in columns}) # pyright: ignore[reportPrivateUsage]
                for id in matching
                for _row in [apply_transforms(table._rows[id])] # pyright: ignore[reportPrivateUsage]
            }

        return {
            id: Row(id_=id, **{key: rows[id].values[key] for key in columns})
            for id in matching
            if id in rows
            for _row in [apply_transforms(rows[id])]
        }

    map: dict[OpType, Callable[[Self, Table, dict[int, Row]], dict[int, Row] | _RowView]] = {
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

        table._rows = new_rows  # type: ignore

