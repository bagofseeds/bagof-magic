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

from ._constants import _FIELDS, MISSING
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


def _keyed(found: tx.Sequence[Field]) -> tx.Dict[str, Field]:
    """Key fields by the name they are known by outside the class.

    Two fields can only collide here when neither is a constructor
    argument: the constructor refuses to be built with a duplicate
    parameter, so it has already ruled the common case out.
    """
    keyed = {}
    for field in found:
        name = field.public_name
        if name in keyed:
            raise TypeError(
                f"fields {keyed[name].name!r} and {field.name!r} are both "
                f"known as {name!r} outside the class, so they cannot both "
                f"appear under that name. Give one of them its own alias."
            )
        keyed[name] = field
    return keyed


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
    table = _field_table(obj, "asdict")
    keyed = _keyed([field for field in table.values() if not field.var])
    return {
        name: getattr(obj, field.name) for name, field in keyed.items()
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
    table = _field_table(obj, "astuple")
    return tuple(
        getattr(obj, field.name)
        for field in table.values() if not field.var
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
    """
    table = _field_table(obj, "replace")
    given, values = dict(changes), {}
    for field in table.values():
        name = field.public_name
        if not field.init:
            if name in given:
                raise TypeError(
                    f"{type(obj).__name__} does not take {name!r} when it "
                    f"is built, so replace() has no way to set it."
                )
            continue
        if name in given:
            values[name] = given.pop(name)
        elif not field.var:
            values[name] = getattr(obj, field.name)
        elif field.default is MISSING and not field.factory:
            # An InitVar is used during construction and not stored, so
            # a required one has to be given again every time.
            raise TypeError(
                f"{type(obj).__name__} needs {name!r} to be built and does "
                f"not keep it afterwards, so replace() cannot reuse the "
                f"one it was built with: pass {name}= as well."
            )
    if given:
        named = ", ".join(repr(name) for name in given)
        raise TypeError(
            f"{type(obj).__name__} has no field named {named}."
        )
    return type(obj)(**values)


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
