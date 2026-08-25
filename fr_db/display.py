from typing import TYPE_CHECKING
from textwrap import wrap
import re

if TYPE_CHECKING:
    from .types import Table

def display_table(table: Table, width: int = 50, sort: bool = False) -> str:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    ITALIC = "\033[3m"
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    DIM = "\033[2m"

    ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

    def visible_len(text: str) -> int:
        return len(ANSI_RE.sub("", text))

    def wrap_text(text: str, width: int) -> list[str]:
        if width <= 0:
            return [""]
        if not text:
            return [""]

        return wrap(
            text,
            width=width,
            replace_whitespace=False,
            drop_whitespace=True,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]

    def wrap_ansi(text: str, width: int) -> list[str]:
        if width <= 0:
            return [""]
        if not text:
            return [""]

        lines: list[str] = []
        current = ""
        current_width = 0
        active_codes: list[str] = []

        tokens = re.split(r"(\x1b\[[0-9;]*m)", text)

        for token in tokens:
            if not token:
                continue

            if ANSI_RE.fullmatch(token):
                current += token

                if token == RESET:
                    active_codes.clear()
                else:
                    active_codes.append(token)

                continue

            for char in token:
                if char == "\n":
                    current += RESET
                    lines.append(current)
                    current = "".join(active_codes)
                    current_width = 0
                    continue

                if current_width >= width:
                    current += RESET
                    lines.append(current)
                    current = "".join(active_codes) + char
                    current_width = 1
                else:
                    current += char
                    current_width += 1

        if current:
            current += RESET
            lines.append(current)

        return lines or [""]

    indexed_columns = list(enumerate(table.columns))
    indexed_columns.sort(
        key=lambda item: (
            not item[1].primary,
            not item[1].unique,
            item[0],
        )
    )

    columns = [column for _, column in indexed_columns]

    raw_headers: list[str] = []
    styled_headers: list[str] = []

    special_properties = {"primary", "unique"}

    for col in columns:
        base = f"{col.name}: {col.type.__name__}"

        properties = [
            prop
            for prop in col.properties
            if prop not in special_properties
        ]

        annotations: list[str] = []

        if properties:
            annotations.append(", ".join(properties))

        raw = base
        if annotations:
            raw += f" ({', '.join(annotations)})"

        raw_headers.append(raw)

        if col.primary:
            styled = f"{BOLD}{UNDERLINE}{CYAN}{base}{RESET}"
        elif col.unique:
            styled = f"{UNDERLINE}{YELLOW}{base}{RESET}"
        else:
            styled = base

        if annotations:
            styled += f"{ITALIC}{DIM} ({', '.join(annotations)}){RESET}"

        styled_headers.append(styled)

    raw_values: list[list[str]] = [
        [str(row.values.get(col.name, "")) for col in columns]
        for row in table.rows
    ]

    natural_widths: list[int] = [
        max(
            [len(raw_headers[i])]
            + [visible_len(row[i]) for row in raw_values]
        )
        for i in range(len(columns))
    ]

    min_widths = [
        max(3, min(len(raw_headers[i]), 20))
        for i in range(len(columns))
    ]

    fixed_width = 1 + len(columns) * 3

    available = max(
        sum(min_widths),
        width - fixed_width,
    )

    widths = natural_widths[:]

    if sum(widths) > available:
        widths = min_widths[:]

        remaining = available - sum(widths)

        while remaining > 0:
            candidates = [
                i
                for i in range(len(widths))
                if widths[i] < natural_widths[i]
            ]

            if not candidates:
                break

            for i in candidates:
                if remaining <= 0:
                    break

                widths[i] += 1
                remaining -= 1

    border = "+" + "+".join(
        "-" * (w + 2)
        for w in widths
    ) + "+"

    # Actually preserve ANSI formatting while wrapping headers.
    styled_header_lines: list[list[str]] = [
        wrap_ansi(styled_headers[i], widths[i])
        for i in range(len(columns))
    ]

    result = border + "\n"

    header_height = max(
        len(lines)
        for lines in styled_header_lines
    )

    for line_index in range(header_height):
        result += "| "

        for i, lines in enumerate(styled_header_lines):
            text = lines[line_index] if line_index < len(lines) else ""

            result += text
            result += " " * (widths[i] - visible_len(text))
            result += " | "

        result += "\n"

    result += border

    primary = next(
        (column for column in columns if column.primary),
        None,
    )

    rows = table.rows

    if primary is not None and sort:
        rows = sorted(
            rows,
            key=lambda row: row.values[primary.name],
        )

    for row in rows:
        cell_lines = [
            wrap_text(
                str(row.values.get(col.name, "")),
                widths[i],
            )
            for i, col in enumerate(columns)
        ]

        row_height = max(len(lines) for lines in cell_lines)

        for line_index in range(row_height):
            result += "\n| "

            for i, lines in enumerate(cell_lines):
                text = lines[line_index] if line_index < len(lines) else ""

                result += text
                result += " " * (widths[i] - visible_len(text))
                result += " | "

    result += "\n" + border

    return result

