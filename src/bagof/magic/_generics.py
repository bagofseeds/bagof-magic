"""
Filling in the type parameters a base class was written with.

A class written as ``class IntBox(Box[int])`` says that ``Box``'s type
variable ``T`` stands for ``int`` here. Python keeps the bases as they
were written in ``__orig_bases__``, so what each variable stands for can
be read back off, and a field ``Box`` declared as ``item: T`` becomes
``item: int`` on the subclass -- with a converter, a validator and a
default factory built from the type that was filled in.

The substitution itself is left to ``typing``. Every hint that mentions a
type variable lists it in ``__parameters__`` and can be subscripted to
fill it in, which is exactly what writing ``Box[int]`` does. Going
through that rather than taking a hint apart and putting it back
together keeps every shape working the same way: a nested hint
(``List[T]``, ``Dict[str, T]``), one carrying metadata
(``Annotated[T, Field(alias="why")]``, whose metadata is kept), a
callable signature (``Callable[[T], T]``), and a base that fills one
parameter of two (``Pair[int, S]``, which leaves ``S`` standing).

The same reading answers a second question, for a class that chooses
which subclass to build: given ``Box[int]``, which of the subclasses
registered with ``Box`` can stand for it, and what each of them becomes.
``base_arguments`` reads what a subclass filled ``Box``'s parameters in
with, and ``fill_in`` matches that against the ones asked for -- a
variable takes them, a type of its own has to be them.
"""

__all__ = ["base_arguments", "fill_in", "substitute", "type_arguments"]

import typing_extensions as tx


def type_arguments(namespace: dict) -> tx.Dict[type, tx.Dict[tx.Any, tx.Any]]:
    """
    What each base fills its type variables in with, keyed by that base.

    `namespace` is the class body being built. A base written without
    brackets, and one written with its own variables passed straight
    through (`Generic[T]`), fills nothing in and is left out.
    """
    arguments = {}
    for base in namespace.get("__orig_bases__", ()):
        origin = tx.get_origin(base)
        if origin is None:
            continue
        parameters = getattr(origin, "__parameters__", ())
        values = tx.get_args(base)
        if len(values) != len(parameters):
            # A base subscripted with the wrong number of arguments is
            # Python's to complain about, not this module's.
            continue
        filled = {
            parameter: value
            for parameter, value in zip(parameters, values)
            if value is not parameter
        }
        if filled:
            arguments[origin] = filled
    return arguments


def substitute(hint: tx.Any, arguments: tx.Dict[tx.Any, tx.Any]) -> tx.Any:
    """
    `hint` with the type variables named in `arguments` filled in.

    The hint is handed back unchanged, and not merely equal to itself,
    when it mentions none of them.
    """
    if isinstance(hint, tx.TypeVar):
        return arguments.get(hint, hint)
    parameters = getattr(hint, "__parameters__", ())
    if not parameters or tx.get_origin(hint) is None:
        # No variables to fill in -- or a generic class named on its own,
        # like a bare `Box`, which lists its parameters but stands for
        # `Box` with anything in it and is not this class's to narrow.
        return hint
    values = tuple(arguments.get(p, p) for p in parameters)
    if all(value is p for value, p in zip(values, parameters)):
        return hint
    return hint[values if len(values) > 1 else values[0]]


def base_arguments(cls: type, base: type) -> tx.Optional[tx.Tuple]:
    """
    What `cls` fills `base`'s type parameters in with, as it was written.

    A tuple as long as `base.__parameters__`: a concrete type where
    `cls` filled one in (`class Sub(Box[int])`), and a variable of
    `cls`'s own where it passed one through (`class Sub(Box[T])`).
    `None` when `cls` does not inherit from `base`.
    """
    if cls is base:
        return tuple(getattr(base, "__parameters__", ()))
    # From the class's own dict: `__orig_bases__` is an ordinary
    # attribute, so a class that fills nothing in would otherwise be
    # handed its parent's bases and read as having filled them in.
    written = cls.__dict__.get("__orig_bases__", cls.__bases__)
    for entry in written:
        origin = tx.get_origin(entry) or entry
        if not (isinstance(origin, type) and issubclass(origin, base)):
            continue
        upper = base_arguments(origin, base)
        if upper is None:
            continue
        parameters = getattr(origin, "__parameters__", ())
        values = tx.get_args(entry)
        filled = (
            dict(zip(parameters, values))
            if len(values) == len(parameters)
            else {}
        )
        return tuple(substitute(hint, filled) for hint in upper)
    return None


def fill_in(
    target: type, base: type, arguments: tx.Tuple
) -> tx.Optional[type]:
    """
    `target` with `base`'s type parameters standing for `arguments`.

    `None` when `target` cannot stand for them, because it fills one of
    them in with a type of its own that they contradict -- `class
    Sub(Box[str])` where `Box[int]` was asked for. A target with no
    parameters left to fill, or one whose own are not all named by the
    subscription, is handed back as it is.
    """
    written = base_arguments(target, base)
    if written is None or len(written) != len(arguments):
        return None
    stands_for = {}
    for hint, argument in zip(written, arguments):
        if not _matches(hint, argument, stands_for):
            return None
    parameters = getattr(target, "__parameters__", ())
    if not parameters:
        return target
    values = tuple(stands_for.get(p, p) for p in parameters)
    if any(value is p for value, p in zip(values, parameters)):
        # A variable of its own that the subscription says nothing
        # about: there is nothing to fill it in with.
        return target
    filled = target[values if len(values) > 1 else values[0]]
    # A class of its own written in the class body answers the
    # subscription, and may hand back anything at all. What it gave is
    # not something to build, so the target is used as it was written.
    return filled if isinstance(filled, type) else target


def _matches(hint: tx.Any, argument: tx.Any, stands_for: dict) -> bool:
    # Whether `hint`, as a base wrote one of its type arguments, can
    # stand for `argument` -- recording what each variable in it would
    # then stand for. A variable takes the argument; anything else has
    # to be that argument, or be built the same way out of parts that
    # each match.
    if isinstance(hint, tx.TypeVar):
        return stands_for.setdefault(hint, argument) == argument
    if isinstance(hint, list):
        # The argument list of a callable signature, which `get_args`
        # hands back as a list rather than as a typing form.
        return (
            isinstance(argument, list)
            and len(hint) == len(argument)
            and all(
                _matches(inner, given, stands_for)
                for inner, given in zip(hint, argument)
            )
        )
    if hint is tx.Any or argument is tx.Any:
        # `Box[Any]` is `Box` with anything in it, so it stands for
        # every filling-in and every filling-in stands for it.
        return True
    if not getattr(hint, "__parameters__", ()):
        return hint == argument
    origin = tx.get_origin(hint)
    if origin is None or origin is not tx.get_origin(argument):
        return False
    inner, given = tx.get_args(hint), tx.get_args(argument)
    return len(inner) == len(given) and all(
        _matches(one, other, stands_for) for one, other in zip(inner, given)
    )
