"""Public field queries share filters, order and field identity."""

import inspect

import pytest
import typing_extensions as tx

from bagof.magic import (
    ClassVar,
    ConvertTo,
    Field,
    InitVar,
    Magic,
    NoInit,
    dictfields,
    fields,
    fields_dict,
    iterfields,
)


@pytest.fixture
def example() -> type:
    class Base(Magic):
        inherited: int

    class Example(Base):
        _value: tx.Annotated[int, Field(alias="amount", frozen=True)]
        converted: ConvertTo[int] = 0
        optional: tx.Optional[int] = None
        cached: NoInit[int] = 0
        scratch: InitVar[int] = 1
        shared: ClassVar[str] = "units"

    return Example


@pytest.mark.parametrize("query", [
    fields, iterfields, dictfields, fields_dict,
])
@pytest.mark.parametrize("filters, expected", [
    ({}, ["inherited", "_value", "converted", "optional", "cached"]),
    ({"var": True}, ["scratch", "shared"]),
    ({"var": None}, [
        "inherited", "_value", "converted", "optional", "cached",
        "scratch", "shared",
    ]),
    ({"var": True, "init": True}, ["scratch"]),
    ({"var": True, "init": False}, ["shared"]),
    ({"init": False}, ["cached"]),
    ({"var": None, "init": False}, ["cached", "shared"]),
    ({"frozen": True}, ["_value"]),
    ({"convert": True}, ["converted"]),
    ({"convert": True, "init": False}, []),
    ({"type": int, "default": 0}, ["converted", "cached"]),
    ({"default": None}, ["optional"]),
    ({"name": "_value"}, ["_value"]),
    ({"public_name": "amount"}, ["_value"]),
    ({"var": True, "default": "units"}, ["shared"]),
])
def test_field_filters(
    example: type, query: tx.Callable, filters: dict, expected: list,
) -> None:
    found = query(example, **filters)
    values = list(found.values()) if isinstance(found, dict) else list(found)
    assert [field.name for field in values] == expected
    assert all(
        field is example.__magic_fields__[field.name] for field in values
    )


def test_return_types_and_iterator(example: type) -> None:
    assert isinstance(fields(example), tuple)
    assert isinstance(dictfields(example), dict)
    found = iterfields(example)
    assert iter(found) is found
    assert next(found).name == "inherited"
    assert [field.name for field in found] == [
        "_value", "converted", "optional", "cached",
    ]
    assert list(found) == []


def test_dict_key_choices(example: type) -> None:
    assert list(dictfields(example, frozen=True)) == ["amount"]
    assert list(dictfields(example, by="name", frozen=True)) == ["_value"]
    public = dictfields(example, by="public_name", frozen=True)
    assert list(public) == ["amount"]
    assert list(fields_dict(example, frozen=True)) == ["amount"]
    assert list(fields_dict(example, by="name", frozen=True)) == ["_value"]
    assert dictfields(example) == fields_dict(example)


@pytest.mark.parametrize("query", [dictfields, fields_dict])
def test_public_names_strip_underscores(query: tx.Callable) -> None:
    class Example(Magic):
        _value: int

    assert list(query(Example)) == ["value"]
    assert list(query(Example, by="name")) == ["_value"]
    assert list(query(Example, by="public_name")) == ["value"]


@pytest.mark.parametrize("query", [
    fields, iterfields, dictfields, fields_dict,
])
def test_plain_classes_have_no_fields(query: tx.Callable) -> None:
    class Plain:
        value: int

    assert not list(query(Plain))
    assert not list(query(Plain, var=None, init=True))


@pytest.mark.parametrize("query", [
    fields, iterfields, dictfields, fields_dict,
])
@pytest.mark.parametrize("attribute", [
    "unknown", "_declared", "update", "__class__",
])
def test_invalid_attributes_are_rejected_eagerly(
    query: tx.Callable, attribute: str,
) -> None:
    with pytest.raises(TypeError, match="Unknown field attribute"):
        query(Magic, **{attribute: True})


@pytest.mark.parametrize("query", [
    fields, iterfields, dictfields, fields_dict,
])
@pytest.mark.parametrize("value", [0, 1, "all"])
def test_invalid_var_is_rejected(query: tx.Callable, value: tx.Any) -> None:
    with pytest.raises(TypeError, match="var must be"):
        query(Magic, var=value)


@pytest.mark.parametrize("query", [dictfields, fields_dict])
def test_invalid_dictionary_key_is_rejected(query: tx.Callable) -> None:
    with pytest.raises(TypeError, match="by must be"):
        query(Magic, by="alias")


def test_queries_do_not_change_constructor_or_registry(example: type) -> None:
    before = inspect.signature(example)
    registry = example.__magic_fields__
    fields(example, var=True, init=False)
    dictfields(example, var=None, by="public_name")
    list(iterfields(example, var=None, init=True))
    assert example.__magic_fields__ is registry
    assert inspect.signature(example) == before
    assert list(registry) == [
        "inherited", "_value", "converted", "optional", "cached",
        "scratch", "shared",
    ]
