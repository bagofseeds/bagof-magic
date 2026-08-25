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
"""

from __future__ import annotations

__all__ = ["substitute", "type_arguments"]

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
