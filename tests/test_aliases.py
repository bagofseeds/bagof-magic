"""Aliases keep one value while exposing several explicit access paths."""

# Alias and Property payloads contain values, not forward references.
# ruff: noqa: F821

import inspect

import pytest
import typing_extensions as tx

from bagof.magic import (
    Alias,
    ClassVar,
    ConvertTo,
    Field,
    InitVar,
    Magic,
    Property,
    ReadOnlyProperty,
    Validate,
    asdict,
    field,
    fields,
    magic,
    replace,
)


def test_normalized_names_and_copied_configuration() -> None:
    names = ["label", "name"]
    properties = {"label": "readwrite", "title": "readonly"}
    declared = field(alias=names, property=properties)
    names.append("later")
    properties["later"] = True

    class Example(Magic):
        name: str = declared

    f = fields(Example)[0]
    assert f.aliases == ("label", "name")
    assert f.public_name == "label"
    assert f.properties == {"label": True, "title": "readonly"}
    f.properties["later"] = True
    assert "later" not in f.properties
    assert Field(name="_name").aliases == ("name",)
    assert Field(name="_name", alias=False).aliases == ("_name",)


@pytest.mark.parametrize("slots", [False, True])
def test_properties_and_constructor_aliases(slots: bool) -> None:
    class Example(Magic, slots=slots, mapping=True, convert=True):
        name: Property[
            Alias[str, ("label", "name", "title")],
            {"label": True, "title": "readonly"},
        ]

    obj = Example(title=b"1")
    assert obj.name == obj.label == obj.title == "1"
    obj.label = b"2"
    assert obj.name == obj.title == "2"
    with pytest.raises(AttributeError):
        obj.title = "three"
    with pytest.raises(AttributeError):
        del obj.label
    with pytest.raises(AttributeError):
        del obj.title
    assert dict(obj) == {"label": "2"}
    assert asdict(obj) == {"label": "2"}
    with pytest.raises(KeyError):
        _ = obj["title"]
    assert repr(obj) == "Example(label='2')"
    assert len(fields(Example)) == 1
    assert obj == Example(name="2")
    assert str(inspect.signature(Example)) == "(label: str) -> None"
    assert "Also accepts: name, title." in Example.__init__.__doc__


def test_auto_aliases_and_modes() -> None:
    class Example(Magic, alias=True):
        _name: Property[
            str, {"label": "readwrite", "title": "readonly", "disabled": False}
        ]

    assert fields(Example)[0].aliases == ("name", "label", "title")
    assert Example(title="Ada")._name == "Ada"
    assert not hasattr(Example(name="Ada"), "disabled")

    class Circular(Magic, alias=True, property=True):
        name: str
        _count: int

    obj = Circular("Ada", 3)
    assert obj.name == "Ada"
    assert obj.count == 3
    obj.count = 4
    assert obj._count == 4


@pytest.mark.parametrize("names", [("label", "title"), ["label", "title"]])
def test_property_sequences(names: tx.Sequence[str]) -> None:
    class Example(Magic):
        name: Property[str, names]

    obj = Example("Ada")
    obj.title = "Grace"
    assert obj.label == obj.name == "Grace"


def test_preferred_name_is_replacement_not_implicit_synonym() -> None:
    class Example(Magic):
        name: Alias[str, ("label", "title")]

    with pytest.raises(TypeError):
        Example(name="Ada")
    assert Example(title=None).name is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"label": 1, "name": 1},
        {"name": None, "title": 2},
    ],
)
def test_duplicate_keywords(kwargs: dict) -> None:
    class Example(Magic):
        name: Alias[int, ("label", "name", "title")]

    with pytest.raises(TypeError, match="multiple values"):
        Example(**kwargs)
    with pytest.raises(TypeError, match="multiple values"):
        replace(Example(1), **kwargs)


