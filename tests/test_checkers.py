"""What mypy and pyright report about the annotation family.

A type checker never runs `Frozen[int]`, so it cannot know that the
subscription stands for `Annotated[int, Frozen()]`: it reads `Frozen` as
the class it is, which takes no type arguments. The "Type checkers"
section of `docs/intro/fields.md` lists the spellings that both checkers
accept instead. The tests here hold the page to what the checkers say:

- `CLEAN` is every spelling the page recommends, and both checkers have
  to accept it without a word and read the constructor it describes;
- `MISREAD` is accepted, but read differently from what the class does,
  and the page says how;
- `REPORTED` is every spelling the page says a checker reports, so a
  checker that starts accepting one is noticed and the page can change.

Each checker is skipped where it is not installed. The versions pinned in
`tests/requirements.txt` are the ones these messages were written against.
"""
import importlib.util
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import typing_extensions as tx

CLEAN = textwrap.dedent('''
    import typing
    from typing import Optional

    from typing_extensions import Annotated, reveal_type

    from bagof.magic import (
        ConvertTo, Doc, Frozen, HideIfNone, Magic, Pin, field,
    )


    class Clean(Magic):
        _x: int = field(alias="x")
        _why: int = field(alias="why", default=0)
        frozen: Annotated[int, Frozen()] = 0
        documented: Annotated[int, Doc("how many")] = 0
        pinned: Annotated[str, Pin("classvar")] = ""
        hidden: Annotated[Optional[int], HideIfNone()] = None
        converted: Annotated[int, ConvertTo()] = 0
        retries: int = 3
        items: list = field(factory=list)
        named: int = field(kw_only=True)
        shared: typing.ClassVar[int] = 0


    reveal_type(Clean.__init__)
    reveal_type(Clean(1, 2, named=3).frozen)
    Clean(x=1, why=2, named=3)
    Clean(1, named=3)
''')

MISREAD = textwrap.dedent('''
    from typing_extensions import Annotated, reveal_type

    from bagof.magic import Alias, Factory, KwOnly, Magic


    class Misread(Magic):
        items: Annotated[list, Factory()]
        _y: Annotated[int, Alias("why")] = 0
        later: Annotated[int, KwOnly()] = 0


    reveal_type(Misread.__init__)
''')

# Each line here is one spelling a checker reports; `{}` marks where the
# line is looked for in the checkers' output.
REPORTED = textwrap.dedent('''
    from typing_extensions import Annotated, reveal_type

    from bagof.magic import (
        Alias, ClassVar, ConvertTo, Default, Doc, Frozen, Inherit, KwOnly,
        Magic, Pin,
    )


    class Reported(Magic):
        frozen: Frozen[int] = 0
        alias: Alias[int, "why"] = 0
        default: Default[int, 3] = 3
        pin: Pin[str, "classvar"] = ""
        doc: Doc[int, "how many"] = 0
        shared: ClassVar[int] = 0
        named: KwOnly[int] = 0


    class Base(Magic):
        x: int = 0


    class Changed(Base):
        x: ... = Inherit(frozen=True)


    reveal_type(Changed.__init__)
    Changed(x="nope")


    class Locked(Base):
        x: Frozen[...] = 0


    class Converts(Magic):
        n: Annotated[int, ConvertTo()] = 0


    Converts(n="3")
''')

_REPORTED_BY_BOTH = [
    "frozen: Frozen[int]",
    'alias: Alias[int, "why"]',
    "default: Default[int, 3]",
    'pin: Pin[str, "classvar"]',
    'doc: Doc[int, "how many"]',
    "shared: ClassVar[int]",
    "named: KwOnly[int]",
    'Converts(n="3")',
    "x: Frozen[...] = 0",
]

_REPORTED_BY_MYPY_ONLY = "x: ... = Inherit(frozen=True)"


def _line(source: str, text: str) -> int:
    """The number of the line of `source` that holds `text`."""
    numbers = [
        number for number, line in enumerate(source.splitlines(), 1)
        if text in line
    ]
    assert len(numbers) == 1, text
    return numbers[0]


