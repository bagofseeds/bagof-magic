"""
Naming the class and the field when a converter, a validator or a
factory fails.

A converter, a validator and a factory each know what they were asked to
do, and nothing about where they were asked to do it: on its own, a
failure reads ``ToNumber(<class 'int'>): Invalid value.``, which does not
say which field of which class was being filled in. Every call to one of
them hands its failure to `field_error`, which raises the same error
again -- same class, so an ``except`` written for it still catches -- with
the class, the field and the offending value in front of the original
text, and the original as its cause.
"""

from __future__ import annotations

__all__ = ["field_error"]

# dependencies
import typing_extensions as tx

# internals
from ._constants import MISSING, MaybeMissing

# What was being done to the field, in the reader's terms. The key is
# what the call site was doing, not which of the three it called: a
# factory builds a value, a converter converts one, a validator turns
# one down.
_WHAT = {
    "build": "could not build a value",
    "convert": "could not convert {value!r}",
    "validate": "{value!r} is not a valid value",
}


def field_error(
    owner: str,
    name: str,
    action: str,
    error: Exception,
    value: MaybeMissing[tx.Any] = MISSING,
) -> tx.NoReturn:
    """
    Raise `error` again, saying which field of which class it is about.

    Parameters
    ----------
    owner : str
        Name of the class the field belongs to.
    name : str
        Name of the field.
    action : str
        What was being done: "build", "convert" or "validate".
    error : Exception
        What was raised while doing it.
    value : Any, optional
        The value that was being converted or validated. A factory is
        given no value, and names none.
    """
    what = _WHAT[action].format(value=value)
    message = f"{owner}.{name}: {what} -- {error}"
    again = _rebuilt(error, message)
    if again is None:
        # Nothing can be said about where this one comes from without
        # changing what it is, and its class is what a caller catches.
        raise error
    raise again from error


def _rebuilt(error: Exception, message: str) -> tx.Optional[Exception]:
    """The same error, of the same class, saying `message` instead."""
    try:
        again = type(error)(message)
    except Exception:
        # An exception class whose constructor asks for more than a
        # message cannot be built from one.
        return None
    # Whatever the original was carrying comes across, so that code
    # reading an attribute off the error it caught still finds it.
    again.__dict__.update(error.__dict__)
    if hasattr(again, "message"):
        # A `bagof` error keeps its own plain text under `message` and
        # decorates it for display; the plain text is now the fuller one.
        again.message = message
    return again