def test_duplicate_position_and_alias_before_hook() -> None:
    calls = []

    class Example(Magic):
        name: Alias[int, ("label", "name")]

        def __pre_init__(self, arguments: tx.Any) -> None:
            calls.append(arguments)

    with pytest.raises(TypeError, match="multiple values"):
        Example(1, name=1)
    assert calls == []
    Example(1)
    assert len(calls) == 1


def test_hooks_and_replace_use_preferred_names() -> None:
    calls = []

    class Example(Magic, convert=True):
        name: Alias[int, ("label", "name")]

        def __pre_init__(self, arguments: tx.Any) -> None:
            calls.append(("pre", arguments.label))

        def __post_init__(self, arguments: tx.Any) -> None:
            calls.append(("post", arguments.label))

    obj = Example(name="1")
    copied = replace(obj, name="2")
    assert copied.name == 2
    assert calls == [("pre", "1"), ("post", 1), ("pre", "2"), ("post", 2)]


def test_keyword_only_and_positional_only() -> None:
    class Example(Magic):
        first: int = field(alias=("one", "uno"), kw=False)
        second: int = field(alias=("two", "dos"), positional=False)

    assert Example(1, dos=2).second == 2
    with pytest.raises(TypeError):
        Example(uno=1, dos=2)
    assert str(inspect.signature(Example)) == (
        "(one: int, /, *, two: int) -> None"
    )


def test_frozen_and_single_assignment_pipeline() -> None:
    calls = []

    def convert(value: int) -> int:
        calls.append(value)
        return int(value)

    class Example(Magic):
        value: int = field(property="other", converter=convert)

    obj = Example(1)
    obj.other = 2
    assert calls == [1, 2]

    class Frozen(Magic, frozen=True):
        value: Property[int, "other"]

    with pytest.raises(AttributeError, match="frozen"):
        Frozen(1).other = 2


def test_class_options_respect_inherited_and_explicit_preferences() -> None:
    class Base(Magic):
        _value: int
        _explicit: int = field(property=False, alias=False)

    class Inherited(Base, property=True, alias=True):
        _extra: int

    assert not hasattr(Inherited(1, 2, 3), "value")
    assert Inherited(1, 2, 3).extra == 3

    class Overridden(Base, property=True, alias=True, override=True):
        pass

    obj = Overridden(1, 2)
    assert obj.value == 1
    assert not hasattr(obj, "explicit")
    assert fields(Overridden)[1].aliases == ("_explicit",)
    assert not hasattr(Base(1, 2), "value")


def test_redeclaration_removes_old_properties_without_changing_base() -> None:
    class Base(Magic):
        value: Property[Alias[int, ("value", "old")], "old"]

    class Child(Base):
        value: Property[Alias[int, ("value", "new")], "new"]

    assert Base(old=1).old == 1
    assert Child(new=1).new == 1
    assert not hasattr(Child(1), "old")
    with pytest.raises(AttributeError):
        Child(1).old = 2
    with pytest.raises(AttributeError):
        del Child(1).old
    with pytest.raises(TypeError):
        Child(old=1)


def test_subclass_own_attribute_shadows_inherited_property() -> None:
    # Dropping the property in a redeclaration and defining that name in
    # the class body keeps the class's own attribute, rather than masking
    # it as a disabled property.
    class Base(Magic):
        value: Property[Alias[int, ("value", "old")], "old"]

    class Child(Base):
        value: int
        old = 5

    assert Base(old=1).old == 1
    assert Child(1).old == 5


def test_override_disables_inherited_implicit_property() -> None:
    class Base(Magic, property=True):
        _value: int

    class Child(Base, property=False, override="property"):
        pass

    assert Base(1).value == 1
    assert not hasattr(Child(1), "value")


