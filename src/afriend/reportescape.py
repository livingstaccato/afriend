"""Making untrusted friend prose safe to place in a Markdown report.

Split out of report.py, which crossed the 777-line cap. These are one
concern -- every function here answers "what can this text do to the
rendered document, and how is that neutralized" -- and they are the part of
the report layer with a security contract rather than a formatting one.

The recurring defect in this file's history is an escape that can be
switched off by its own input: a guard that skipped a line whose first
character was `<`, and a negative lookbehind that a second backslash
defeated. Both let an unclosed hidden `<div>` through, which swallowed 3 of
3 findings in the run that found it.
"""

from __future__ import annotations

import re

from .dispatch import sanitize_display

_BLOCK_LEADER_RE = re.compile(
    r"^(?P<indent>[ \t]{0,3})(?P<marker>"
    r"#{1,6}(?=[ \t]|$)"
    r"|>"
    r"|[-+*]+(?=[ \t]|$)"
    r"|=+(?=[ \t]*$)"
    r"|\|"
    r"|`+"
    r"|~{3,}"
    r"|\d+[.)](?=[ \t]|$)"
    r"|<"
    r")"
)
_URI_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*)://")
_ACTIVE_URI_RE = re.compile(r"(?i)\b(javascript|vbscript|data):")
_BARE_WWW_RE = re.compile(r"(?i)\bwww\.")
_EMAIL_RE = re.compile(
    r"(?i)(?<![A-Z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"([A-Z0-9.!#$%&'*+/=?^_`{|}~-]+)@"
    r"(?=[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?(?:\.[A-Z0-9-]+)+\b)"
)


def _sanitize_display(value: object, *, single_line: bool = False) -> str:
    """Neutralize terminal/display controls before any Markdown escaping."""
    text = sanitize_display(str(value))
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if single_line:
        return text.replace("\n", " ")
    return text


def _defang_links(text: str) -> str:
    text = _URI_RE.sub(lambda match: f"{match.group(1)}: //", text)
    text = _ACTIVE_URI_RE.sub(lambda match: f"{match.group(1)}: ", text)
    text = _BARE_WWW_RE.sub("www .", text)
    return _EMAIL_RE.sub(lambda match: f"{match.group(1)} @", text)


def _escape_cell(value: object) -> str:
    """Make `value` safe to place inside a single GFM table cell.

    A table cell that contains an unescaped `|` splits into extra columns
    for a human reading the rendered file, silently misaligning every field
    after it; a literal newline breaks the row entirely. Friend name and
    status are free text supplied by adapters/roster config, not claim
    authors, but nothing here guarantees they are pipe-free, so every cell
    is escaped the same way regardless of which field it came from.
    """
    text = _sanitize_display(value, single_line=True)
    text = _defang_links(text).replace("<", "&lt;").replace(">", "&gt;")
    text = text.replace("\\", "\\\\").replace("|", "\\|")
    text = text.replace("`", "&#96;").replace("[", "\\[").replace("]", "\\]")
    return text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def _escape_status_cell(value: object) -> str:
    """Defense in depth for a status rendered without resume validation."""
    text = _escape_cell(sanitize_display(str(value))).replace("`", "&#96;")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"(?i)\b([a-z][a-z0-9+.-]*)://", r"\1: //", text)
    text = re.sub(r"(?i)\bwww\.", "www .", text)
    return re.sub(r"(?i)\b(javascript|vbscript|data):", r"\1 :", text)


def _code_span(text: str) -> str:
    """Wrap `text` in backticks so it still renders as inline code even if
    `text` itself contains backticks (e.g. a location like
    ``src/a.py:`eval(...)```), and so a viewer displays exactly `text` --
    including its edge whitespace, if any.

    Per CommonMark, a backtick-delimited code span's fence must be a run of
    backticks strictly longer than the longest backtick run inside the
    content, and if the content starts or ends with a backtick, one space
    of padding on that side keeps the delimiter from fusing with it.
    Separately, CommonMark also strips exactly one leading and one trailing
    space from a code span's content whenever that content both begins and
    ends with a space (and isn't made entirely of spaces) -- so content
    like " abc " needs one extra space of padding on each side to survive
    that stripping and still display as " abc ". The two padding reasons
    are independent but never conflict: whenever either applies, adding
    exactly one space on each side is enough to round-trip the original
    text, because CommonMark only ever removes one space per side.
    """
    text = _sanitize_display(text, single_line=True)
    if text == "":
        return "``"
    longest_run = 0
    current = 0
    for ch in text:
        if ch == "`":
            current += 1
            longest_run = max(longest_run, current)
        else:
            current = 0
    fence = "`" * (longest_run + 1)
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    backtick_edge = text.startswith("`") or text.endswith("`")
    space_bracketed = text.startswith(" ") and text.endswith(" ") and text.strip(" ") != ""
    if backtick_edge or space_bracketed:
        return f"{fence} {text} {fence}"
    return f"{fence}{text}{fence}"


def _escape_block(text: str) -> str:
    """Backslash-escape a Markdown block-level construct at the start of
    each line of `text`, leaving everything else -- including newlines --
    untouched.

    Only the leading marker character is escaped (e.g. "### heading"
    becomes "\\### heading"); the rest of the line is left as-is, since a
    single leading backslash is enough to stop a block parser from
    recognizing the construct at all. This keeps the field rendering as
    ordinary prose rather than being wrapped in a code block, which would
    misrepresent prose fields like `claim` and `suggested_fix`.
    """
    text = _sanitize_display(text)
    escaped_lines = []
    for line in text.split("\n"):
        # First, before the marker match: an entity, not a backslash escape.
        # The previous `(?<!\\)<` skipped any `<` preceded by a backslash so
        # as not to double-escape `\<`, but a lookbehind cannot count -- two
        # backslashes before a tag suppressed it too, and CommonMark renders
        # `\\` as one literal backslash and then reads `<div hidden>` as live
        # HTML. That is the unclosed hidden `<div>` this module's docstring
        # records as having swallowed 3 of 3 findings, reachable again through
        # any even-length backslash run in friend prose. `&lt;` contains no
        # backslash, so no run of them can defeat it -- the same reason
        # `_escape_cell` uses entities. Doing it here rather than after the
        # marker match also means `<` never matches _BLOCK_LEADER_RE's `<`
        # alternative, so the line does not collect a stray `\` before the
        # entity. `>` is deliberately left alone: no tag can form without a
        # `<`, and escaping it would fight the blockquote marker.
        line = line.replace("<", "&lt;")
        match = _BLOCK_LEADER_RE.match(line)
        if match:
            marker = match.group("marker")
            start, end = match.span("marker")
            line = line[:start] + "\\" + marker[0] + marker[1:] + line[end:]
        line = _defang_links(line)
        line = line.replace("[", "\\[").replace("]", "\\]")
        escaped_lines.append(line)
    return "\n".join(escaped_lines)
