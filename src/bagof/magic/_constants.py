"""
Sentinels and attribute names used across the package.

`MISSING`, `_HasFactory`, `_FIELDS` and `_POST_INIT_NAME` are adapted from
Python's standard library `dataclasses` module.
Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved.
Licensed under the Python Software Foundation License Version 2; see
LICENSE-PSF-2.0.txt for its text and NOTICE.md for the list of derived
components and the summary of changes.
"""

from __future__ import annotations

import typing_extensions as tx

T = tx.TypeVar("T")

# The name of an attribute on the class where we store the StructField
# objects.  Also used to check if a class is a @magic.
_FIELDS = '__magic_fields__'

# The name of an attribute on the class that stores the parameters to
# @magic.
_OPTIONS = '__magic_options__'

# The name of an attribute on the class that stores where a type the
# class was annotated with by name is looked up when it is first needed.
_HINTS = '__magic_hints__'

# The name of a method that is called before the __init__ method,
# if it exists.
# It returns (args, kwargs).
_PRE_INIT_NAME = "__pre_init__"

# The name of a method that is called after the __init__ method,
# if it exists.
_POST_INIT_NAME = "__post_init__"

# The name of an attribute on the class that stores which of its
# subclasses it builds, for which arguments (see `_polymorph.py`). Only
# a class that has some is given one, so a class that has none costs one
# failed dict lookup per instantiation.
_POLYMORPHS = '__magic_polymorphs__'

# The name of an attribute on the class that stores the registration the
# class statement asked for -- the class it registers with, what it
# stands for, and how strong a claim that is.
_REGISTRATION = '__magic_registration__'

# The name of an attribute on the class that stores which of its fields
# were given a default because the class registered for one exact value
# of them. Inherited: a field pinned by a base is still pinned further
# down, and `__init__` has to be built the same way there.
_PINNED = '__magic_pinned__'

# Name we give to classes that are only created temporarily to build the
# MRO and then discarded.
_DISCARD = "__magic_discard__"

# Name we give to the `self` variable, in cases where a field named `self`
# already exists.
_SELF = "__magic_self__"

# Name under which a generated method is *always* available, whatever the
# option says, so a hand-written method can delegate to it:
#     def __init__(self, raw): self.__magic_init__(int(raw))
def _MAGIC(x: str) -> str: return f"__magic_{x}__"

# Attribute set on every method this package generates, so that turning an
# option off can tell one of ours from a hand-written one.
_GENERATED = "__magic_generated__"

# Name given to the local type variable when generating __init__
def _TYPE(x: str) -> str: return f"__magic_{x}_type__"

# Name given to the local default variable when generating __init__
def _DEFAULT(x: str) -> str: return f"__magic_{x}_default__"

# Name given to the local converter variable when generating __init__
def _CONVERTER(x: str) -> str: return f"__magic_{x}_converter__"

# Name given to the local validator variable when generating __init__
def _VALIDATOR(x: str) -> str: return f"__magic_{x}_validator__"

# Name given to the local holding the Arguments class when generating
# __init__, for the object handed to the init hooks
_ARGUMENTS = "__magic_arguments__"

# Names given, when generating __init__, to the local holding the helper
# that names the class and the field when a converter, a validator or a
# factory raises, and to the exception it is handed
_FIELD_ERROR = "__magic_field_error__"
_ERROR = "__magic_error__"

# Name given, when generating __init__, to the local holding the sentinel
# that stands for "this argument was not passed". It fills in for a
# parameter that has no default and follows one that does -- which
# Python's own syntax cannot spell -- and the body turns it back into
# the usual "missing a required argument".
_REQUIRED_ARG = "__magic_required__"

# Name given to the local holding the value of a field that is not a
# parameter, while it is being built, converted and validated
def _VALUE(x: str) -> str: return f"__magic_{x}_value__"

# Names given, when generating __init__, to the locals holding the
# builtins and the factory marker its body is written in terms of. The
# generated function's parameters are named after the fields, so a field
# called `object` or `isinstance` would shadow the builtin of that name
# for the whole body; carrying each under a namespaced name keeps it
# reachable whatever the fields are called.
_OBJECT = "__magic_object__"
_ISINSTANCE = "__magic_isinstance__"
_EXCEPTION = "__magic_exception__"
_HAS_FACTORY = "__magic_has_factory__"

# Name given to a method's return type variable when generating it
def _RETURN_TYPE(x: str) -> str: return f"__magic_{x}_return_type__"


class _MissingType:

    def __new__(cls) -> tx.Self:
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<MISSING>"

    def __bool__(self) -> bool:
        return False


MISSING = _MissingType()
MaybeMissing = tx.Union[T, _MissingType]


class _RequiredType:

    def __new__(cls) -> tx.Self:
        if not hasattr(cls, "_instance"):
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "<REQUIRED>"

    def __bool__(self) -> bool:
        return True


REQUIRED = _RequiredType()


class _HasFactory:

    def __init__(self, factory: callable) -> None:
        self.factory = factory

    def __repr__(self) -> str:
        return '<factory>'

    def __call__(self) -> tx.Any:
        return self.factory()


class SHOW_ATTR:

    def __init__(
        self,
        key: tx.Optional[str] = None,
        hide_if_none: bool = False
    ) -> None:
        self.key = key
        self.hide_if_none = hide_if_none

    def __call__(self, value: tx.Any) -> bool:
        if self.key is False:
            return False
        if self.hide_if_none and value is None:
            return False
        return True

    def __bool__(self) -> bool:
        return self.key is not False

    def __str__(self) -> str:
        return str(self.key)

    def __repr__(self) -> str:
        if self.key is False:
            return "False"
        if self.key is True and self.hide_if_none:
            return "<if not None>"
        if self.hide_if_none:
             return f"{self.key!r} <if not None>"
        return f"{self.key!r}"


class HIDE_IF_NONE(SHOW_ATTR):
    """
    Sentinel for `Field.repr` / `Field.key`: include the field in the
    generated `__repr__` / dict-like interface only when its value is not
    `None` at runtime, instead of unconditionally.

    ```python
    class C(Magic):
        x: Annotated[Optional[int], Field(repr=HIDE_IF_NONE)]

    repr(C(None))  # "C()"
    repr(C(5))     # "C(x=5)"
    ```
    """

    def __init__(self, key: tx.Optional[str] = None) -> None:
        super().__init__(key=key, hide_if_none=True)
