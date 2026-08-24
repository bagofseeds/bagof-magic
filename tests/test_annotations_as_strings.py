"""
Tests for classes written in a module whose annotations are text.

The `from __future__ import annotations` line below is the point of this
file, and it has to stay there. With it, Python stores every annotation
in this module as a string instead of an object, which is how a great
many real modules look -- and a string hides the whole annotation family
(`ClassVar`, `KwOnly`, `Frozen`, `Field(...)`, ...) unless `Magic` reads
it back. Without the line, these tests silently become a copy of the ones
in `test_magic.py`, which use annotations that are already objects.
"""
from __future__ import annotations

import inspect

import pytest
from typing_extensions import Annotated, ForwardRef, Optional

from bagof.magic import (
    Arguments,
    ClassVar,
    ConvertTo,
    Doc,
    Factory,
    Field,
    Frozen,
    InitVar,
    KwOnly,
    Magic,
    NoRepr,
)


class _Canary:
    x: int


def test_this_module_stores_its_annotations_as_text() -> None:
    # If this fails, the future import at the top of the file is gone and
    # every test below has quietly stopped testing what it was written for.
    assert _Canary.__annotations__["x"] == "int"


# ======================================================================
# The annotation family
# ======================================================================


class TestAnnotationFamily:

    def test_kw_only_field_is_keyword_only(self) -> None:
        class Server(Magic):
            port: int
            debug: KwOnly[bool] = False

        parameters = inspect.signature(Server.__init__).parameters
        assert parameters["debug"].kind is inspect.Parameter.KEYWORD_ONLY
        with pytest.raises(TypeError):
            Server(80, True)
        assert Server(80, debug=True).debug is True

    def test_class_var_is_shared_and_not_an_init_parameter(self) -> None:
        class Counter(Magic):
            value: int = 0
            unit: ClassVar[str] = "requests"

        assert "unit" not in inspect.signature(Counter.__init__).parameters
        first, second = Counter(1), Counter(2)
        Counter.unit = "bytes"
        assert (first.unit, second.unit) == ("bytes", "bytes")

    def test_frozen_field_rejects_assignment(self) -> None:
        class Point(Magic):
            x: Frozen[int]
            y: int

        point = Point(1, 2)
        with pytest.raises(AttributeError, match="Cannot set frozen field"):
            point.x = 10
        point.y = 20
        assert point.y == 20

    def test_alias_renames_the_parameter(self) -> None:
        class Query(Magic):
            count: Annotated[int, Field(alias="n")] = 10

        assert "count" not in inspect.signature(Query.__init__).parameters
        assert Query(n=5).count == 5

    def test_doc_reaches_the_docstring(self) -> None:
        class Server(Magic, doc=True):
            port: Doc[int, "the port to listen on"]  # noqa: F722

        assert "port : int\n    the port to listen on" in Server.__doc__

    def test_init_var_is_passed_to_post_init_only(self) -> None:
        class Scaled(Magic):
            x: int
            scale: InitVar[int]

            def __post_init__(self, arguments: Arguments) -> None:
                self.x = self.x * arguments.scale

        scaled = Scaled(5, 10)
        assert scaled.x == 50
        assert not hasattr(scaled, "scale")

    def test_factory_default_is_built_per_instance(self) -> None:
        class Bag(Magic):
            items: Factory[list]

        first, second = Bag(), Bag()
        first.items.append(1)
        assert (first.items, second.items) == ([1], [])

    def test_no_repr_field_is_left_out_of_the_repr(self) -> None:
        class Point(Magic):
            x: int
            y: NoRepr[int]

        assert repr(Point(1, 2)) == "Point(x=1)"

    def test_convert_to_asks_for_conversion(self) -> None:
        class Server(Magic):
            port: ConvertTo[int]

        assert Server("8080").port == 8080

    def test_a_name_bound_earlier_in_the_class_body_is_visible(self) -> None:
        class Server(Magic):
            Port = int
            port: KwOnly[Port] = 80

        assert Server.__magic_fields__["port"].type is int
        assert Server(port=8080).port == 8080


# ======================================================================
# Types that are not available yet, or not at all
# ======================================================================


class TestUnresolvedNames:

    def test_a_class_can_refer_to_itself(self) -> None:
        class Node(Magic):
            value: int = 0
            parent: Optional[Node] = None

        assert Node.__magic_fields__["parent"].type == (
            Optional[ForwardRef("Node")]
        )
        tree = Node(1, Node(2))
        assert tree.parent.value == 2

    def test_a_name_that_is_never_defined_still_builds_the_class(
        self
    ) -> None:
        class Sized(Magic):
            width: NeverDefined = 1  # noqa: F821
            height: KwOnly[NeverDefined] = 2  # noqa: F821

        parameters = inspect.signature(Sized.__init__).parameters
        assert parameters["height"].kind is inspect.Parameter.KEYWORD_ONLY
        assert Sized.__magic_fields__["width"].type == (
            ForwardRef("NeverDefined")
        )
        assert Sized(3, height=4).height == 4

    def test_an_attribute_of_an_undefined_name_keeps_the_text(self) -> None:
        class Sized(Magic):
            width: Missing.Inner = 1  # noqa: F821

        assert Sized.__magic_fields__["width"].type == "Missing.Inner"
        assert Sized(3).width == 3

    def test_a_subscript_of_an_undefined_name_keeps_the_text(self) -> None:
        class Sized(Magic):
            width: Missing[int] = 1  # noqa: F821

        assert Sized.__magic_fields__["width"].type == "Missing[int]"
        assert Sized(3).width == 3

    def test_a_class_written_inside_a_function_reads_its_family(self) -> None:
        class Local(Magic):
            value: int = 0

        class Holder(Magic):
            item: KwOnly[Local] = None

        parameters = inspect.signature(Holder.__init__).parameters
        assert parameters["item"].kind is inspect.Parameter.KEYWORD_ONLY
        # A name that only a function body binds is out of reach from the
        # class statement, so the type itself stays a forward reference.
        assert Holder.__magic_fields__["item"].type == ForwardRef("Local")
        assert Holder(item=Local(1)).item.value == 1
