"""
Tests for classes written in a module whose annotations are text.

The `from __future__ import annotations` line below is the point of this
file, and it has to stay there. With it, Python stores every annotation
in this module as a string instead of an object, which is how a great
many real modules look -- and a string hides the whole annotation family
(`ClassVar`, `KwOnly`, `Frozen`, `Field(...)`, ...) unless `Magic` reads
it back. Without the line, these tests silently become a copy of the ones
in `test_magic.py`, which use annotations that are already objects.

A module written that way is also free to name types it never imports at
runtime, so the tests below cover both halves: the annotation family
still applies, and a type that is not available is carried by name
instead of taking the family down with it.
"""
from __future__ import annotations

import inspect
import sys
import warnings
from typing import TYPE_CHECKING

import pytest
import typing_extensions as tx
from bagof.converters import ConversionError
from typing_extensions import Annotated, ForwardRef

import bagof.magic._magic as m
import bagof.magic._resolve as r
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
    NoInit,
    NoRepr,
    Options,
    Validate,
    fields_dict,
)

if TYPE_CHECKING:
    # Imported for type checking only, so at runtime the name `decimal`
    # is not defined in this module -- the reason PEP 563 exists, and the
    # case that used to take the annotation family down with it.
    import decimal

    import bagof.magic as magic_types


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

    def test_stacked_family_members_all_apply(self) -> None:
        class Bag(Magic):
            items: NoInit[Factory[list]]

        assert "items" not in inspect.signature(Bag.__init__).parameters
        assert Bag().items == []

    def test_no_repr_field_is_left_out_of_the_repr(self) -> None:
        class Point(Magic):
            x: int
            y: NoRepr[int]

        assert repr(Point(1, 2)) == "Point(x=1)"

    def test_convert_to_asks_for_conversion(self) -> None:
        class Server(Magic):
            port: ConvertTo[int]

        assert Server("8080").port == 8080

    def test_a_marker_written_through_its_module_applies(self) -> None:
        class Counter(Magic):
            value: int = 0
            unit: tx.ClassVar[str] = "requests"

        assert "unit" not in inspect.signature(Counter.__init__).parameters
        assert Counter.unit == "requests"

    def test_a_factory_may_be_given_as_a_lambda(self) -> None:
        class Bag(Magic):
            items: Factory[list, lambda: [1, 2]]

        assert Bag().items == [1, 2]

    def test_a_subscript_that_names_no_marker_is_read_as_a_type(
        self
    ) -> None:
        # Nothing that could be a marker is written in front of the
        # brackets, so the annotation is simply the type it evaluates to.
        class Odd(Magic):
            x: (int, str)[0] = 1

        assert Odd.__magic_fields__["x"].type is int

    def test_a_method_does_not_shadow_the_type_it_is_named_after(
        self
    ) -> None:
        class Model(Magic):
            payload: dict = None
            mapping: KwOnly[dict] = None

            def dict(self) -> dict:
                return {"payload": self.payload}

        assert Model.__magic_fields__["payload"].type is dict
        assert Model.__magic_fields__["mapping"].type is dict
        assert Model(1).dict() == {"payload": 1}


# ======================================================================
# Types that are not available where the class is written
# ======================================================================


