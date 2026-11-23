"""Local, offline syntax checking.

The code is only PARSED (ast.parse). It is never executed, imported or compiled
into a runnable object, so a check cannot run the learner's program.
"""
from __future__ import annotations

import ast
import re
import warnings
from dataclasses import dataclass, field

BLOCK_KEYWORDS = ("for", "while", "if", "elif", "else", "try", "except",
                  "finally", "with", "def", "class", "match", "case")

GLOSSARY = {
    "header": "A header is the first line of a loop, if-statement or function. "
              "It starts with a keyword such as for, if or def and ends with a colon.",
    "colon": "A colon (:) at the end of a header tells Python: "
             "the indented lines below belong to this header.",
    "indent": "To indent means to push a line to the right (usually 4 spaces) "
              "so Python knows it belongs to the header above it.",
    "bracket": "Brackets are ( ), [ ] and { }. Every opening one needs a matching closing one.",
    "string": "A string is text inside quotes, like \"hello\". The opening and closing quote must match.",
}


@dataclass
class CheckResult:
    ok: bool
    empty: bool = False
    line_count: int = 0
    line: int | None = None
    column: int | None = None
    error_type: str = ""
    raw_message: str = ""
    kind: str = ""
    code_line: str = ""
    explanation: str = ""
    terms: list[str] = field(default_factory=list)


def normalize(text: str) -> str:
    """Notepad and UI Automation may hand back \\r\\n, \\r, BOMs or NULs."""
    return (text.replace("\r\n", "\n").replace("\r", "\n")
                .replace("\ufeff", "").replace("\x00", ""))


def check_python(source: str) -> CheckResult:
    source = normalize(source)
    lines = source.split("\n")
    if not source.strip():
        return CheckResult(ok=False, empty=True)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ast.parse(source, filename="<editor>")   # parse only: never executes
    except SyntaxError as exc:
        return _from_syntax_error(exc, lines)
    except (ValueError, RecursionError, MemoryError) as exc:
        return CheckResult(
            ok=False, line_count=len(lines), error_type=type(exc).__name__,
            raw_message=str(exc), kind="other",
            explanation="Python could not read this text as a program "
                        f"({type(exc).__name__}: {exc}).")
    return CheckResult(ok=True, line_count=len(lines))


def _from_syntax_error(exc: SyntaxError, lines: list[str]) -> CheckResult:
    msg = exc.msg or str(exc)
    line = exc.lineno
    if line and 1 <= line <= len(lines):
        code_line = lines[line - 1]
    else:
        code_line = (exc.text or "").rstrip("\n")
    kind, explanation, terms = _explain(msg, code_line, line)
    return CheckResult(
        ok=False, line_count=len(lines), line=line, column=exc.offset,
        error_type=type(exc).__name__, raw_message=msg, kind=kind,
        code_line=code_line, explanation=explanation, terms=terms)


def _looks_like_missing_colon(msg_lower: str, code_line: str) -> bool:
    if not msg_lower.startswith("invalid syntax"):
        return False
    text = re.sub(r"\s+#.*$", "", code_line.strip())
    words = text.replace("async ", "", 1).split()
    return bool(words) and words[0].rstrip("(") in BLOCK_KEYWORDS and not text.endswith(":")


