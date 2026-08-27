
# Formatting guide

## General

### Empty lines

Empty line generally after dedent.

On the same indent level, empty lines
used to seperate "blocks" (like parapraphs),
related lines should be in the same block.
A good lines per block is **2-4**.

Exactly **1** empty line in between functions,
except if function names are almost the same
and are put into groups

You can put multiple empty lines if you want
to distinguish between high level sections,
but usually a comment is enough.

End of the file should have at least 2 empty lines.

### Indentation

Standard indentation, 4 spaces.

No hanging indent. (don't put anything on the same line as the opening parenthesis.)

#### Function args

Only multi-line function args if they would be too long.

When multi-lining, the first arg should be **2** indents above the `def`,
the closing paren is **1** indent above the def, and at the same level as the func code.

#### Multiline/nested calls

Each paren increases indent by **1**,
if a line starts with `.` (e.g. `something\n.method()`) it will be indented by **1** extra.

For call chains don't multiline it with `\` unless its too long.

Don't multiline too agressively. Default state is non-multiline, only multiline if the line
becomes insanely long.

You can put things after lines that only have a closing paren as if that was an empty line.
I don't want to see lines with just `)` and something after that could've been on that line.

Example:

```py
result = connection.execute(
    Query(User)
        .where(
            User.id == user_id,
        ).limit(1),
).first()
```

#### Comprehensions

Generally have the key alone on the first line (e.g. `key: value` in dict comprehensions),
unless it is very short (e.g. `i`), otherwise put the key and the `for` on the first line.

Second line should be `for`, and third line `if`.
These can be split across multiple lines if they are long/nested.

Indent the same as [Multiline/nested calls](#multilinenested-calls).

### Naming things

These are recommendations and are not absolute.

#### Class names

UpperCamelCase

#### Function names

lower_snake_case

#### Variable names

lower_snake_case.

## Typing

Strict pylance typing. Try to not add too many ignores.

Every argument should have a type hint, and every
method, function or class should have a docstring.

Docstring format example template:

```py
        """_summary_

        :param column: _description_
        :type column: str | Callable[[Row], bool]
        :param key: _description_, defaults to _MISSING
        :type key: Any, optional
        :raises Exception: _description_
        :return: _description_
        :rtype: Table
        """
```

Use proper formatting so editor hover looks pretty.

Use modern python typevar syntax (`def example[T](...):`)

Use builtin types instead of importing `List` from typing.

## Imports

Sort imports from longest to shortest.

For importing things in the project, put them in a separate block.

For type checker imports put them after other imports.

## Classes

Order of things in classes

1. `__slots__` (single line unless too long)
2. Class vars
3. `__init__` method
4. Methods starting with `__`
5. Methods starting with `_`
6. Methods sorted per categories

Each category should be marked by a comment

## Modules

All projects should be in a python module,
split everything into distinct files.

Don't have everything in a single folder,
have multiple subfolders.

`__main__` should not have anything except CLI,
if cli is over 50 lines move to cli.py and call
it from `__main__`.