class TestUnavailableTypes:

    def test_a_type_imported_for_type_checking_only_keeps_the_family(
        self
    ) -> None:
        class Service(Magic):
            table: ClassVar[decimal.Decimal] = {}
            port: KwOnly[decimal.Decimal] = 80
            key: Frozen[decimal.Decimal] = None
            name: Annotated[decimal.Decimal, Field(alias="label")] = "s"

        parameters = inspect.signature(Service.__init__).parameters
        assert "table" not in parameters
        assert parameters["port"].kind is inspect.Parameter.KEYWORD_ONLY
        assert "label" in parameters and "name" not in parameters
        service = Service()
        with pytest.raises(AttributeError, match="Cannot set frozen field"):
            service.key = 1
        assert service.table == {}

    def test_a_type_a_newer_python_would_be_needed_for_keeps_the_family(
        self
    ) -> None:
        # `list[str]` and `int | None` are what the future import exists
        # to allow: they are fine as text on every Python, and raise when
        # actually evaluated on the older ones. Either way the field is
        # still a `ClassVar` and still keyword-only, and the type reads
        # back as what was written.
        class Config(Magic):
            names: ClassVar[list[str]] = []
            timeout: KwOnly[int | None] = None

        parameters = inspect.signature(Config.__init__).parameters
        assert "names" not in parameters
        assert parameters["timeout"].kind is inspect.Parameter.KEYWORD_ONLY
        fields = Config.__magic_fields__
        assert m._doc_type(fields["names"].type) == "list[str]"
        assert m._doc_type(fields["timeout"].type) == "int | None"

    @pytest.mark.skipif(
        sys.version_info < (3, 9),
        reason="list[str] cannot be built at runtime before 3.9",
    )
    def test_a_parameterised_builtin_generic_keeps_its_parameter(
        self
    ) -> None:
        # Pins `_doc_type` itself, not just a class that carries the type
        # by name. `list[str]` is a real object here (unlike the test
        # above, where an unavailable type falls back to text), which is
        # what exposes the parameter Python versions disagree on: on 3.9
        # and 3.10, `isinstance(list[str], type)` is True, so a check that
        # asks "is this a class" before "is this a parameterised generic"
        # takes the wrong branch and reports the type as plain `list`.
        assert m._doc_type(list[str]) == "list[str]"

    def test_a_class_can_refer_to_itself(self) -> None:
        class Node(Magic):
            value: int = 0
            parent: Frozen[Node] = None

        assert Node.__magic_fields__["parent"].type == ForwardRef("Node")
        tree = Node(1, Node(2))
        assert tree.parent.value == 2
        with pytest.raises(AttributeError, match="Cannot set frozen field"):
            tree.parent = None

    def test_a_type_that_is_never_defined_still_builds_the_class(
        self
    ) -> None:
        class Sized(Magic):
            width: NeverDefined = 1  # noqa: F821
            height: KwOnly[NeverDefined] = 2  # noqa: F821

        parameters = inspect.signature(Sized.__init__).parameters
        assert parameters["height"].kind is inspect.Parameter.KEYWORD_ONLY
        assert Sized.__magic_fields__["width"].type == "NeverDefined"
        assert Sized(3, height=4).height == 4

    def test_a_type_a_module_does_not_have_still_builds_the_class(
        self
    ) -> None:
        class Sized(Magic):
            width: KwOnly[inspect.NotAThing] = 1
            height: inspect.NotAThing[int] = 2

        parameters = inspect.signature(Sized.__init__).parameters
        assert parameters["width"].kind is inspect.Parameter.KEYWORD_ONLY
        assert Sized.__magic_fields__["width"].type == (
            ForwardRef("inspect.NotAThing")
        )
        assert Sized.__magic_fields__["height"].type == (
            "inspect.NotAThing[int]"
        )

    def test_a_class_written_inside_a_function_keeps_the_family(
        self
    ) -> None:
        # A name a function body binds is out of reach of a class
        # statement, so the family still applies and the type is carried
        # by the name it was written with.
        class Local(Magic):
            value: int = 0

        class Holder(Magic):
            item: KwOnly[Local] = None

        parameters = inspect.signature(Holder.__init__).parameters
        assert parameters["item"].kind is inspect.Parameter.KEYWORD_ONLY
        assert Holder.__magic_fields__["item"].type == ForwardRef("Local")
        assert Holder(item=Local(1)).item.value == 1

    def test_an_unavailable_type_is_documented_by_name(self) -> None:
        class Node(Magic, doc=True):
            parent: Frozen[Node] = None
            rate: ClassVar[decimal.Decimal] = None

        assert "parent : Node, optional" in Node.__doc__
        assert "rate : decimal.Decimal, optional" in Node.__doc__


# ======================================================================
# Annotations that are not evaluated, and what is said when they are not
# ======================================================================


_side_effects = []


def _record() -> type:
    _side_effects.append("ran")
    return int


def _explode() -> type:
    raise KeyboardInterrupt("an annotation must not be called")


def _metadata() -> str:
    return "not a field"


