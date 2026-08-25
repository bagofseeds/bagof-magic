"""
Functions you call on a Magic class or one of its instances.

Everything here speaks the names the constructor uses. A field can be
written under one name in the class body and reach `__init__` under
another -- because it starts with an underscore, or because it was given
an alias -- and it is that second name these functions use as a key, and
that `replace` expects its keyword arguments to be named after. It is
also the name `repr()` shows.
"""
from __future__ import annotations

import typing_extensions as tx

from ._constants import _FIELDS, MISSING, _HasFactory
from ._fields import Field

__all__ = [
    "fields",
    "fields_dict",
    "asdict",
    "astuple",
    "replace",
    "is_magic",
]


def _field_table(obj: tx.Any, caller: str) -> tx.Dict[str, Field]:
    """Every field of an instance's class, pseudo-fields included.

    The lookup goes through `type(obj)` rather than `obj`, so a class
    handed in by mistake is reported instead of being read as if it were
    an instance: a class carries the table, its metaclass does not.
    """
    cls = type(obj)
    table = getattr(cls, _FIELDS, None)
    if table is None:
        raise TypeError(
            f"{caller}() needs an instance of a Magic class, and "
            f"{obj!r} is not one."
        )
    return table


def _keyed(found: tx.Iterable[Field]) -> tx.Dict[str, Field]:
    """Key fields by the name they are known by outside the class.

    One name reaches one field: a class with two fields under a single
    outside name is refused when it is built, so the keys here never
    collide.
    """
    return {field.public_name: field for field in found}


def _value(obj: tx.Any, field: Field, caller: str) -> tx.Any:
    """The value a field holds, or a written error if it holds none."""
    try:
        return getattr(obj, field.name)
    except AttributeError:
        # A field that is not a constructor argument and has no default
        # is only ever set by hand, so an object can be perfectly usable
        # and still have nothing under this name.
        raise AttributeError(
            f"{type(obj).__name__}.{field.name} has never been given a "
            f"value, so {caller}() has nothing to report for it. Give the "
            f"field a default, or set it in __post_init__."
        ) from None


def _concrete(obj: tx.Any, caller: str) -> tx.Dict[str, Field]:
    """An instance's real fields, keyed by their outside name."""
    table = _field_table(obj, caller)
    return _keyed(field for field in table.values() if not field.var)


def fields(cls: type) -> tx.Tuple[Field]:
    """
    Get the fields of a Magic class.

    Parameters
    ----------
    cls : type
        The class to get the fields of.

    Returns
    -------
    fields : tuple[Field]
        All concrete fields (that are not `ClassVar` or `InitVar`).
    """
    return tuple(
        field for field in getattr(cls, _FIELDS, {}).values()
        if not field.var
    )


def fields_dict(cls: type) -> tx.Dict[str, Field]:
    """
    Get the fields of a Magic class, keyed by name.

    The same fields `fields` returns, in the same order, keyed by the
    name each one is known by outside the class -- the name the
    constructor takes, which for an aliased or underscored field is not
    the name the class body uses.

    Parameters
    ----------
    cls : type
        The class to get the fields of.

    Returns
    -------
    fields : dict[str, Field]
        All concrete fields (that are not `ClassVar` or `InitVar`).
        A class that `Magic` never built simply has none, so the answer
        is an empty dict -- the same as `fields` gives. `asdict`,
        `astuple` and `replace` need a real instance and say so instead.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> list(fields_dict(Point))
        ['x', 'y']
        >>> fields_dict(Point)["x"].type
        <class 'int'>
        ```
    """
    return _keyed(fields(cls))


