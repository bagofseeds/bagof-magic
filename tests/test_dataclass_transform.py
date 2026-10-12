"""What a type checker is told about a Magic class.

`Magic` builds `__init__` when the class is created, which is long after
a type checker has finished looking. PEP 681 is the standard way to
describe that -- the same one `dataclasses` and `attrs` use -- so the
constructor shows up in completion and its arguments are checked.
"""
from __future__ import annotations

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

import bagof.magic._fields as _fields
from bagof.magic import (
    Alias,
    ConvertTo,
    Default,
    Factory,
    Field,
    Frozen,
    Init,
    Kw,
    KwOnly,
    Magic,
    NoInit,
    NotKw,
    NotKwOnly,
    NotPositional,
    NotPositionalOnly,
    Positional,
    PositionalOnly,
    Repr,
    field,
    fields,
)
from bagof.magic._magic import MetaMagic, magic
from bagof.magic._options import Options

# Every public class of the annotation family, in the order the module
# lists them, after `Field` and `field()`.
_SPECIFIERS = (Field, field) + tuple(
    getattr(_fields, name) for name in _fields.__all__
    if isinstance(getattr(_fields, name), type)
    and issubclass(getattr(_fields, name), Field)
    and getattr(_fields, name) is not Field
)

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

    def test_the_field_specifiers_are_named(self) -> None:
        # `x: int = field(default=3)` is only understood as a field
        # rather than as a plain assignment because the thing on the
        # right is named here. `Field`, `field()` and every marker whose
        # meaning a PEP 681 keyword can say are.
        assert (
            MetaMagic.__dataclass_transform__["field_specifiers"]
            == _SPECIFIERS
        )

    def test_every_copy_of_the_tuple_names_the_same(self) -> None:
        # The tuple is written out once per decorator, since a checker
        # reads only a literal there; the overloads of `magic` keep
        # nothing to look at when the program runs, so read the source.
        import bagof.magic._magic as m

        tree = ast.parse(Path(m.__file__).read_text())
        written = [
            [element.id for element in keyword.value.elts]
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dataclass_transform"
            for keyword in node.keywords
            if keyword.arg == "field_specifiers"
        ]
        assert len(written) == 4
        expected = [
            "_field" if spec is field else spec.__name__
            for spec in _SPECIFIERS
        ]
        assert all(names == expected for names in written)


