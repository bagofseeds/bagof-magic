"""What a type checker is told the annotation family is.

At run time `Frozen[int]` is `Annotated[int, Frozen()]`, made by the
class's `__class_getitem__`. A type checker never runs that: it reads
`Frozen` as a class that takes no type arguments, and reports the
annotation instead of reading it as `int`.

So, for a checker only, each marker that is written in the brackets of
an annotation is rebound here to a generic alias, `Annotated[T, ...]`,
which a checker reads as the type in the brackets. `ClassVar` and
`InitVar` are rebound to the standard library's own, so that a checker
also leaves a class variable out of the constructor and keeps an init
variable in it, as the class does.

A name cannot be a type alias and a class at once, and calling an alias
is an error to a checker. The markers whose call is the usual spelling
-- `Inherit("x")` as a field's value, `repr=HideIfNone()`, `Key(...)` --
and the ones that are never complete without a value (`Default`, `Doc`,
`ShowIf`, `HideIf`) therefore stay classes. `Forget` is written bare,
which a class already is.

Nothing in the `TYPE_CHECKING` branch runs: at run time this module
hands on exactly what `_fields` defines.
"""
import typing_extensions as tx

__all__ = [
    "Alias",
    "Property",
    "ReadOnlyProperty",
    "Field",
    "field",
    "Default",
    "Factory",
    "ConvertTo",
    "Validate",
    "Init",
    "NoInit",
    "Kw",
    "NotKw",
    "KwOnly",
    "NotKwOnly",
    "Positional",
    "NotPositional",
    "PositionalOnly",
    "NotPositionalOnly",
    "Frozen",
    "NotFrozen",
    "Var",
    "InitVar",
    "ClassVar",
    "Repr",
    "NoRepr",
    "ShowIf",
    "HideIf",
    "HideIfNone",
    "HideIfDefault",
    "Compare",
    "NoCompare",
    "Eq",
    "NoEq",
    "Order",
    "NoOrder",
    "Hash",
    "NoHash",
    "Key",
    "NotKey",
    "Doc",
    "Pin",
    "Narrow",
    "NoPin",
    "Forget",
    "Inherit",
    "REQUIRED",
    "PIN",
    "CLASSVAR",
    "KEEP",
    "NARROW",
    "PIN_NARROW",
    "CLASSVAR_NARROW",
    "KEEP_NARROW",
]

if tx.TYPE_CHECKING:
    from dataclasses import InitVar

    from typing_extensions import ClassVar

    from . import _fields
    from ._fields import (
        CLASSVAR,
        CLASSVAR_NARROW,
        KEEP,
        KEEP_NARROW,
        NARROW,
        PIN,
        PIN_NARROW,
        REQUIRED,
        Default,
        Doc,
        Field,
        Forget,
        HideIf,
        HideIfDefault,
        HideIfNone,
        Inherit,
        Key,
        ShowIf,
        field,
    )

    T = tx.TypeVar("T")

    Alias = tx.Annotated[T, _fields.Alias]
    Property = tx.Annotated[T, _fields.Property]
    ReadOnlyProperty = tx.Annotated[T, _fields.ReadOnlyProperty]
    Factory = tx.Annotated[T, _fields.Factory]
    ConvertTo = tx.Annotated[T, _fields.ConvertTo]
    Validate = tx.Annotated[T, _fields.Validate]
    Init = tx.Annotated[T, _fields.Init]
    NoInit = tx.Annotated[T, _fields.NoInit]
    Kw = tx.Annotated[T, _fields.Kw]
    NotKw = tx.Annotated[T, _fields.NotKw]
    KwOnly = tx.Annotated[T, _fields.KwOnly]
    NotKwOnly = tx.Annotated[T, _fields.NotKwOnly]
    Positional = tx.Annotated[T, _fields.Positional]
    NotPositional = tx.Annotated[T, _fields.NotPositional]
    PositionalOnly = tx.Annotated[T, _fields.PositionalOnly]
    NotPositionalOnly = tx.Annotated[T, _fields.NotPositionalOnly]
    Frozen = tx.Annotated[T, _fields.Frozen]
    NotFrozen = tx.Annotated[T, _fields.NotFrozen]
    Var = tx.Annotated[T, _fields.Var]
    Repr = tx.Annotated[T, _fields.Repr]
    NoRepr = tx.Annotated[T, _fields.NoRepr]
    Compare = tx.Annotated[T, _fields.Compare]
    NoCompare = tx.Annotated[T, _fields.NoCompare]
    Eq = tx.Annotated[T, _fields.Eq]
    NoEq = tx.Annotated[T, _fields.NoEq]
    Order = tx.Annotated[T, _fields.Order]
    NoOrder = tx.Annotated[T, _fields.NoOrder]
    Hash = tx.Annotated[T, _fields.Hash]
    NoHash = tx.Annotated[T, _fields.NoHash]
    NotKey = tx.Annotated[T, _fields.NotKey]
    Pin = tx.Annotated[T, _fields.Pin]
    Narrow = tx.Annotated[T, _fields.Narrow]
    NoPin = tx.Annotated[T, _fields.NoPin]
else:
    from ._fields import *  # noqa: F401, F403
