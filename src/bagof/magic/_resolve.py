"""
Adapters that resolve a type hint to a field converter / validator, using
the sibling ``bagof-converters`` and ``bagof-validators`` packages.

A [`Magic`][bagof.magic.Magic] field's ``converter`` and ``validator`` are
both called as ``value = f(value)``. A converter already returns the
converted value, but a validator only *raises* on failure and returns
``None`` -- so it is wrapped to return the value it was given.
"""

from __future__ import annotations

__all__ = ["make_converter", "make_validator"]

# dependencies
import typing_extensions as tx

# bags
from bagof.converters import Converter
from bagof.validators import Validator


def make_converter(hint: tx.Any) -> tx.Callable[[tx.Any], tx.Any]:
    """Return a callable that converts a value to ``hint``."""
    return Converter.get(hint)


def make_validator(hint: tx.Any) -> tx.Callable[[tx.Any], tx.Any]:
    """
    Return a callable that validates a value against ``hint`` and returns
    it unchanged (raising on failure).
    """
    validator = Validator.get(hint)

    def validate(value: tx.Any) -> tx.Any:
        validator(value)
        return value

    return validate