FIXTURE = '''
from bagof.magic import Magic, Field, field


class Point(Magic):
    x: float
    y: float


class Task(Magic):
    name: str
    tags: list = field(factory=list)
    token: str = Field(default="", repr=False)


class Named(Magic):
    name: str = field(kw_only=True)
    size: int = 0


reveal_type(Point.__init__)
reveal_type(Task.__init__)
Point("nope", 2.0)
Named("positional")
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

    def test_a_default_written_with_field_is_understood(
        self, tmp_path: Path
    ) -> None:
        # `field(...)` says it produces whatever the field is annotated
        # as, so the default is read as a default rather than as a
        # `Field` being assigned to the wrong type.
        said = _run_mypy(tmp_path)
        assert "tags: builtins.list[Any] =" in said
        assert 'variable has type "list[Any]"' not in said

    def test_mypy_still_objects_to_the_class_written_as_a_default(
        self, tmp_path: Path
    ) -> None:
        # `Field(...)` in a default is the older spelling and still
        # builds the same object. pyright reads it as a field with a
        # default; mypy reads it as assigning a `Field` to a `str` and
        # says so, which is why `field(...)` exists.
        #
        # Pinned so that a future mypy quietly accepting it does not go
        # unnoticed: if this starts failing, the two spellings have
        # become equivalent and the docs can stop distinguishing them.
        said = _run_mypy(tmp_path)
        assert 'expression has type "Field"' in said

    def test_kw_only_is_keyword_only_to_mypy(self, tmp_path: Path) -> None:
        # The run-time half is `test_kw_only_is_keyword_only_when_run`:
        # the checker and the class have to agree about which calls are
        # allowed.
        said = _run_mypy(tmp_path)
        assert 'Missing named argument "name" for "Named"' in said


def test_kw_only_is_keyword_only_when_run() -> None:
    # What mypy is told about `field(kw_only=True)` in the fixture is
    # what the class does.
    namespace: dict = {}
    exec(textwrap.dedent(FIXTURE).split("reveal_type")[0], namespace)
    with pytest.raises(TypeError):
        namespace["Named"]("positional")
    assert namespace["Named"](name="named").name == "named"


# ----------------------------------------------------------------------
# The family as the value: `x: int = KwOnly(kw_only=True)`.


def _parameters(cls: type) -> tx.Dict[str, inspect.Parameter]:
    return dict(inspect.signature(cls).parameters)


class TestAMarkerAsTheValue:
    """A marker written as the value means what it means in the
    annotation, and the PEP 681 keyword a checker reads means the same.
    """

    def test_each_marker_works_as_the_value(self) -> None:
        class C(Magic):
            _y: str = Alias(alias="why")
            x: int = KwOnly(kw_only=True)
            z: list = Factory(factory=list)
            f: list = Factory(default_factory=list)
            w: int = NoInit(init=False)
            v: int = Default(default=3)
            c: int = ConvertTo(converter=int)

        params = _parameters(C)
        assert list(params) == ["why", "z", "f", "v", "c", "x"]
        assert params["x"].kind is inspect.Parameter.KEYWORD_ONLY
        c = C("a", c="7", x=1)
        assert (c._y, c.x, c.z, c.f, c.v, c.c) == ("a", 1, [], [], 3, 7)
        assert c.z is not C("a", c=1, x=1).z
        assert not hasattr(c, "w")
        # The default is left on the class, the marker is not.
        assert C.v == 3

    def test_any_marker_works_as_the_value(self) -> None:
        # A marker that does not shape the constructor takes the same
        # keywords, so a checker can be told the rest.
        class C(Magic):
            x: int = Frozen(kw_only=True)
            y: int = Repr(False, default=2)

        params = _parameters(C)
        assert params["x"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["y"].default == 2
        c = C(x=1)
        assert repr(c) == "C(x=1)"
        with pytest.raises(AttributeError):
            c.x = 3

    def test_without_the_keyword_it_means_the_same(self) -> None:
        # Only a checker needs the keyword; the class reads the marker.
        class C(Magic):
            _y: str = Alias("why")
            x: int = KwOnly()
            z: list = Factory(list)
            w: int = NoInit()
            v: int = Default(3)

        params = _parameters(C)
        assert list(params) == ["why", "z", "v", "x"]
        assert params["x"].kind is inspect.Parameter.KEYWORD_ONLY
        assert C("a", x=1).v == 3

    def test_the_value_and_the_annotation_add_up(self) -> None:
        # The value is read after the annotation, as `field()` is: a
        # setting both give is the value's, and the names given to
        # Alias are all accepted.
        class C(Magic):
            x: KwOnly[int] = NotKwOnly(kw_only=False)
            y: tx.Annotated[int, Alias("why")] = Alias(alias="wye")
            z: KwOnly[int] = Default(default=3)

        params = _parameters(C)
        assert params["x"].kind is (
            inspect.Parameter.POSITIONAL_OR_KEYWORD
        )
        assert params["z"].kind is inspect.Parameter.KEYWORD_ONLY
        assert params["z"].default == 3
        assert C(1, wye=2).y == 2
        assert C(1, why=2).y == 2
        named = {f.name: f for f in fields(C)}
        assert named["y"].aliases[:2] == ("why", "wye")

    @pytest.mark.parametrize("marker,keyword", [
        (KwOnly, {"kw_only": True}),
        (NotKwOnly, {"kw_only": False}),
        (NoInit, {"init": False}),
        (Init, {"init": True}),
        (Init, {"init": False}),
        (NotKw, {"init": True}),
        (Kw, {"kw_only": True}),
        (Positional, {"kw_only": False}),
        (NotPositional, {"kw_only": True}),
        (NotPositionalOnly, {"kw_only": True}),
        # A marker that says nothing about how the field is passed takes
        # either keyword as `field()` does.
        (Frozen, {"kw_only": True}),
        (Repr, {"init": False}),
    ])
    def test_a_keyword_that_agrees_is_accepted(
        self, marker: type, keyword: dict
    ) -> None:
        assert isinstance(marker(**keyword), marker)

    @pytest.mark.parametrize("marker,args,keyword", [
        (KwOnly, (), {"kw_only": False}),
        (NotKwOnly, (), {"kw_only": True}),
        (NoInit, (), {"init": True}),
        (NoInit, (), {"kw_only": True}),
        (PositionalOnly, (), {"init": False}),
        (PositionalOnly, (), {"kw_only": True}),
        (NotKw, (), {"kw_only": True}),
        (Kw, (), {"init": False}),
        # What the call sets counts, not only what the class declares.
        (Kw, (False,), {"kw_only": True}),
        (Positional, (False,), {"kw_only": False}),
        (KwOnly, (), {"positional": True, "kw_only": True}),
        (Init, (), {"kw": False, "positional": False, "init": True}),
    ])
    def test_a_keyword_that_disagrees_is_refused(
        self, marker: type, args: tuple, keyword: dict
    ) -> None:
        # A checker would read the keyword and the class the marker, and
        # the two would describe different constructors.
        key, value = list(keyword.items())[-1]
        with pytest.raises(TypeError) as caught:
            marker(*args, **keyword)
        assert f"{marker.__name__}({key}={value!r}) says two" in str(
            caught.value
        )
        assert f"field({key}={value!r})" in str(caught.value)

    @pytest.mark.parametrize(
        "marker", [KwOnly, NoInit, Init, Positional, Frozen]
    )
    @pytest.mark.parametrize("key", ["init", "kw_only"])
    @pytest.mark.parametrize("value", [None, 0, "yes"])
    def test_a_keyword_that_is_not_a_bool_is_refused(
        self, marker: type, key: str, value: tx.Any
    ) -> None:
        # PEP 681 defines these keywords as booleans; a checker reads
        # nothing else from them.
        with pytest.raises(TypeError) as caught:
            marker(**{key: value})
        assert str(caught.value) == (
            f"{marker.__name__}({key}=...) takes True or False, not "
            f"{value!r}."
        )


MARKERS_FIXTURE = '''\
from bagof.magic import (
    Magic, Alias, Default, Factory, Frozen, KwOnly, NoInit, Repr,
)


