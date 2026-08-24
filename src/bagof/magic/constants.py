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

# The name of a method that is called before the __init__ method,
# if it exists.
# It returns (args, kwargs).
_PRE_INIT_NAME = "__pre_init__"

# The name of a method that is called after the __init__ method,
# if it exists.
_POST_INIT_NAME = "__post_init__"

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

# The name of an attribute holding the class-body values the builder
# consumed -- a `Field()` written as a default value is replaced by the
# real default, or removed. Kept so that a rebuild can put the class
# body back the way the user wrote it.
_DECLARED = "__magic_declared__"

# Name given to the local type variable when generating __init__
def _TYPE(x: str) -> str: return f"__magic_{x}_type__"

# Name given to the local default variable when generating __init__
def _DEFAULT(x: str) -> str: return f"__magic_{x}_default__"

# Name given to the local converter variable when generating __init__
def _CONVERTER(x: str) -> str: return f"__magic_{x}_converter__"

# Name given to the local validator variable when generating __init__
def _VALIDATOR(x: str) -> str: return f"__magic_{x}_validator__"

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
