"""
Functions you call on a Magic class or one of its instances.

Every function here uses the name the constructor takes. A field whose
class-body name starts with an underscore, or that has an alias, reaches
``__init__`` under a different name. That public name is the key in
``fields_dict``, the keyword in ``replace``, and the label in ``repr``.
"""
import typing_extensions as tx

from ._constants import _FIELDS, MISSING, _HasFactory
from ._fields import Field, _stored

__all__ = [
    "fields",
    "fields_dict",
    "asdict",
    "astuple",
    "replace",
    "is_magic",
]


def _asdict_inner(obj: tx.Any) -> tx.Any:
    """Walk a value, recursing into Magic instances and containers."""
    cls = type(obj)
    if getattr(cls, _FIELDS, None) is not None:
        return {
            name: _asdict_inner(value)
            for name, field in _keyed(
                f for f in getattr(cls, _FIELDS).values() if not f.var
            ).items()
            for has_value, value in (_stored(obj, field),)
            if has_value
        }
    if isinstance(obj, tuple) and hasattr(obj, "_fields"):
        return type(obj)(*(_asdict_inner(v) for v in obj))
    if isinstance(obj, (list, tuple)):
        return type(obj)(_asdict_inner(v) for v in obj)
    if isinstance(obj, dict):
        return type(obj)(
            (_asdict_inner(k), _asdict_inner(v)) for k, v in obj.items()
        )
    return obj


def _astuple_inner(obj: tx.Any) -> tx.Any:
    """Walk a value, recursing into Magic instances and containers."""
    cls = type(obj)
    if getattr(cls, _FIELDS, None) is not None:
        return tuple(
            _astuple_inner(_value(obj, field, "astuple"))
            for field in _keyed(
                f for f in getattr(cls, _FIELDS).values() if not f.var
            ).values()
        )
    if isinstance(obj, tuple) and hasattr(obj, "_fields"):
        return type(obj)(*(_astuple_inner(v) for v in obj))
    if isinstance(obj, (list, tuple)):
        return type(obj)(_astuple_inner(v) for v in obj)
    if isinstance(obj, dict):
        return type(obj)(
            (_astuple_inner(k), _astuple_inner(v)) for k, v in obj.items()
        )
    return obj


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
    has_value, value = _stored(obj, field)
    if not has_value:
        raise AttributeError(
            f"{type(obj).__name__}.{field.name} has never been given a "
            f"value, so {caller}() has nothing to report for it. Give the "
            f"field a default, or set it in __post_init__."
        )
    return value


def _concrete(obj: tx.Any, caller: str) -> tx.Dict[str, Field]:
    """An instance's real fields, keyed by their outside name."""
    table = _field_table(obj, caller)
    return _keyed(field for field in table.values() if not field.var)


def fields(cls: type) -> tx.Tuple[Field]:
    """
    Return the fields of a Magic class as a tuple.

    Only concrete fields are included, so `ClassVar` and `InitVar`
    fields are left out. A class that Magic did not build has no
    fields, and the result for it is an empty tuple.

    Parameters
    ----------
    cls : type
        A Magic class (not an instance).

    Returns
    -------
    fields : tuple[Field, ...]
        The class's concrete fields, in declaration order.
    """
    return tuple(
        field for field in getattr(cls, _FIELDS, {}).values()
        if not field.var
    )


def fields_dict(cls: type) -> tx.Dict[str, Field]:
    """
    Return the fields of a Magic class, keyed by their public names.

    The result holds the same fields as [`fields`][], in the same order.
    Each field is keyed by its public name, which is the name the
    constructor takes. For a field with an alias, or a field whose name
    starts with an underscore, the public name differs from the name
    used in the class body.

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

    Parameters
    ----------
    cls : type
        The class to get the fields of.

    Returns
    -------
    fields : dict[str, Field]
        Every field that is not a `ClassVar` or an `InitVar`. A class
        that Magic did not build has no fields, so the result for it is
        an empty dict, as with [`fields`][]. [`asdict`][], [`astuple`][]
        and [`replace`][] need an instance of a Magic class instead, and
        raise an error for anything else.
    """
    return _keyed(fields(cls))


def asdict(obj: tx.Any) -> tx.Dict[str, tx.Any]:
    """
    Return the fields of a Magic instance as a plain `dict`.

    A field that holds another Magic instance is turned into a dict of
    that instance's fields, and so on at every level. Magic instances
    inside lists, tuples and dicts are turned into dicts too, and every
    other value is returned as it is.

    The keys are the names that the constructor takes. For a field with
    an alias, or a field whose name starts with an underscore, the key
    differs from the name used in the class body.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> asdict(Point(1, 2))
        {'x': 1, 'y': 2}
        ```

    !!! example "Nested Magic objects become dicts"
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
        {'start': {'x': 0, 'y': 0}, 'end': {'x': 1, 'y': 2}}
        >>> class Path(Magic):
        ...     points: list
        ...
        >>> asdict(Path([Point(0, 0), Point(1, 2)]))
        {'points': [{'x': 0, 'y': 0}, {'x': 1, 'y': 2}]}
        ```

    !!! note "A field with no value is left out"
        A field that the constructor does not take, and that has no
        default, holds nothing until something sets it. Such a field is
        absent from the result, in the way that an optional key is absent
        from a dict, and it appears as soon as it is given a value:

        ```pycon
        >>> class Draft(Magic):
        ...     title: str
        ...     slug: NoInit[str]
        ...
        >>> draft = Draft("Ada")
        >>> asdict(draft)
        {'title': 'Ada'}
        >>> draft.slug = "ada"
        >>> asdict(draft)
        {'title': 'Ada', 'slug': 'ada'}
        ```

        [`astuple`][] raises an error for such a field instead. A key
        says which field a value belongs to and a position does not, so
        a tuple can only be read correctly while every field is in it.

    !!! note "Not the same as `dict(obj)`"
        An instance of a class written with `mapping=True` can be passed
        to `dict` directly. The result covers only the fields that are
        keys, under their key names, whereas `asdict` covers every field.
        Both leave out a field that holds no value.

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

    Parameters
    ----------
    obj : Magic
        An instance of a Magic class.

    Returns
    -------
    values : dict[str, any]
        Every field that holds a value, in field order, leaving out
        `ClassVar` and `InitVar` fields.
    """
    found = {}
    for name, field in _concrete(obj, "asdict").items():
        has_value, value = _stored(obj, field)
        if has_value:
            found[name] = _asdict_inner(value)
    return found


