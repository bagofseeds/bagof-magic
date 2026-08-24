"""Every ``pycon`` block in a docstring must be true.

The examples in `bagof.magic._fields` show what each annotation lowers to,
so they are only useful if they match what the interpreter actually
prints. This runs them.
"""

# stdlib
import doctest
import io
import re
import textwrap
from pathlib import Path

# dependencies
import pytest
import typing_extensions as tx

# locals
import bagof.magic as magic

SOURCES = [
    "_api.py",
    "_arguments.py",
    "_constants.py",
    "_fields.py",
    "_magic.py",
    "_options.py",
]

#: Hand-written pages, relative to the repository root.
PAGES = ["README.md", "docs/comparison.md"]


class _Checker(doctest.OutputChecker):
    """Compare output without the `typing_extensions` spelling.

    Before Python 3.9 `typing_extensions` re-implements `Annotated` and
    friends rather than re-exporting them, so their repr is
    `typing_extensions.Annotated[...]`. The examples show the canonical
    `typing.Annotated[...]`, which is what a reader on any supported
    version recognises and what all but the oldest actually print.
    """

    def check_output(self, want: str, got: str, optionflags: int) -> bool:
        got = got.replace("typing_extensions.", "typing.")
        return super().check_output(want, got, optionflags)


def _globals() -> dict:
    """The namespace the examples are written against."""
    # `bagof.magic` uses `from __future__ import annotations`, and doctest
    # inherits a module's future flags from the globals it is given. That
    # would turn every annotation in these examples into a string, which
    # is not how a reader's own module behaves unless they opt into it.
    namespace = {k: v for k, v in vars(magic).items() if k != "annotations"}
    namespace["tx"] = tx
    return namespace


def _root() -> tx.Optional[Path]:
    """The repository root, or `None` when running from an installed copy."""
    root = Path(magic.__file__).resolve().parents[3]
    return root if (root / "README.md").is_file() else None


def _as_examples(code: str) -> str:
    """Turn a ``python`` block into doctest input."""
    lines = []
    decorated = False
    for line in code.splitlines():
        if not line.strip():
            continue
        # A new example starts at column zero -- unless the line before it
        # was a decorator, which belongs to the statement that follows.
        top = line == line.lstrip()
        lines.append(f"{'>>>' if top and not decorated else '...'} {line}")
        decorated = top and line.lstrip().startswith("@")
    return "\n".join(lines)


#: A page may show the other libraries side by side. Those blocks are
#: illustrations, not promises about this package, and their imports are
#: not installed -- so they are rendered but never run.
FOREIGN = ("dataclasses", "attrs", "pydantic")


def _is_ours(code: str) -> bool:
    return not any(f"from {name} import" in code or f"import {name}" in code
                   for name in FOREIGN)


def _page(path: Path) -> str:
    """A whole page as one doctest.

    A page defines its classes in ``python`` blocks and uses them in
    ``pycon`` blocks, so the two only make sense read together and in
    order -- unlike a docstring, where each block stands alone.
    """
    source = path.read_text()
    parts = []
    for match in re.finditer(r"```(python|pycon)\n(.*?)[ ]*```", source, re.S):
        kind = match.group(1)
        # A fence inside a `=== "tab"` is indented as a whole; dedent by
        # the common prefix so real Python indentation survives.
        body = textwrap.dedent(match.group(2))
        if kind == "python":
            if _is_ours(body):
                parts.append(_as_examples(body))
        else:
            parts.append(body)
    return "\n".join(parts) + "\n"


def _blocks(path: Path) -> tx.List[tx.Tuple[int, str]]:
    """Every ``pycon`` block in a file, with its line number."""
    source = path.read_text()
    found = []
    for match in re.finditer(r"```pycon\n(.*?)[ ]*```", source, re.S):
        line = source[: match.start()].count("\n") + 1
        body = "\n".join(
            ln[8:] if ln.startswith(" " * 8) else ln.lstrip()
            for ln in match.group(1).splitlines()
        )
        found.append((line, body + "\n"))
    return found


def _all_files() -> tx.List[Path]:
    files = [Path(magic.__file__).parent / name for name in SOURCES]
    root = _root()
    if root is not None:
        # Only present in a checkout; an installed copy ships the
        # modules but not the hand-written pages.
        files += [root / page for page in PAGES]
    return [path for path in files if path.is_file()]


CASES = [
    pytest.param(path.name, line, body, id=f"{path.name}:{line}")
    for path in _all_files()
    if path.suffix == ".py"
    for line, body in _blocks(path)
] + [
    pytest.param(path.name, 1, _page(path), id=path.name)
    for path in _all_files()
    if path.suffix == ".md"
]


def test_there_are_examples_to_check() -> None:
    # A refactor that moves the annotations elsewhere should not make this
    # file silently pass by finding nothing.
    assert len(CASES) >= 20


@pytest.mark.parametrize("name,line,body", CASES)
def test_pycon_block(name: str, line: int, body: str) -> None:
    test = doctest.DocTestParser().get_doctest(
        body, _globals(), f"{name}:{line}", name, line
    )
    runner = doctest.DocTestRunner(
        checker=_Checker(),
        optionflags=doctest.ELLIPSIS | doctest.IGNORE_EXCEPTION_DETAIL,
    )
    report = io.StringIO()
    result = runner.run(test, out=report.write)
    assert not result.failed, report.getvalue()