class TestAnnotationsAreNotRun:

    def test_an_annotation_that_is_a_call_is_never_called(self) -> None:
        # Both helpers really do what they claim when something calls
        # them, so the class below staying quiet means something.
        assert _record() is int
        assert _side_effects == ["ran"]
        _side_effects.clear()
        with pytest.raises(KeyboardInterrupt):
            _explode()

        class Reckless(Magic):
            x: _record() = 1
            y: _explode() = 2

        assert _side_effects == []
        assert Reckless().x == 1
        assert Reckless.__magic_fields__["x"].type == "_record()"

    def test_a_family_name_that_is_not_defined_is_reported(self) -> None:
        with pytest.warns(UserWarning, match="TYPE_CHECKING"):

            class Service(Magic):
                port: magic_types.KwOnly[int] = 80

        parameters = inspect.signature(Service.__init__).parameters
        assert parameters["port"].kind is not inspect.Parameter.KEYWORD_ONLY

    def test_metadata_that_cannot_be_read_back_is_reported(self) -> None:
        # Not a member of the annotation family, so there is nothing to
        # rebuild the metadata from -- and it is never called to find out.
        assert _metadata() == "not a field"

        with pytest.warns(UserWarning, match="could not be read back"):

            class Tagged(Magic):
                x: Annotated[int, _metadata()] = 1

        assert Tagged.__magic_fields__["x"].type == (
            "Annotated[int, _metadata()]"
        )

    def test_metadata_written_in_a_way_that_cannot_be_read_is_reported(
        self
    ) -> None:
        with pytest.warns(UserWarning, match="could not be read back"):

            class Tagged(Magic):
                x: Doc[int, f"a {1} doc"] = 1  # noqa: F722

        assert Tagged.__magic_fields__["x"].doc is None

    def test_metadata_naming_something_unavailable_is_reported(
        self
    ) -> None:
        with pytest.warns(UserWarning, match="could not be read back"):

            class Tagged(Magic):
                x: Annotated[int, Field(alias=NEVER)] = 1  # noqa: F821

        assert "x" in inspect.signature(Tagged.__init__).parameters

    def test_a_marker_that_cannot_be_rebuilt_is_reported(self) -> None:
        # `Annotated` needs metadata; with only a type in the brackets
        # there is nothing to rebuild it from.
        with pytest.warns(UserWarning, match="could not be read back"):

            class Tagged(Magic):
                x: Annotated[int] = 1

        assert Tagged.__magic_fields__["x"].type == "Annotated[int]"

    def test_an_annotation_that_is_not_an_expression_is_left_alone(
        self
    ) -> None:
        # Only a hand-built namespace can hold text like this; the
        # compiler never produces it. It is kept exactly as it came.
        Odd = type(Magic)(
            "Odd", (Magic,), {"__annotations__": {"x": "1 +"}, "x": 1}
        )
        assert Odd.__magic_fields__["x"].type == "1 +"

    def test_a_plain_unavailable_type_is_not_reported(self) -> None:
        # A type that is simply not available says nothing: there is no
        # structure to lose, and the field carries the name it was
        # written with, exactly as a quoted annotation always has.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class Service(Magic):
                rate: decimal.Decimal = None

        assert caught == []
        assert Service.__magic_fields__["rate"].type == "decimal.Decimal"


# ======================================================================
# Hints that are not types yet
# ======================================================================


class Sizes(Magic, convert=True):
    """A class written above the name its field is annotated with."""

    width: Pixels = 0  # noqa: F821


#: Bound after the class that uses it, the way a name further down a
#: module is when the class statement runs.
Pixels = int


class TestHintsResolvedOnFirstUse:

    def test_a_class_that_names_itself_is_converted_on_first_use(
        self
    ) -> None:
        class Node(Magic, convert=True):
            value: int = 0
            parent: KwOnly[tx.Optional[Node]] = None

        assert Node.__magic_fields__["parent"].type == ForwardRef(
            "tx.Optional[Node]"
        )
        assert Node(1, parent=Node(2)).parent.value == 2
        # The converter really is the one `Node` asks for: it builds a
        # `Node` out of what it is given, and refuses what it cannot.
        assert Node(1, parent=7).parent == Node(7)
        with pytest.raises(ConversionError):
            Node(1, parent="deep")

    def test_a_name_bound_later_in_the_module_resolves_on_first_use(
        self
    ) -> None:
        assert Sizes.__magic_fields__["width"].type == "Pixels"
        assert Sizes("3").width == 3

    def test_a_class_whose_types_are_all_there_is_unchanged(self) -> None:
        class Config(Magic, convert=True, validate=True):
            host: str = "localhost"
            port: int = 8080
            tags: Factory[list]

        for field in Config.__magic_fields__.values():
            assert not isinstance(field.converter, r._Deferred)
            assert not isinstance(field.validator, r._Deferred)
            assert not isinstance(field.factory, r._Deferred)
        assert Config("h", "9000") == Config(host="h", port=9000)
        assert Config().tags == []

    def test_a_default_is_built_from_a_name_bound_later(self) -> None:
        class Basket(Magic):
            items: Factory[Pixels]  # noqa: F821

        assert Basket().items == 0