def astuple(obj: tx.Any) -> tx.Tuple[tx.Any, ...]:
    """
    Return the field values of a Magic instance as a tuple, in field order.

    As in [`asdict`][], a nested Magic instance is turned into a tuple of
    its own field values, and every other value is returned as it is.

    !!! example
        ```pycon
        >>> class Point(Magic):
        ...     x: int
        ...     y: int
        ...
        >>> astuple(Point(1, 2))
        (1, 2)
        ```

    !!! note "A field with no value is an error here"
        [`asdict`][] and `dict(obj)` leave such a field out, but
        `astuple` raises an error. A position only has a meaning while
        every field is in the tuple. If one field were dropped, every
        field after it would move up, and the same index would stand for
        different fields in different instances, with nothing in the
        tuple to show it.

    Parameters
    ----------
    obj : Magic
        An instance of a Magic class.

    Returns
    -------
    values : tuple
        The value of every field, in field order, leaving out `ClassVar`
        and `InitVar` fields.

    Raises
    ------
    AttributeError
        If a field has never been given a value. A field that the
        constructor does not take, and that has no default, holds a
        value only once something sets it.
    """
    return tuple(
        _astuple_inner(_value(obj, field, "astuple"))
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
    Return a copy of a Magic instance with some of its values changed.

    The copy is built by calling the class again, so conversion,
    validation and the `__pre_init__` and `__post_init__` hooks all run,
    and a replaced value is checked exactly as an original one is. Every
    field that is not mentioned is carried over unchanged. `replace`
    also works on a frozen class, which is where it is most useful.

    Each change is named after an argument that the constructor takes.
    Any of a field's input aliases can be used, but giving the same
    field under two names is an error.

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
        so the copy receives whatever the class gives it, rather than
        the value that `obj` holds. An `InitVar` is passed to the
        constructor and not kept, so there is nothing to read back from
        `obj`. Such a field is either given again or left to its
        default.

    !!! warning "A `__post_init__` that derives a field runs again"
        The copy starts from the values as they are stored. A hook that
        derives one field from another therefore derives it a second
        time, from the value that it already derived, and `replace` with
        no changes at all can then return a different value:

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

    !!! warning "A converter runs again too"
        The same applies to conversion. The values passed back to the
        constructor have already been converted once, so a converter
        that does not return its own output unchanged changes the value
        each time:

        ```pycon
        >>> def double(value):
        ...     return value * 2
        ...
        >>> class Doubled(Magic):
        ...     x: ConvertTo[int, double] = 3
        ...
        >>> Doubled()
        Doubled(x=6)
        >>> replace(Doubled())
        Doubled(x=12)
        ```

        A converter that comes from a type hint is almost always safe
        here, because `int("7")` and `int(7)` are both `7`, so the
        question arises only for a converter written by hand.
        `dataclasses.replace` and `attrs.evolve` behave in the same way,
        for the same reason: the copy is a new construction, not a copy
        of the stored data.

        Where this matters, conversion can be turned off for the fields
        concerned, or the converter can be written so that running it
        twice gives the same result as running it once.

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
        If `obj` is not an instance of a Magic class, if a change names
        something that the constructor does not take, or if the class
        has an `InitVar` with no default and no value is given for it.
    """
    cls = type(obj)
    # Every field, pseudo-fields included: a change has to be turned
    # down by name whether or not the name belongs to a real field, and
    # a class that cannot tell two of its fields apart cannot say which
    # one a change was meant for.
    keyed = _keyed(_field_table(obj, "replace").values())
    given, arguments = {}, []
    aliases = {
        alias: field.public_name
        for field in keyed.values()
        for alias in field.aliases
    }
    for name, value in changes.items():
        preferred = aliases.get(name, name)
        if preferred in given:
            raise TypeError(
                f"{cls.__name__} got multiple values for argument "
                f"{preferred!r}"
            )
        given[preferred] = value
    for name, field in keyed.items():
        # A field the constructor does not take -- one that can be
        # passed neither by position nor by name, which is what `NoInit`
        # says -- has no way in.
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
        elif field.build:
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
    Return whether a class, or the class of an object, was built by Magic.

    The answer is the same for a class and for its instances. A class
    counts whichever way it was built, by inheriting from `Magic` or by
    decorating a plain class with `magic`.

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

    Parameters
    ----------
    obj : any
        A class, or any object at all.

    Returns
    -------
    is_magic : bool
        Whether the class, or the object's class, is a Magic class.
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
