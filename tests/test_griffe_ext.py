"""The API reference shows what a `Magic` class writes for itself.

`docs/griffe_ext.py` is what puts the generated constructor, the field
table and the generated methods into the documentation site. It reads
the live class, so it knows things about `_magic.py` that a reader of
`_magic.py` would not think to keep true -- which is what this checks.

griffe needs Python 3.10, and is not installed for the older
interpreters the package itself supports, so these are skipped there.
"""

# stdlib
import sys
import textwrap
from pathlib import Path

# dependencies
import pytest

griffe = pytest.importorskip("griffe")

EXTENSION = Path(__file__).parent.parent / "docs" / "griffe_ext.py"

EXAMPLE = '''
"""An example package."""
from __future__ import annotations

import typing_extensions as tx

from bagof.magic import ClassVar, Doc, Factory, Field, Frozen, KwOnly, Magic


class Point(Magic, frozen=True, convert=True):
    """A point on a plane."""

    x: Doc[int, "How far along."]
    y: Doc[int, "How far up."] = 0


class Recipe(Magic, validate=True, mapping=True):
    """Something to cook."""

    origin: ClassVar[Doc[str, "Where it is from."]] = "here"
    name: tx.Annotated[str, Field(alias="title")]
    servings: KwOnly[int] = 4
    steps: Factory[list]
    secret: Frozen[tx.Optional[str]] = None

    def __repr__(self) -> str:
        """Written by hand, and so left alone."""
        return "a recipe"


class Plain:
    """Not a Magic class at all."""
'''


def _load(tmp_path: Path) -> griffe.Module:
    """Load the example package the way the documentation site does."""
    (tmp_path / "example.py").write_text(textwrap.dedent(EXAMPLE))
    sys.path.insert(0, str(tmp_path))
    try:
        return griffe.load(
            "example",
            search_paths=[str(tmp_path)],
            extensions=griffe.load_extensions(str(EXTENSION)),
        )
    finally:
        sys.path.remove(str(tmp_path))
        sys.modules.pop("example", None)


@pytest.fixture
def example(tmp_path: Path) -> griffe.Module:
    return _load(tmp_path)


def _parameters(cls: griffe.Class) -> list:
    return [
        (p.name, p.annotation, p.default, p.kind.value)
        for p in cls.members["__init__"].parameters
    ]


class TestConstructor:

    def test_signature(self, example: griffe.Module) -> None:
        assert _parameters(example["Point"]) == [
            ("x", "int", None, "positional or keyword"),
            ("y", "int", "0", "positional or keyword"),
        ]

    def test_keyword_only_and_factory(
        self, example: griffe.Module
    ) -> None:
        assert _parameters(example["Recipe"]) == [
            ("title", "str", None, "positional or keyword"),
            ("steps", "list", "<factory>", "positional or keyword"),
            ("secret", "str", "None", "positional or keyword"),
            ("servings", "int", "4", "keyword-only"),
        ]

    def test_carries_the_parameter_documentation(
        self, example: griffe.Module
    ) -> None:
        doc = example["Point"].members["__init__"].docstring.value
        assert "x : int" in doc
        assert "How far along." in doc

    def test_labelled_generated(self, example: griffe.Module) -> None:
        assert "generated" in example["Point"].members["__init__"].labels


class TestFieldTable:

    def test_columns(self, example: griffe.Module) -> None:
        doc = example["Point"].docstring.value
        assert "A point on a plane." in doc
        assert "| Field | Type | Default | Notes |" in doc
        assert "| `x` | `int` | *required* | frozen, converted |" in doc
        assert "| `y` | `int` | `0` | frozen, converted |" in doc

    def test_says_how_each_field_behaves(
        self, example: griffe.Module
    ) -> None:
        rows = example["Recipe"].docstring.value
        assert "| `servings` | `int` | `4` | keyword-only, validated |" in rows
        assert "| `steps` | `list` | `<factory>` | validated |" in rows
        assert "| `secret` | `str` | `None` | frozen, validated |" in rows

    def test_names_the_field_as_the_constructor_does(
        self, example: griffe.Module
    ) -> None:
        # The field is written `name` and passed as `title`.
        assert "| `title` |" in example["Recipe"].docstring.value

    def test_documents_a_field_that_is_not_a_parameter(
        self, example: griffe.Module
    ) -> None:
        rows = example["Recipe"].docstring.value
        assert "| Field | Type | Default | Notes | Description |" in rows
        assert "class attribute" in rows
        assert "Where it is from." in rows

    def test_a_column_with_nothing_in_it(self, tmp_path: Path) -> None:
        # A class that asks for nothing out of the ordinary has nothing
        # to say in the last two columns, so they are not drawn.
        (tmp_path / "plain_example.py").write_text(
            '"""Plain."""\n'
            "from bagof.magic import Magic\n"
            "class Plain(Magic):\n"
            '    """Plain."""\n'
            "    name: str\n"
            "    count: int = 0\n"
        )
        sys.path.insert(0, str(tmp_path))
        try:
            module = griffe.load(
                "plain_example",
                search_paths=[str(tmp_path)],
                extensions=griffe.load_extensions(str(EXTENSION)),
            )
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop("plain_example", None)
        doc = module["Plain"].docstring.value
        assert "| Field | Type | Default |" in doc
        assert "Notes" not in doc
        assert "| `count` | `int` | `0` |" in doc

class TestGeneratedMethods:

    def test_labelled_generated(self, example: griffe.Module) -> None:
        members = example["Point"].members
        for name in ("__eq__", "__hash__", "__repr__"):
            assert "generated" in members[name].labels

    def test_described(self, example: griffe.Module) -> None:
        eq = example["Point"].members["__eq__"]
        assert eq.docstring.value.startswith("Compare field by field")

    def test_the_dict_like_interface(self, example: griffe.Module) -> None:
        members = example["Recipe"].members
        for name in ("__getitem__", "__iter__", "__len__"):
            assert "generated" in members[name].labels

    def test_a_method_written_by_hand_is_left_alone(
        self, example: griffe.Module
    ) -> None:
        written = example["Recipe"].members["__repr__"]
        assert "generated" not in written.labels
        assert written.docstring.value == "Written by hand, and so left alone."


class TestLeftAlone:

    def test_a_class_that_is_not_magic(
        self, example: griffe.Module
    ) -> None:
        plain = example["Plain"]
        assert plain.docstring.value == "Not a Magic class at all."
        assert "__init__" not in plain.members

    def test_a_magic_class_with_no_fields(self) -> None:
        # `Magic` itself has no fields, so there is no constructor worth
        # showing and no table to draw.
        module = griffe.load(
            "bagof.magic",
            extensions=griffe.load_extensions(str(EXTENSION)),
        )
        assert "Fields" not in module["Magic"].docstring.value