class TestHintsThatNeverResolve:

    def test_the_field_carries_on_and_says_so_once(self) -> None:
        class Server(Magic):
            port: ConvertTo[decimal.Decimal] = 1

        with pytest.warns(UserWarning, match="is not being converted") as told:
            first = Server("8")
        assert len(told) == 1
        assert first.port == "8"

        # Once for the field, not once per call: a converter on a hot
        # constructor that said this every time would be unusable.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert Server("9").port == "9"
            assert Server("10").port == "10"
        assert caught == []

    def test_the_message_names_the_field_and_the_missing_name(self) -> None:
        class Server(Magic):
            port: ConvertTo[decimal.Decimal] = 1

        with pytest.warns(UserWarning) as told:
            Server("8")
        assert str(told[0].message).startswith(
            "Server.port: the name `decimal` is not defined, so `port` is "
            "not being converted."
        )

    def test_building_and_assigning_agree(self) -> None:
        class Server(Magic):
            port: ConvertTo[decimal.Decimal] = 1

        with pytest.warns(UserWarning):
            built = Server("8")
        assigned = Server(1)
        assigned.port = "8"
        assert built.port == assigned.port == "8"

    def test_a_value_is_not_validated_and_says_so(self) -> None:
        class Server(Magic):
            port: Validate[decimal.Decimal] = 1

        with pytest.warns(UserWarning, match="is not being validated"):
            assert Server("8").port == "8"

    def test_they_can_be_made_an_error(self) -> None:
        class Server(Magic, unresolved_hints="raise"):
            port: ConvertTo[decimal.Decimal] = 1

        with pytest.raises(NameError, match="`port` cannot be converted"):
            Server("8")
        # Settled once, and it stays settled.
        with pytest.raises(NameError):
            Server("9")

    def test_they_can_be_passed_over_in_silence(self) -> None:
        class Server(Magic, unresolved_hints="ignore"):
            port: Validate[decimal.Decimal] = 1

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert Server("8").port == "8"
        assert caught == []

    def test_a_default_that_cannot_be_built_says_so_when_it_is_needed(
        self
    ) -> None:
        class Basket(Magic):
            items: Factory[decimal.Decimal]

        with pytest.raises(NameError, match="no default value can be built"):
            Basket()
        # Nothing is wrong with a value that was passed in.
        assert Basket(3).items == 3

    def test_a_default_that_cannot_be_built_raises_whatever_is_asked(
        self
    ) -> None:
        # There is no value to hand back in place of one that cannot be
        # built, so "ignore" has nothing quieter to offer.
        class Basket(Magic, unresolved_hints="ignore"):
            items: Factory[decimal.Decimal]

        with pytest.raises(NameError, match="`items`"):
            Basket()

    def test_an_unknown_setting_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unresolved_hints must be"):

            class Server(Magic, unresolved_hints="shrug"):
                port: int = 1

    def test_a_hint_that_is_a_call_is_still_never_called(self) -> None:
        _side_effects.clear()

        class Reckless(Magic, convert=True):
            x: _record() = 1

        with pytest.warns(UserWarning, match="could not be worked out"):
            assert Reckless("3").x == "3"
        assert _side_effects == []

    def test_a_hint_that_is_not_an_expression_is_reported(self) -> None:
        Odd = type(Magic)(
            "Odd",
            (Magic,),
            {"__annotations__": {"x": "1 +"}, "x": 1},
            convert=True,
        )
        with pytest.warns(UserWarning, match=r"`1 \+` could not be worked"):
            assert Odd("3").x == "3"

    def test_a_hint_whose_names_are_all_defined_is_reported_as_written(
        self
    ) -> None:
        # Every name in it is there; what it spells is not, so there is
        # no missing name to point at.
        class Sized(Magic, convert=True):
            width: inspect.NotAThing = 1

        with pytest.warns(
            UserWarning, match="`inspect.NotAThing` could not be worked out"
        ):
            assert Sized("3").width == "3"

    def test_a_field_with_nowhere_to_look_still_names_itself(self) -> None:
        # A field resolved on its own, outside a class statement, has no
        # module to look a name up in and no class to be named after.
        field = Field(name="port", type="NeverDefined", converter=True)
        field.setdefault(Options.make_default())

        with pytest.warns(UserWarning, match="^port: the name `NeverDefined`"):
            assert field.converter("8") == "8"


# ======================================================================
# Type parameters
# ======================================================================


_T = tx.TypeVar("_T")


class TextBox(Magic, tx.Generic[_T], convert=True):
    item: _T
    items: tx.List[_T]


class TestTypeParametersWrittenAsText:
    """A generic class in a module whose annotations are strings."""

    def test_a_type_parameter_is_read_back_as_itself(self) -> None:
        # Not carried by name: `_T` is defined in this module, so the
        # text resolves to the very type variable the class was written
        # with -- which is what a subclass then fills in.
        fields = fields_dict(TextBox)
        assert fields["item"].type is _T
        assert fields["items"].type == tx.List[_T]

    def test_a_subclass_fills_it_in(self) -> None:
        class IntBox(TextBox[int]):
            pass

        fields = fields_dict(IntBox)
        assert fields["item"].type is int
        assert fields["items"].type == tx.List[int]
        assert IntBox("1", ["2"]) == IntBox(1, [2])