class Spec(Magic):
    f: int = Frozen()
    _y: str = Alias(alias="why")
    x: int = KwOnly(kw_only=True)
    z: list = Factory(factory=list)
    w: int = NoInit(init=False)
    v: int = Default(default=3)
    r: int = Repr(False, default=1)


Spec(0, why="a", x=1)  # ok
Spec(0, "a", [], 4, 2, x=1)  # ok
Spec(0, "a", x=1, v=4, r=2)  # ok
Spec(0, "a", [], 4, 2, 5)  # error: x is keyword-only
Spec(0, _y="a", x=1)  # error: the parameter is called why
Spec(0, "a", x=1, w=2)  # error: w is not a parameter
Spec(0, "a")  # error: x has no default
Spec(why="a", x=1)  # error: f has no default, Frozen() is not one
'''


def _lines(marker: str) -> tx.Set[int]:
    """The fixture's lines whose comment starts with `marker`."""
    return {
        number
        for number, line in enumerate(MARKERS_FIXTURE.splitlines(), 1)
        if f"  {marker}" in line
    }


def _class_body() -> tx.Set[int]:
    """The fixture's lines that assign a marker to a field."""
    return {
        number
        for number, line in enumerate(MARKERS_FIXTURE.splitlines(), 1)
        if line.startswith("    ") and " = " in line
    }


def _reported(output: str, name: str) -> tx.Set[int]:
    """The fixture lines a checker reported an error on.

    mypy writes `markers.py:12: error: ...` and pyright
    `/path/markers.py:12:5 - error: ...`.
    """
    found = set()
    for line in output.splitlines():
        if "error" not in line or f"{name}:" not in line:
            continue
        number = line.split(f"{name}:", 1)[1].split(":", 1)[0]
        found.add(int(number))
    return found


def _check(tmp_path: Path, command: tx.List[str]) -> tx.Tuple[str, set]:
    """Run a checker over the fixture: what it said, and where."""
    source = tmp_path / "markers.py"
    source.write_text(MARKERS_FIXTURE)
    result = subprocess.run(
        [*command, str(source)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )
    return result.stdout, _reported(result.stdout, source.name)


@pytest.fixture(scope="module")
def mypy_said(
    tmp_path_factory: pytest.TempPathFactory,
) -> tx.Tuple[str, set]:
    return _check(tmp_path_factory.mktemp("mypy"), [
        sys.executable, "-m", "mypy",
        "--no-error-summary",
        "--follow-imports=silent",
        "--no-incremental",
    ])


@pytest.fixture(scope="module")
def pyright_said(
    tmp_path_factory: pytest.TempPathFactory,
) -> tx.Tuple[str, set]:
    return _check(tmp_path_factory.mktemp("pyright"), [
        str(shutil.which("pyright")), "--pythonpath", sys.executable,
    ])


def test_the_fixture_does_what_the_checkers_are_told() -> None:
    namespace: dict = {}
    body, calls = MARKERS_FIXTURE.split("\n\n\nSpec(", 1)
    exec(body, namespace)
    for line in ("Spec(" + calls).splitlines():
        call, comment = line.split("  # ")
        if comment == "ok":
            eval(call, namespace)
        else:
            with pytest.raises(TypeError):
                eval(call, namespace)


def test_the_fixture_marks_the_lines_it_means() -> None:
    assert len(_lines("# ok")) == 3
    assert len(_lines("# error")) == 5
    assert len(_class_body()) == 7


def test_a_report_is_read_by_line() -> None:
    said = "\n".join([
        "markers.py:12: error: Too many positional arguments",
        "/tmp/x/markers.py:15:5 - error: No parameter named \"w\"",
        "markers.py:3: note: Revealed type is ...",
        "other.py:4: error: unrelated",
    ])
    assert _reported(said, "markers.py") == {12, 15}


@pytest.mark.skipif(
    importlib.util.find_spec("mypy") is None,
    reason="mypy is not installed",
)
class TestMypyReadsAMarkerAsTheValue:

    @pytest.fixture
    def checked(self, mypy_said: tx.Tuple[str, set]) -> tx.Tuple[str, set]:
        return mypy_said

    def test_the_constructor_is_the_one_the_class_builds(
        self, checked: tx.Tuple[str, set]
    ) -> None:
        said, lines = checked
        assert _lines("# error") <= lines, said
        assert not (_lines("# ok") & lines), said

    def test_mypy_still_objects_to_a_class_as_the_value(
        self, checked: tx.Tuple[str, set]
    ) -> None:
        # mypy reads the marker as an instance of itself assigned to the
        # annotated type, as it does `Field(...)`; `field(...)` is the
        # spelling it accepts. Pinned so that a mypy that starts
        # accepting it does not go unnoticed.
        said, lines = checked
        assert _class_body() <= lines, said
        assert 'expression has type "KwOnly"' in said


@pytest.mark.skipif(
    shutil.which("pyright") is None, reason="pyright is not installed"
)
class TestPyrightReadsAMarkerAsTheValue:

    @pytest.fixture
    def checked(
        self, pyright_said: tx.Tuple[str, set]
    ) -> tx.Tuple[str, set]:
        return pyright_said

    def test_the_constructor_is_the_one_the_class_builds(
        self, checked: tx.Tuple[str, set]
    ) -> None:
        said, lines = checked
        assert _lines("# error") <= lines, said
        assert not (_lines("# ok") & lines), said

    def test_a_marker_as_the_value_is_not_an_error(
        self, checked: tx.Tuple[str, set]
    ) -> None:
        said, lines = checked
        assert not (_class_body() & lines), said