def asdict(obj: tx.Any) -> tx.Dict[str, tx.Any]:
    """
    Get an object's fields as a plain `dict`.

    Values come back exactly as they are stored: nothing is copied,
    converted, or looked inside. A field holding a list gives you *that*
    list, and a field holding another Magic object gives you the object
    itself, not a dict of its fields. If you want a copy, or a nested
    object turned into a dict too, do it yourself -- that way you decide
    how deep to go and what to do with the things that are neither.

    Keys are the names the constructor takes, which for an aliased or
    underscored field is not the name the class body uses.

    Parameters
    ----------
    obj : Magic
        An instance of a Magic class.

    Returns
    -------
    values : dict[str, any]
        Every concrete field (not `ClassVar` or `InitVar`), in field
        order.

    Raises
    ------
    AttributeError
        If a field has never been given a value. A field the
        constructor does not take, with no default, is only set if
        something sets it by hand.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> asdict(Point(1, 2))
        {'x': 1, 'y': 2}
        ```

    !!! example "A nested object is left alone"
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> class Line(Magic):
        ...     start: Point
        ...     end: Point
        ...
        >>> asdict(Line(Point(0, 0), Point(1, 2)))
        {'start': Point(x=0, y=0), 'end': Point(x=1, y=2)}
        ```

    !!! note "Not the same as `dict(obj)`"
        A class written with `mapping=True` can be passed to `dict`
        directly, and that covers the fields marked as keys, under the
        key names they were given. `asdict` always covers every field.

        ```pycon
        >>> class Row(Magic, mapping=True):
        ...     name: str
        ...     age: NotKey[int]
        ...
        >>> dict(Row("ada", 36))
        {'name': 'ada'}
        >>> asdict(Row("ada", 36))
        {'name': 'ada', 'age': 36}
        ```
    """
    return {
        name: _value(obj, field, "asdict")
        for name, field in _concrete(obj, "asdict").items()
    }


def astuple(obj: tx.Any) -> tx.Tuple[tx.Any, ...]:
    """
    Get an object's field values as a tuple, in field order.

    Values come back exactly as they are stored, the same way `asdict`
    returns them: nothing is copied, converted, or looked inside.

    Parameters
    ----------
    obj : Magic
        An instance of a Magic class.

    Returns
    -------
    values : tuple
        The value of every concrete field (not `ClassVar` or `InitVar`),
        in field order.

    Raises
    ------
    AttributeError
        If a field has never been given a value, as for `asdict`.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> astuple(Point(1, 2))
        (1, 2)
        ```
    """
    # The same fields `asdict` reports, worked out the same way: a class
    # whose fields cannot be told apart by name is refused by both,
    # rather than answering a tuple here and an error there.
    return tuple(
        _value(obj, field, "astuple")
        for field in _concrete(obj, "astuple").values()
    )