def _said(command: tx.List[str], where: Path, name: str) -> tx.List[str]:
    """What a checker said about one file, one line per diagnostic, each
    starting with its line number."""
    result = subprocess.run(
        command + [name], capture_output=True, text=True, cwd=str(where)
    )
    # 0 is a clean file and 1 a file with errors. Anything else means the
    # checker did not check anything -- pyright, for one, downloads Node
    # the first time it runs -- and its silence must not pass for "no
    # errors".
    assert result.returncode in (0, 1), (
        f"{command[0]} could not check {name}:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    said = []
    for line in result.stdout.splitlines():
        if f"{name}:" in line:
            said.append(line.split(f"{name}:", 1)[1])
    return said


def _errors_on(said: tx.List[str], number: int) -> tx.List[str]:
    return [
        line for line in said
        if line.startswith(f"{number}:") and "error" in line
    ]


def _errors(said: tx.List[str]) -> tx.List[str]:
    return [line for line in said if " error" in line]


_Said = tx.Callable[[tx.List[str], str], tx.List[str]]


@pytest.fixture(scope="module")
def check(tmp_path_factory: pytest.TempPathFactory) -> _Said:
    """Run a checker on one of the sources, once per module."""
    where = tmp_path_factory.mktemp("checkers")
    for name, source in [
        ("clean.py", CLEAN), ("misread.py", MISREAD),
        ("reported.py", REPORTED),
    ]:
        (where / name).write_text(source)
    seen: tx.Dict[tx.Tuple[str, str], tx.List[str]] = {}

    def said(command: tx.List[str], name: str) -> tx.List[str]:
        key = (command[0], name)
        if key not in seen:
            seen[key] = _said(command, where, name)
        return seen[key]

    return said


_MYPY = [
    sys.executable, "-m", "mypy",
    "--no-error-summary", "--follow-imports=silent", "--no-incremental",
]
_PYRIGHT = ["pyright", "--pythonpath", sys.executable]

_skip_mypy = pytest.mark.skipif(
    importlib.util.find_spec("mypy") is None, reason="mypy is not installed"
)
_skip_pyright = pytest.mark.skipif(
    shutil.which("pyright") is None, reason="pyright is not installed"
)


class TestTheSpellingsRun:
    """What the page recommends does what it says when the code runs."""

    def test_the_clean_spellings(self) -> None:
        namespace: tx.Dict[str, tx.Any] = {}
        exec(CLEAN.split("reveal_type(")[0], namespace)
        clean = namespace["Clean"](x=1, why=2, named=3)
        assert (clean._x, clean._why, clean.named) == (1, 2, 3)
        assert clean.items == []
        assert namespace["Clean"](x=1, converted="4", named=0).converted == 4
        assert namespace["Clean"].shared == 0
        with pytest.raises(TypeError):
            namespace["Clean"](1, 2, 3)
        with pytest.raises(TypeError):
            namespace["Clean"](x=1, why=2, named=3, shared=4)

    def test_the_misread_spellings(self) -> None:
        # What a checker misses: the factory gives a default, the input
        # name is `why`, and `later` is keyword-only.
        namespace: tx.Dict[str, tx.Any] = {}
        exec(MISREAD.split("reveal_type(")[0], namespace)
        misread = namespace["Misread"](why=1, later=2)
        assert (misread.items, misread._y, misread.later) == ([], 1, 2)


@_skip_mypy
class TestMypy:

    def test_the_clean_spellings_are_accepted(
        self, check: _Said
    ) -> None:
        said = check(_MYPY, "clean.py")
        assert _errors(said) == [], said
        init = next(line for line in said if "Revealed type is \"def" in line)
        assert "x: builtins.int, why: builtins.int =," in init
        assert "items: builtins.list[Any] =" in init
        assert "*, named: builtins.int" in init
        assert "shared" not in init
        assert any(
            line.endswith('Revealed type is "builtins.int"') for line in said
        )

    def test_the_misread_spellings(self, check: _Said) -> None:
        said = check(_MYPY, "misread.py")
        assert _errors(said) == [], said
        init = next(line for line in said if "Revealed type is" in line)
        assert "items: builtins.list[Any]," in init
        assert "_y: builtins.int =" in init
        assert "*" not in init

    @pytest.mark.parametrize(
        "text", _REPORTED_BY_BOTH + [_REPORTED_BY_MYPY_ONLY]
    )
    def test_reported(self, check: _Said, text: str) -> None:
        said = check(_MYPY, "reported.py")
        assert _errors_on(said, _line(REPORTED, text)), said


@_skip_pyright
class TestPyright:

    def test_the_clean_spellings_are_accepted(
        self, check: _Said
    ) -> None:
        said = check(_PYRIGHT, "clean.py")
        assert _errors(said) == [], said
        init = next(line for line in said if '"Clean.__init__"' in line)
        assert "(self: Clean, x: int, why: int = 0," in init
        assert "items: list[Unknown] = list" in init
        assert "*, named: int)" in init
        assert "shared" not in init
        assert any('.frozen" is "int"' in line for line in said)

    def test_the_misread_spellings(self, check: _Said) -> None:
        said = check(_PYRIGHT, "misread.py")
        assert _errors(said) == [], said
        init = next(line for line in said if '"Misread.__init__"' in line)
        assert "items: list[Unknown]," in init
        assert "_y: int = 0" in init
        assert "*" not in init

    @pytest.mark.parametrize("text", _REPORTED_BY_BOTH)
    def test_reported(self, check: _Said, text: str) -> None:
        said = check(_PYRIGHT, "reported.py")
        assert _errors_on(said, _line(REPORTED, text)), said

    def test_inherit_with_no_type_is_accepted(self, check: _Said) -> None:
        # Accepted, but with `...` as the type, so the constructor
        # checks nothing for `x`: `Changed(x="nope")` is not reported.
        said = check(_PYRIGHT, "reported.py")
        number = _line(REPORTED, _REPORTED_BY_MYPY_ONLY)
        assert _errors_on(said, number) == [], said
        init = next(line for line in said if '"Changed.__init__"' in line)
        # `Inherit` is a field specifier, so pyright reads the value as
        # declaring the field rather than as its default.
        assert "x: ..." in init
        assert "Inherit(" not in init
        assert _errors_on(said, _line(REPORTED, 'Changed(x="nope")')) == []
