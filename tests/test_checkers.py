"""What a type checker reads the annotation family as.

`Frozen[int]` becomes `Annotated[int, Frozen()]` when the code runs, but
a checker never runs it: to a checker, `Frozen` has to be declared as
something that, subscripted with a type, stands for that type. Those
declarations live in `_checkers`, behind `TYPE_CHECKING`, so the checks
here are of two kinds. The first kind runs everywhere and makes sure the
declarations cover the whole family and change nothing at run time. The
second asks mypy and pyright themselves, and is skipped where either is
not installed.
"""
import ast
import importlib.util
import inspect
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import typing_extensions as tx

import bagof.magic
import bagof.magic._checkers as checkers
import bagof.magic._fields as fields

# The markers whose call is the usual spelling, or which are never
# complete without a value, stay classes to a checker too.
_KEPT_AS_CLASSES = {
    "Default", "Doc", "ShowIf", "HideIf", "HideIfNone", "HideIfDefault",
    "Key", "Inherit", "Forget",
}


def _checker_bindings() -> tx.Dict[str, str]:
    """Each name the `TYPE_CHECKING` branch binds, and how it binds it:
    "alias" for an `Annotated` alias, or the module it is imported from.
    """
    tree = ast.parse(inspect.getsource(checkers))
    branch = next(
        node for node in tree.body
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test)
    )
    bound = {}
    for node in branch.body:
        if isinstance(node, ast.ImportFrom):
            for name in node.names:
                bound[name.asname or name.name] = (
                    "." * node.level + (node.module or "")
                )
        else:
            # Nothing but imports and assignments belongs in the branch.
            assert isinstance(node, ast.Assign)
            for target in node.targets:
                assert isinstance(target, ast.Name)
                kind = "alias" if "Annotated" in ast.dump(node.value) else ""
                bound[target.id] = kind
    return bound


class TestNothingChangesWhenTheCodeRuns:

    def test_the_family_is_listed_whole(self) -> None:
        assert sorted(checkers.__all__) == sorted(fields.__all__)

    @pytest.mark.parametrize("name", fields.__all__)
    def test_each_name_is_the_same_object(self, name: str) -> None:
        assert getattr(checkers, name) is getattr(fields, name)
        assert getattr(bagof.magic, name) is getattr(fields, name)

    def test_subscription_still_builds_annotated(self) -> None:
        hint = bagof.magic.Frozen[int]
        assert tx.get_origin(hint) is tx.Annotated
        kind, marker = tx.get_args(hint)
        assert kind is int
        assert type(marker) is fields.Frozen


class TestTheCheckerDeclarationsCoverTheFamily:

    @pytest.mark.parametrize("name", fields.__all__)
    def test_each_name_is_declared_for_a_checker(self, name: str) -> None:
        # A marker added to `_fields` and forgotten here would reach a
        # checker as the class, and `Marker[int]` would be reported.
        assert name in _checker_bindings()

    @pytest.mark.parametrize("name", fields.__all__)
    def test_each_marker_is_an_alias_unless_kept(self, name: str) -> None:
        how = _checker_bindings()[name]
        if name == "ClassVar":
            assert how == "typing_extensions"
        elif name == "InitVar":
            assert how == "dataclasses"
        elif name in _KEPT_AS_CLASSES or not isinstance(
            getattr(fields, name), type
        ) or name == "Field":
            assert how == "._fields"
        else:
            assert how == "alias"


# Every marker that a checker reads as an alias, written as a field.
_ALIASED = sorted(
    name for name, how in _checker_bindings().items() if how == "alias"
)

