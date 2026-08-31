from typing import TYPE_CHECKING, Generator, Any

if TYPE_CHECKING:
    from .row import Row


class RowView(dict[int, 'Row']):
    """Dict-like view overlaying a delta on top of a base dict.

    Avoids copying the entire rows dict when only a few rows change.
    Reads check _delta first, then fall back to _base.

    The delta can be either:
    - dict[int, Row]: Row objects (for modified rows)
    - dict[int, dict[str, Any]]: Raw values (for merged updates, avoids creating Row objects)
    """
    __slots__ = ('_base', '_delta', '_deleted', '_len')

    def __init__(self, base: dict[int, Row], delta: dict[int, Row] | dict[int, dict[str, Any]] | None = None, deleted: set[int] | None = None):
        self._base = base
        self._delta = delta if delta is not None else {}
        self._deleted: set[int] = deleted if deleted is not None else set()

        # Track length incrementally to avoid O(n) computation
        # Visible rows = base rows not deleted and not in delta + all delta rows
        base_keys = set(base.keys())
        delta_keys = set(self._delta.keys())
        visible_base = len(base_keys - self._deleted - delta_keys)
        self._len = visible_base + len(delta_keys)

    def __getitem__(self, key: int) -> Row:
        if key in self._deleted:
            raise KeyError(key)

        if key in self._delta:
            delta_val = self._delta[key]
            if isinstance(delta_val, dict):
                # Raw values dict - merge with base row
                base_row = self._base[key]
                merged = base_row.values.copy()
                merged.update(delta_val)
                row = base_row.copy()
                row.values = merged
                return row
            return delta_val
        return self._base[key]

    def __setitem__(self, key: int, value: Row) -> None:
        in_base = key in self._base
        in_delta = key in self._delta
        in_deleted = key in self._deleted

        self._delta[key] = value
        self._deleted.discard(key)

        # Length changes:
        # - Adding a new key (not in base, not in deleted): +1
        # - Restoring a deleted key (in deleted, not in base): +1
        # - Overwriting existing delta or base row: no change
        if not in_base and not in_deleted:
            self._len += 1
        elif in_deleted and not in_base:
            self._len += 1

    def __delitem__(self, key: int) -> None:
        in_delta = key in self._delta
        in_base = key in self._base

        if in_delta:
            del self._delta[key]
        self._deleted.add(key)

        # Length changes:
        # - Removing a visible delta row: -1
        # - Removing a visible base row (not in delta): -1
        # - Removing an already deleted row: no change
        if in_delta or (in_base and not in_delta):
            self._len -= 1

    def __contains__(self, key: object) -> bool:
        if key in self._deleted:
            return False
        return key in self._delta or key in self._base

    def __len__(self) -> int:
        return self._len

    def __iter__(self) -> Generator[int, Any, None]:
        # Yield base keys first (not in delta), then delta keys
        for key in self._base:
            if key not in self._deleted and key not in self._delta:
                yield key
        yield from self._delta

    def get[T](self, key: int, default: T = None) -> Row | T:
        if key in self._deleted:
            return default

        return self._delta[key] if key in self._delta else self._base.get(key, default)

    def items(self) -> Generator[tuple[int, Row], Any, None]: # pyright: ignore[reportIncompatibleMethodOverride]
        for key in self:
            yield key, self[key]

    def values(self) -> Generator[Row, Any, None]: # pyright: ignore[reportIncompatibleMethodOverride]
        for key in self:
            yield self[key]

    def keys(self) -> set[int]: # pyright: ignore[reportIncompatibleMethodOverride]
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

    def collapse(self) -> dict[int, Row]:
        """Convert this view to an actual dict of Row objects.

        This materializes all lazy operations and returns a concrete dict.
        Use this when you need an actual dict (e.g., for indexing, validation).
        """
        result: dict[int, Row] = {key: self[key] for key in self}
        return result

__all__ = [
    'Row'
]
