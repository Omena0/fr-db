# QUESTIONS.md

Fill in the "Answer:" lines (edit the code blocks to the preferred format). Once done, I'll use this to extend `FORMAT.md`.

## 1. Line length and when to break a signature

`index.py` keeps `def __init__(self, column: str, unique: bool = False):` on one line (47 chars) but breaks `def update(self, old_value: Any, new_value: Any, row_id: int) -> None:` onto multiple lines (74 chars). What is the line-length limit, and when does a signature break?

```python
    def update(
        self,
        old_value: Any,
        new_value: Any,
        row_id: int,
    ) -> None:
```

Answer (line-length limit): There isn't really a line length limit. Its just what feels 'too long'.

Answer (break rule):  When its feels too long.

Also in regard to update(), that should've been on a single line tbh.

And what contributes to the feeling of it being too long?
Argument count, how long the annotations & default values are, and overall line length.

## 2. Docstring with a summary + a longer description

`index.py` only shows summary+params and a class docstring (no blank line, description indented +1 level). The codebase also has PEP 257-style docstrings with a blank line after the summary. Which do you want?

Option A (like the `index.py` class docstring — no blank line, description indented +1 level):

```python
def get_index(self, column: str) -> Index | None:
    """Return the index associated with a column, or None if no index exists.
        Used by lookup helpers to determine whether an indexed lookup is
        available for the requested column.
    """
```

Option B (PEP 257 — blank line after summary, description at the opening indent):

```python
def get_index(self, column: str) -> Index | None:
    """Return the index associated with a column, or None if no index exists.

    Used by lookup helpers to determine whether an indexed lookup is
    available for the requested column.
    """
```

Answer:  Option B, the syntax for option A is only for :params.

To clarify, here are the options:

Single line summary + params
(most common for things with params)

```py
"""_summary_
    _params_
"""
```

Single line summary + description.
(most common for things with no params)

```py
"""_summary_

_description_
"""
```

Multiline summary / fused summary + description
(usually for class docstrings where there are no params)

```py
"""
    _summary_
    _summary_
"""
```

Summary + params + description
(used rarely cuz you usually dont need something so long)

```py
"""_summary_
    _params_

_description_
"""
```

## 3. `__slots__`: list vs tuple, ordering, and wrapping

`index.py` uses a single-quoted list sorted alphabetically (`'_dirty'` first). The rest of the codebase mixes tuples `('type', 'key')`, unsorted lists in `__init__` order, and one very long single line. Which win?

```python
__slots__ = ['_dirty', '_shared', '_table', '_values', 'column', 'unique']
__slots__ = ('type', 'key')
__slots__ = ['database', 'name', '_rows', '_columns', 'indexes', '_transaction', 'operations', '_default_columns', '_in_transaction', '_query_cache']
```

Answer (list or tuple):  tuple
Answer (ordering: sorted vs __init__ order):  order in which they were added to the class, so development order.
Answer (when too long, wrap how):  If it goes out of the screen, so like 100 chars.

Wrap like this:

```py
__slots__ = (
    'database',
    'name',
    '_rows',
    '_columns',
    'indexes',
    '_transaction',
    'operations',
    '_default_columns',
    '_in_transaction',
    '_query_cache'
)
```

I keep them on single line unless its too long because it gets kinda long.

Either one thing per line or all of them on one line.

I think you can also do this to get it just a bit shorter, if its barely over 100 chars or approaching 100.

```py
__slots__ = (
    'database', 'name', '_rows', '_columns', 'indexes', '_transaction', 'operations', '_default_columns', '_in_transaction', '_query_cache'
)
```

## 4. Blank lines around top-level functions

`index.py` shows 2 blank lines before a top-level `class`. For top-level `def`, is it also 2 blank lines before (and after)?

```python
def apply_all(keys: Iterable[Callable[[Any], Any]], value: Any):
    for key in keys:
        value = key(value)
    return value
```

Answer (blank lines before a top-level def):  In index.py there is two lines because it separates two blocks, imports and class defs.

Between individual functions / classes only 1 empty line, in between concrete blocks, two lines.

Blocks as in imports, defs, `__main__`, etc.

## 5. Type-ignore comments

`index.py` uses specific inline `# pyright: ignore[reportPrivateUsage]`. Other files use bare `# type: ignore`. Which do you want, and inline-at-end-of-line?

```python
for row_id, row in table._rows.items(): # pyright: ignore[reportPrivateUsage]
def __exit__(self, _exc_type, _exc_val, _exc_traceback): # type: ignore
```

