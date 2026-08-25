"""What a type checker is told about a Magic class.

`Magic` builds `__init__` when the class is created, which is long after
a type checker has finished looking. PEP 681 is the standard way to
describe that -- the same one `dataclasses` and `attrs` use -- so the
constructor shows up in completion and its arguments are checked.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from bagof.magic._magic import MetaMagic, magic
from bagof.magic._options import Options

# The transform's defaults are written out as literals, because that is
# the only form a checker reads. These are the options they have to
# agree with.
_MIRRORED = {
    "eq_default": "eq",
    "order_default": "order",
    "kw_only_default": "kw_only",
    "frozen_default": "frozen",
}


class TestTheDefaultsAgree:
    """A checker assumes what the class actually does, or it is worse
    than nothing: it would report a signature the class does not have.
    """

    @pytest.mark.parametrize("declared,option", sorted(_MIRRORED.items()))
    def test_the_metaclass_says_what_the_options_say(
        self, declared: str, option: str
    ) -> None:
        recorded = MetaMagic.__dataclass_transform__
        assert recorded[declared] == Options._DEFAULTS[option]

    @pytest.mark.parametrize("declared,option", sorted(_MIRRORED.items()))
    def test_the_decorator_says_the_same(
        self, declared: str, option: str
    ) -> None:
        recorded = magic.__dataclass_transform__
        assert recorded[declared] == Options._DEFAULTS[option]

    def test_field_is_the_field_specifier(self) -> None:
        # `x: int = Field(default=3)` is only understood as a field
        # rather than as a plain assignment because `Field` is named
        # here.
        from bagof.magic._fields import Field

        assert MetaMagic.__dataclass_transform__["field_specifiers"] == (
            Field,
        )


FIXTURE = '''
from bagof.magic import Magic, Field


class Point(Magic):
    x: float
    y: float


class Task(Magic):
    name: str
    token: str = Field(default="", repr=False)


reveal_type(Point.__init__)
Point("nope", 2.0)
'''


def _run_mypy(tmp_path: Path) -> str:
    """Type-check the fixture and hand back what mypy said about it."""
    source = tmp_path / "fixture.py"
    source.write_text(textwrap.dedent(FIXTURE))
    # The sibling packages are only on the path so that the import
    # resolves; their own type errors are not this suite's business.
    result = subprocess.run(
        [
            sys.executable, "-m", "mypy",
            "--no-error-summary",
            "--follow-imports=silent",
            str(source),
        ],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    return "\n".join(
        line for line in result.stdout.splitlines()
        if line.startswith(str(source)) or line.startswith("fixture.py")
    )


@pytest.mark.skipif(
    shutil.which("mypy") is None, reason="mypy is not installed"
)
class TestACheckerSeesTheConstructor:

    def test_the_arguments_are_the_fields(self, tmp_path: Path) -> None:
        said = _run_mypy(tmp_path)
        assert "x: builtins.float" in said
        assert "y: builtins.float" in said

    def test_a_wrong_argument_is_an_error(self, tmp_path: Path) -> None:
        said = _run_mypy(tmp_path)
        assert 'has incompatible type "str"; expected "float"' in said

    def test_mypy_still_objects_to_a_field_written_as_a_default(
        self, tmp_path: Path
    ) -> None:
        # A known limitation rather than a goal. PEP 681 lets a field
        # specifier be a class, and pyright reads `token: str =
        # Field(default="")` as a field with a default. mypy reads it as
        # assigning a `Field` to a `str` and says so. Every other
        # library in this space spells its specifier as a function
        # returning `Any`, which is what sidesteps it; ours is a class,
        # and changing that is a bigger question than this file.
        #
        # Pinned so that a future mypy quietly fixing it does not go
        # unnoticed: if this starts failing, delete it and the note in
        # the docs with it.
        said = _run_mypy(tmp_path)
        assert 'expression has type "Field"' in said