def _explain(msg: str, code_line: str, line: int | None) -> tuple[str, str, list[str]]:
    m = msg.lower()
    n = line if line is not None else "?"

    if "expected ':'" in m or _looks_like_missing_colon(m, code_line):
        return ("missing_colon",
                f"Line {n} starts a block (a 'header') but does not end with a colon ':'. "
                "Add a ':' at the very end of that line.",
                ["header", "colon"])
    if m.startswith("expected an indented block"):
        hm = re.search(r"on line (\d+)", msg)
        where = f"the header on line {hm.group(1)}" if hm else "the line above it"
        return ("indent_missing",
                f"Line {n} must be indented (pushed right, usually 4 spaces) "
                f"because it belongs to {where}.",
                ["indent", "header"])
    if "unexpected indent" in m:
        return ("indent_unexpected",
                f"Line {n} is indented, but nothing above it asks for an indented block. "
                "Remove the extra spaces, or check that the line above is a header ending in ':'.",
                ["indent", "header"])
    if "unindent does not match" in m or "inconsistent use of tabs" in m:
        return ("indent_mismatch",
                f"The indentation on line {n} does not line up with earlier lines. "
                "Use the same number of spaces for lines in the same block (and avoid mixing tabs and spaces).",
                ["indent"])
    if "was never closed" in m:
        return ("bracket_open",
                f"A bracket opened on line {n} is never closed. Add the matching closing bracket.",
                ["bracket"])
    if m.startswith("unmatched") or "closing parenthesis" in m:
        return ("bracket_extra",
                f"Line {n} has a closing bracket with no matching opening one. "
                "Remove it, or add the missing opening bracket.",
                ["bracket"])
    if "unterminated string" in m or "unterminated triple-quoted" in m or "eol while scanning" in m:
        return ("string_open",
                f"A string that starts on line {n} is missing its closing quote.",
                ["string"])
    if "missing parentheses in call to 'print'" in m:
        return ("print_call",
                f"On line {n}, print needs parentheses in Python 3, for example print(\"hello\").",
                [])
    if "maybe you meant '==' or ':='" in m:
        return ("assign_in_condition",
                f"On line {n} a single = stores a value. To compare two values, use ==.",
                [])
    if "perhaps you forgot a comma" in m:
        return ("comma",
                f"Two items on line {n} are next to each other without a comma between them.",
                [])
    if "cannot assign to" in m:
        return ("bad_assignment",
                f"Line {n} tries to store a value somewhere Python does not allow "
                "(the left side of = must be a name).",
                [])
    if "expected 'except' or 'finally' block" in m:
        return ("try_without_except",
                f"A 'try' needs an 'except' (or 'finally') block after it. Line {n} is where Python noticed.",
                [])
    if m.startswith("invalid syntax"):
        return ("invalid_syntax",
                f"Python could not understand line {n}. The mistake is often on this line "
                "or at the end of the line before it (a missing colon, bracket or quote).",
                [])
    return ("other", f"Python stopped at line {n}: {msg}.", [])


def signature(result: CheckResult) -> str:
    """A stable label for 'which problem is this' (ignores line numbers)."""
    if result.empty:
        return "empty"
    if result.ok:
        return "ok"
    return f"{result.kind}:{result.raw_message}"


def topic_for(result: CheckResult) -> str | None:
    return None if result.ok or result.empty else "syntax_types"


def describe(result: CheckResult, level: str = "beginner") -> tuple[str, str]:
    """Return (headline, body) text adapted to the learner level."""
    if result.empty:
        return ("Nothing to check yet",
                "The editor is empty. Write some Python, then press Ctrl+Alt+F8 again.")
    if result.ok:
        if level == "advanced":
            return ("No syntax errors",
                    f"Parsed {result.line_count} lines. Parse only, not executed: "
                    "runtime and logic behaviour are unchecked.")
        return ("No syntax errors found",
                f"Python's parser read all {result.line_count} lines without finding a syntax error.\n"
                "I only parsed your code, I did not run it, so this does not prove the program "
                "does what you want.")

    head = f"Syntax error on line {result.line}"
    shown = f"{result.line:>3} | {result.code_line}" if result.line else result.code_line
    if level == "advanced":
        body = (f"{result.error_type} (line {result.line}): {result.raw_message}\n{shown}\n"
                f"{result.explanation}")
        return (head, body)
    body = f"{result.explanation}\n\n{shown}"
    if level == "intermediate":
        body += f"\n\nPython's own message: {result.error_type}: {result.raw_message}"
    else:  # beginner
        extra = [f"- {t}: {GLOSSARY[t]}" for t in result.terms if t in GLOSSARY]
        if extra:
            body += "\n\nWords used here:\n" + "\n".join(extra)
        body += "\n\nFix it, then press Ctrl+Alt+F8 again. You do not need to save."
    return (head, body)