Answer:  type ignore is for supressing all errors, pyright is for a specific one.

In the exit method it is type: ignore because I couldn't bother typing the specific error name, and on that line there can't be any problems anyways if I suppress all.

## 6. `@overload` stubs

Are `@overload` definitions written with a `...` body on the signature line, and are there blank lines between the overloads and the real implementation?

```python
    @overload
    def where(self, column: Callable[[Row], bool]) -> TableView: ...
    @overload
    def where(self, column: str, key: Any) -> TableView: ...
    def where(self, column: str | Callable[[Row], bool], key: Any = _MISSING) -> TableView:
```

Answer (body on same line):  Yes
Answer (blank lines between):  Nope.

What you show is correct.

In case the arguments in the overloads need to be multilined, THEN add blank lines in between the funcs.

## 7. Explanatory comments inside a method body

`index.py`'s comments are category comments (section dividers). For inline step comments, is it "1 blank line before, none after" (like section comments) or attached right to the following statement?

```python
        # Phase 1: Fuse compatible operations
        result = cls._fuse_ops(ops)

        # Phase 2: Merge consecutive same-type operations
        result = cls._merge_consecutive(result)

        # Phase 3: Push down operations for better performance
        result = cls._pushdown(result)
```

Answer: Both those options are the same thing no?

There are no blank line in between a comment and what it is attached to, that helps clarify visually that
the next thing is a part of the section. So it is attached to the next statement.

## 8. Multiline boolean condition in an `if`

How do you wrap a long `if` condition — opening `(` placement, continuation indent, and closing `):`?

```python
        if (op.type == OpType.WHERE and i + 2 < n
            and ops[i + 1].type == OpType.TRANSFORM
            and ops[i + 2].type == OpType.SELECT):
```

Answer (opening paren position / indent / closing): What you showed is fine. But only because of a coincidence.

```python
if (op.type == OpType.WHERE and i + 2 < n
    and ops[i + 1].type == OpType.TRANSFORM
    and ops[i + 2].type == OpType.SELECT):
```

Here the `if (` just happens to be 4 chars exactly, so hangover indent doesnt leave a indent gap.

If it was something else like an elif:

```python
elif (op.type == OpType.WHERE and i + 2 < n
        and ops[i + 1].type == OpType.TRANSFORM
        and ops[i + 2].type == OpType.SELECT):
```

I'd do it like that.

But this might be a special case since the lines are so similar..
Idk I cant find a good example in this codebase so I'll just say this:

If the lines arent similar like this and are hard to follow,
multiline it fully instead of hangover indent.

## 9. `__all__`

Single line vs multiline, single-item case, and trailing comma?

```python
__all__ = [
    'Database',
    'Table',
    'TableView',
]

__all__ = [
    'Row'
]
```

Answer (multi vs single line):  Multi line always.
Answer (trailing comma):  Doesnt matter tbh

## 10. Using `id` as a name

`index.py` uses `row_id`. The rest of the codebase uses `id` as a loop variable / attribute, shadowing the builtin. Preferred?

```python
for id, row in self._rows.items():
    ...
row.id = self.id
```

Answer:  I dont care about shadowing builtins.

If id() isn't even used then its no problem right?
If we need the builtin then I can simply f2 rename the variable.

## 11. Variable annotations (space after colon)

Consistent space after the colon in annotated assignments / annotations?

```python
self._values: dict[Any, set[int]] = {}
rows:list[Row] = []
```

Answer:  Yes, it should have a space after.

## 12. Return type annotations

`index.py` annotates every method's return (e.g. `-> None`). Other files omit return types frequently. Required on every def?

```python
def __init__(self, type: OpType, *key: Any):
def _apply_ops(self):
def apply(self, table: Table):
```

Answer:  Not needed. Returning None is implied by not having an annotation.

Also my IDE shows the return annotation as shadow text anyways if there is none.

## 13. Import aliases

When an import name would shadow something, do you alias it?

```python
from .row import Row as RowClass
```

Answer:  It shouldn't shadow in the first place.
In operation.py that is completely unnecessary since Row is only imported if TYPE_CHECKING.

I've fixed it in operation.py

## 14. Enum members

Blank lines between `IntEnum` members?

```python
class OpType(IntEnum):
    WHERE = auto()
    TRANSFORM = auto()
    TRANSFORM_ROWS = auto()
```

Answer:  No blank lines, they are unnecessary here.
