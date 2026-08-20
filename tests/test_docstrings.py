"""Every ``pycon`` block in a docstring must be true.

The examples in `bagof.magic.fields` show what each annotation lowers to,
so they are only useful if they match what the interpreter actually
prints. This runs them.
"""

# stdlib
import doctest
import io
import re
from pathlib import Path

# dependencies
import pytest
import typing_extensions as tx

# locals
import bagof.magic as magic

SOURCES = ["fields.py", "constants.py", "options.py", "__init__.py"]


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


def _blocks(filename: str) -> tx.List[tx.Tuple[int, str]]:
    """Every ``pycon`` block in a source file, with its line number."""
    path = Path(magic.__file__).parent / filename
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


CASES = [
    pytest.param(name, line, body, id=f"{name}:{line}")
    for name in SOURCES
    for line, body in _blocks(name)
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