FIXTURE = (
    "from typing import Optional\n"
    "from typing_extensions import Annotated, reveal_type\n"
    "from bagof.magic import (\n"
    "    ClassVar, Default, Doc, Field, Forget, HideIf, HideIfDefault,\n"
    "    HideIfNone, Inherit, InitVar, Key, Magic, ShowIf,\n"
    + "".join(f"    {name},\n" for name in _ALIASED)
    + ")\n\n\n"
    "class Every(Magic):\n"
    + "".join(
        f"    {name.lower()}: {name}[int] = 0\n"
        for name in _ALIASED
    )
    + textwrap.dedent('''
        reveal_type(Every().frozen)
        Every(frozen="nope")


        class Standard(Magic):
            first: int
            shared: ClassVar[str] = "s"
            passed: InitVar[int] = 0


        Standard(1, 2)


        class Kept(Magic):
            doc: Annotated[int, Doc("how many")] = 0
            default: Annotated[int, Default(3)] = 3
            hidden: Annotated[Optional[int], HideIfNone()] = None
            keyed: Annotated[int, Key("k", ShowIf(bool))] = 0
            unset: Annotated[int, HideIf(bool), HideIfDefault()] = 0
            named: Annotated[int, Field(alias="why")] = 0
            inherited: Annotated[int, Inherit()] = 0
            gone: Annotated[int, Forget()] = 0


        reveal_type(Kept().doc)
    ''')
)


def _clean(said: str) -> tx.List[str]:
    """The diagnostics, without the file's path in front of them."""
    return [
        line.split("fixture.py", 1)[1] for line in said.splitlines()
        if "fixture.py:" in line
    ]


@pytest.fixture(scope="module")
def fixture_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    where = tmp_path_factory.mktemp("checkers")
    (where / "fixture.py").write_text(FIXTURE)
    return where


@pytest.fixture(scope="module")
def mypy_said(fixture_dir: Path) -> tx.List[str]:
    result = subprocess.run(
        [
            sys.executable, "-m", "mypy",
            "--no-error-summary", "--follow-imports=silent",
            "--no-incremental", "fixture.py",
        ],
        capture_output=True, text=True, cwd=str(fixture_dir),
    )
    return _clean(result.stdout)


@pytest.fixture(scope="module")
def pyright_said(fixture_dir: Path) -> tx.List[str]:
    result = subprocess.run(
        ["pyright", "--pythonpath", sys.executable, "fixture.py"],
        capture_output=True, text=True, cwd=str(fixture_dir),
    )
    return _clean(result.stdout)


@pytest.mark.skipif(
    importlib.util.find_spec("mypy") is None, reason="mypy is not installed"
)
class TestMypy:

    def test_a_marker_stands_for_its_type(
        self, mypy_said: tx.List[str]
    ) -> None:
        # Older releases of mypy spell it `builtins.int`.
        assert any(
            line.endswith(('Revealed type is "int"',
                           'Revealed type is "builtins.int"'))
            for line in mypy_said
        )

    def test_the_type_is_checked(self, mypy_said: tx.List[str]) -> None:
        assert any(
            'incompatible type "str"; expected "int"' in line
            for line in mypy_said
        )

    def test_class_variables_and_init_variables(
        self, mypy_said: tx.List[str]
    ) -> None:
        # `Standard(1, 2)` is accepted: `shared` is not a parameter, so
        # the 2 goes to `passed`.
        assert not any("Standard" in line for line in mypy_said)

    def test_nothing_else_is_reported(self, mypy_said: tx.List[str]) -> None:
        errors = [line for line in mypy_said if ": error:" in line]
        assert len(errors) == 1, mypy_said


@pytest.mark.skipif(
    shutil.which("pyright") is None, reason="pyright is not installed"
)
class TestPyright:

    def test_a_marker_stands_for_its_type(
        self, pyright_said: tx.List[str]
    ) -> None:
        said = "\n".join(pyright_said)
        assert '"Every().frozen" is "int"' in said
        assert '"Kept().doc" is "int"' in said

    def test_the_type_is_checked(self, pyright_said: tx.List[str]) -> None:
        assert any(
            '"Literal[\'nope\']" cannot be assigned to parameter "frozen"'
            in line for line in pyright_said
        )

    def test_a_class_variable_is_still_a_parameter(
        self, pyright_said: tx.List[str]
    ) -> None:
        # pyright leaves a class variable out of the constructor only
        # when `ClassVar` is imported from `typing` itself, in the same
        # file; the one `bagof.magic` hands on is read as the type alone.
        # Pinned so that a pyright that follows it is noticed: the docs
        # can then stop saying so.
        assert any(
            'parameter "shared" of type "str"' in line
            for line in pyright_said
        )

    def test_nothing_else_is_reported(
        self, pyright_said: tx.List[str]
    ) -> None:
        errors = [line for line in pyright_said if " - error:" in line]
        assert len(errors) == 2, pyright_said