# From Python 3.13 `copy.replace(obj, **changes)` calls
# `type(obj).__replace__(obj, **changes)`, which is the signature this
# function already has -- so hooking it up is one assignment. It is not
# done here because `Magic.__replace__ = replace` would only reach the
# classes that inherit from `Magic`, and miss the ones the `magic`
# decorator builds; the method belongs with the other generated ones.
def replace(obj: tx.Any, **changes: tx.Any) -> tx.Any:
    """
    Copy an object, changing some of its values.

    The copy is built by calling the class again, so conversion,
    validation and the `__pre_init__` / `__post_init__` hooks all run on
    the way in: a replaced value is checked exactly as an original one
    is. Anything you do not mention is carried over unchanged. It works
    on a frozen class, which is where it is most useful.

    Name each change after the argument the constructor takes, which for
    an aliased or underscored field is not the name the class body uses.

    Parameters
    ----------
    obj : Magic
        An instance of a Magic class.
    **changes : any
        New values, by constructor argument name.

    Returns
    -------
    copy : Magic
        A new instance of the same class.

    Raises
    ------
    TypeError
        If `obj` is not an instance of a Magic class; if a change names
        something the constructor does not take; or if the class has an
        `InitVar` with no default and no value was given for it.

    !!! example
        ```pycon
        >>> class Point(Magic, frozen=True):
        ...     x: int
        ...     y: int
        ...
        >>> replace(Point(1, 2), y=20)
        Point(x=1, y=20)
        ```

    !!! note "Two kinds of field cannot be carried over"
        A field written as `NoInit[...]` is not a constructor argument,
        so the copy gets whatever the class gives it rather than the
        value `obj` holds. An `InitVar` is passed in and not kept, so
        there is nothing to read back off `obj`: give it again, or leave
        it to its default.

    !!! warning "A `__post_init__` that derives a field runs again"
        The copy starts from the values as they are *stored*, so a hook
        that works one field out from another works it out a second
        time -- from the already worked-out value. `replace` with no
        changes at all can then come back different:

        ```pycon
        >>> class Priced(Magic):
        ...     total: float
        ...     vat: InitVar[float] = 0.2
        ...
        ...     def __post_init__(self, arguments):
        ...         self.total = self.total * (1 + arguments.vat)
        ...
        >>> order = Priced(100.0)
        >>> order
        Priced(total=120.0)
        >>> replace(order)
        Priced(total=144.0)
        ```

        A hook that only checks its arguments, or that fills in a field
        the constructor does not take, is unaffected.
    """
    cls = type(obj)
    # Every field, pseudo-fields included: a change has to be turned
    # down by name whether or not the name belongs to a real field, and
    # a class that cannot tell two of its fields apart cannot say which
    # one a change was meant for.
    keyed = _keyed(_field_table(obj, "replace").values())
    given, arguments = dict(changes), []
    for name, field in keyed.items():
        # A field the constructor does not take -- `NoInit`, or one
        # that can be passed neither by position nor by name -- has no
        # way in.
        if not field.init:
            if name in given:
                raise TypeError(
                    f"{cls.__name__} does not take {name!r} when it is "
                    f"built, so replace() has no way to set it."
                )
            continue
        if name in given:
            value = given.pop(name)
        elif not field.var:
            value = _value(obj, field, "replace")
        elif field.factory:
            # An InitVar is used during construction and not stored, so
            # there is nothing to carry over: its default stands in.
            # The constructor resolves a factory itself, and this is
            # what it would have been handed.
            value = _HasFactory(field.factory)
        elif field.default is not MISSING:
            value = field.default
        else:
            raise TypeError(
                f"{cls.__name__} needs {name!r} to be built and does not "
                f"keep it afterwards, so replace() cannot reuse the one it "
                f"was built with: pass {name}= as well."
            )
        arguments.append((field, value))
    if given:
        named = ", ".join(repr(name) for name in given)
        raise TypeError(f"{cls.__name__} has no field named {named}.")
    # A positional-only field cannot be named and a keyword-only one
    # cannot be counted off, so each value goes back the way its own
    # field is allowed to be passed. Positional-only fields come first
    # in the signature, in field order, which is the order they were
    # collected in.
    positional, keyword = [], {}
    for field, value in arguments:
        if field.positional and not field.kw:
            positional.append(value)
        else:
            keyword[field.public_name] = value
    return cls(*positional, **keyword)


def is_magic(obj: tx.Any) -> bool:
    """
    Say whether something was built by `Magic`.

    Answers for a class or for one of its instances, and for a class
    built either way -- by inheriting from `Magic`, or by decorating a
    plain class with `magic`.

    Parameters
    ----------
    obj : any
        A class, or any object at all.

    Returns
    -------
    is_magic : bool
        Whether the class, or the object's class, is a Magic class.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...
        >>> is_magic(Point), is_magic(Point(1))
        (True, True)
        >>> is_magic(int), is_magic(3)
        (False, False)
        ```
    """
    cls = obj if isinstance(obj, type) else type(obj)
    # The question is whether the class carries the table of fields the
    # builder writes, which is what every generated method reads. Two
    # shorter tests answer a different question: `issubclass(cls, Magic)`
    # says no for a class built by the `magic` decorator, which gains the
    # fields and the generated methods without gaining `Magic` as a base;
    # and `isinstance(obj, Magic)` says no for every class, since a class
    # is not an instance of its own base. Reducing an instance to its
    # class first is what lets one check cover both shapes.
    return getattr(cls, _FIELDS, None) is not None