@pytest.mark.parametrize(
    "declaration", ["", (), [], ("a", "a"), ("good", "not-valid"), 1]
)
def test_invalid_alias_declarations(declaration: tx.Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        field(alias=declaration)


def test_double_underscore_input_alias_remains_valid() -> None:
    class Example(Magic):
        value: Alias[int, "__value"]

    assert Example(__value=3).value == 3


@pytest.mark.parametrize(
    "declaration", [{"other": "bad"}, ["x", "x"], "__dunder", 1]
)
def test_invalid_property_declarations(declaration: tx.Any) -> None:
    with pytest.raises((ValueError, TypeError)):
        field(property=declaration)


def test_inherited_alias_collision_and_explicit_reassignment() -> None:
    class Base(Magic):
        first: Alias[int, ("first", "other")]

    with pytest.raises(TypeError, match="other"):

        class Conflict(Base):
            second: Alias[int, ("second", "other")]

    class Reassigned(Base):
        first: int
        second: Alias[int, ("second", "other")]

    obj = Reassigned(1, other=2)
    assert (obj.first, obj.second) == (1, 2)


def test_multiple_inheritance_collision() -> None:
    class Left(Magic):
        first: Alias[int, ("first", "other")]

    class Right(Magic):
        second: Alias[int, ("second", "other")]

    with pytest.raises(TypeError, match="other"):

        class Conflict(Left, Right):
            pass


def test_property_collisions() -> None:
    with pytest.raises(TypeError, match="conflicts"):

        class Method(Magic):
            value: Property[int, "method"]
            method = object()

    with pytest.raises(TypeError, match="itself"):

        class SelfTarget(Magic):
            value: Property[int, "value"]

    with pytest.raises(TypeError, match="conflicts"):

        class OtherField(Magic):
            value: Property[int, "other"]
            other: int

    class Base(Magic):
        value: int
        method = object()

    with pytest.raises(TypeError, match="inherited attribute"):

        class InheritedMethod(Base):
            value: Property[int, "method"]


@pytest.mark.parametrize("kind", [ClassVar, InitVar])
def test_pseudo_fields_cannot_have_properties(kind: tx.Any) -> None:
    with pytest.raises(TypeError, match="stored instance field"):

        class Example(Magic):
            value: kind[int] = field(property="other")


def test_initvar_aliases() -> None:
    class Example(Magic):
        value: int = 0
        input: InitVar[Alias[int, ("input", "other")]] = 1

        def __post_init__(self, arguments: tx.Any) -> None:
            self.value = arguments.input

    assert Example(other=3).value == 3
    assert replace(Example(), other=4).value == 4


def test_polymorphic_selection_and_duplicates() -> None:
    class Base(Magic, polymorphic=True):
        kind: Alias[str, ("kind", "type")]
        value: int = 0

    class Child(Base, on={"kind": "child"}):
        pass

    assert isinstance(Base(type="child"), Child)
    assert isinstance(Child(type="child"), Child)
    with pytest.raises(TypeError, match="multiple values"):
        Base("child", type="child")


def test_decorator_custom_init_and_self_alias() -> None:
    @magic
    class Example:
        name: Alias[str, ("self", "other")]

        def __init__(self, raw: str) -> None:
            self.__magic_init__(other=raw)

    assert Example("Ada").name == "Ada"
    assert str(inspect.signature(Example)) == "(raw: str) -> None"


def test_generic_property_aliases() -> None:
    t = tx.TypeVar("t")

    class Example(Magic, tx.Generic[t], convert=True, alias=True):
        value: Property[t, "other"]

    obj = Example[int](other="2")
    assert obj.other == 2
    obj.other = "3"
    assert obj.value == 3


@pytest.mark.parametrize("slots", [False, True])
def test_removed_property_can_become_a_stored_field(slots: bool) -> None:
    class Base(Magic, slots=slots):
        first: Property[int, "other"]

    class Child(Base):
        first: int
        other: int

    obj = Child(1, 2)
    assert (obj.first, obj.other) == (1, 2)
    obj.other = 3
    assert obj.first == 1
    assert Base(1).other == 1
    if not slots:
        with pytest.raises(AttributeError, match="has not been set"):
            _ = object.__new__(Child).other


def test_property_cannot_claim_other_fields_input_alias() -> None:
    with pytest.raises(TypeError, match="conflicts"):

        class Conflict(Magic):
            first: Alias[int, "input"]
            second: Property[int, "input"]


def test_class_property_policy_skips_pseudo_fields() -> None:
    class Example(Magic, property=True):
        _value: int
        _init: InitVar[int] = 0
        _class: ClassVar[int] = 1

    assert Example(2).value == 2
    assert not hasattr(Example(2), "init")


def test_readonly_shorthand_and_none_default() -> None:
    class Example(Magic, property="readonly"):
        _value: int = None

    obj = Example()
    assert obj.value is None
    with pytest.raises(AttributeError):
        obj.value = 3
    obj._value = 3
    assert obj.value == 3


def test_read_only_property_sugar() -> None:
    class Bare(Magic, alias=True):
        _value: ReadOnlyProperty[int]

    obj = Bare(3)
    assert obj.value == 3
    with pytest.raises(AttributeError):
        obj.value = 4

    class Named(Magic):
        value: ReadOnlyProperty[int, ("label", "title")]

    named = Named(3)
    assert named.label == named.title == 3
    with pytest.raises(AttributeError):
        named.label = 4
    with pytest.raises(AttributeError):
        named.title = 4

    class Mixed(Magic):
        value: ReadOnlyProperty[int, {"shown": True, "hidden": False}]

    mixed = Mixed(3)
    assert mixed.shown == 3
    assert not hasattr(mixed, "hidden")
    with pytest.raises(AttributeError):
        mixed.shown = 4


def test_read_only_property_matches_property_with_readonly_mapping() -> None:
    class Sugar(Magic):
        value: ReadOnlyProperty[int, ("a", "b")]

    class Spelled(Magic):
        value: Property[int, {"a": "readonly", "b": "readonly"}]

    expected = {"a": "readonly", "b": "readonly"}
    assert fields(Sugar)[0].properties == expected
    assert fields(Spelled)[0].properties == expected


def test_stacked_property_hints_merge() -> None:
    # Stacked Property hints accumulate: the outer adds to the inner
    # rather than replacing it. A name declared on both takes the outer
    # access mode.
    class Example(Magic):
        value: Property[Property[int, "inner"], "outer"]

    obj = Example(3)
    assert obj.outer == obj.inner == 3
    assert fields(Example)[0].properties == {"inner": True, "outer": True}

    class SameName(Magic):
        value: Property[
            Property[int, {"a": True, "b": True}], {"a": "readonly"}
        ]

    fs = fields(SameName)[0]
    assert fs.properties == {"a": "readonly", "b": True}


def test_stacked_alias_hints_merge() -> None:
    # Stacked Alias hints concatenate, keeping order and the first
    # spelling of a repeated name, so the preferred public name is the
    # first one written.
    class Example(Magic):
        name: Alias[Alias[int, ("label", "name")], ("title", "name")]

    f = fields(Example)[0]
    assert f.aliases == ("label", "name", "title")
    assert f.public_name == "label"
    assert Example(title=7).name == 7
    assert Example(label=8).name == 8


def test_stacked_metadata_merges() -> None:
    class Example(Magic):
        x: tx.Annotated[
            int, Field(metadata={"a": 1}), Field(metadata={"b": 2})
        ]

    assert fields(Example)[0].metadata == {"a": 1, "b": 2}


def test_whole_field_property_mode_stays_last_wins() -> None:
    # A whole-field toggle is not a collection, so the outer replaces the
    # inner rather than merging.
    class Example(Magic):
        value: Property[Property[int, "inner"], "all"]

    assert fields(Example)[0].property == "all"


def test_stacked_converters_chain() -> None:
    # Stacked converters chain, the inner running first.
    class Example(Magic):
        x: ConvertTo[ConvertTo[int, lambda v: v + 1], lambda v: v * 10]

    assert Example(0).x == 10  # (0 + 1) * 10


def test_stacked_validators_chain() -> None:
    # Stacked validators both run, the inner first.
    seen = []

    def low(value: int) -> int:
        seen.append("low")
        if value < 0:
            raise ValueError("too low")
        return value

    def high(value: int) -> int:
        seen.append("high")
        if value > 100:
            raise ValueError("too high")
        return value

    class Example(Magic):
        x: Validate[Validate[int, low], high]

    assert Example(5).x == 5
    assert seen == ["low", "high"]
    with pytest.raises(ValueError):
        Example(-1)
    with pytest.raises(ValueError):
        Example(200)


def test_type_derived_step_is_not_chained() -> None:
    # A type-derived converter (`ConvertTo[int]`) is not yet a callable to
    # chain when the class is built, so stacking it with an explicit one
    # is last-wins.
    class Example(Magic):
        x: ConvertTo[ConvertTo[int], lambda v: ("wrapped", v)]

    assert Example(5).x == ("wrapped", 5)


def test_property_true_exposes_only_the_public_name() -> None:
    # `property=True` (and "readonly") expose the preferred public name
    # alone -- the other input aliases are not forwarded.
    class Example(Magic, property=True):
        name: Alias[int, ("label", "name", "title")]

    assert fields(Example)[0].properties == {"label": True}
    obj = Example(title=1)
    assert obj.name == obj.label == 1
    assert not hasattr(obj, "title")
    obj.label = 2
    assert obj.name == 2


def test_property_all_exposes_every_alias() -> None:
    # `property="all"` forwards every input name the field accepts, bar
    # the stored attribute itself.
    class Example(Magic, property="all"):
        name: Alias[int, ("label", "name", "title")]

    assert fields(Example)[0].properties == {"label": True, "title": True}
    obj = Example(title=1)
    assert obj.name == obj.label == obj.title == 1
    obj.label = 2
    assert obj.name == obj.title == 2


def test_read_only_property_forces_read_only_and_keeps_disabled() -> None:
    # A read/write request through ReadOnlyProperty is forced read-only,
    # and a disabled name stays off.
    class Forced(Magic, alias=True):
        _value: ReadOnlyProperty[int, "readwrite"]

    obj = Forced(3)
    assert obj.value == 3
    with pytest.raises(AttributeError):
        obj.value = 4

    class Disabled(Magic):
        value: ReadOnlyProperty[int, False]

    assert fields(Disabled)[0].properties == {}
    assert Disabled(3).value == 3


def test_read_only_property_all_is_read_only() -> None:
    class Example(Magic):
        name: ReadOnlyProperty[Alias[int, ("label", "name", "title")], "all"]

    assert fields(Example)[0].properties == {
        "label": "readonly", "title": "readonly"
    }
    obj = Example(title=1)
    assert obj.label == obj.title == 1
    with pytest.raises(AttributeError):
        obj.label = 2


def test_property_all_skips_names_already_taken() -> None:
    # An auto-derived property yields to a name the class already uses,
    # rather than refusing the class.
    class WithMethod(Magic, property="all"):
        value: Alias[int, ("value", "count")]

        def count(self) -> str:
            return "method"

    obj = WithMethod(5)
    assert obj.value == 5
    assert obj.count() == "method"

    # An explicit property targeting a taken name is still an error.
    with pytest.raises(TypeError, match="conflicts"):

        class Explicit(Magic):
            value: Property[int, "count"]

            def count(self) -> str:
                return "method"


def test_property_all_skips_double_underscore_alias() -> None:
    # A double-underscore input alias is a valid keyword but cannot be a
    # property, so the auto-expansion leaves it out instead of building an
    # attribute Python would reserve.
    class Example(Magic, property="all"):
        value: Alias[int, ("value", "__secret")]

    assert fields(Example)[0].properties == {}
    assert "__secret" not in Example.__dict__
    assert Example(__secret=3).value == 3
