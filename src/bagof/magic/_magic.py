# TODO:
# - Refactor/Simplify validators.
#   (many have identical semantics and could share a base class)
# - Implement from_dict, to_dict, etc.
# - Generate more efficient bytecode by evaluating magic methods at
#   class creation time, rather than looping through fields at run-time.
#   This is already done for __init__, but not for the other ones.
"""
A `Magic` acts like a python `dataclass`, except that it operates
via inheritance, rather than via a decorator (although the @magic
decorator can be used if preferred).

The options typically specified in the @dataclass decorator are instead
specified as class keyword arguments, and are inherited (or overloaded)
by subclasses.

```python
class Point(Magic, frozen=True):
    x: float
    y: float

# --- or ---

@magic(frozen=True)
class Point:
    x: float
    y: float
```

Most options supported by dataclasses are supported, but there are
some differences. Additional options are also implemented:

Parameters
----------
init : bool | str, default=True
    Generate `__init__` method
repr : bool | str, default=True
    Generate `__repr__` method; a field holding no value is left out
eq : bool | str, default=True
    Generate `__eq__` method; two objects are equal when the same
    fields are holding values and those values match
order : bool | str, default=False
    Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods; a field
    holding no value stops the comparison
hash : bool | str, default=None
    Generate `__hash__` method; if `None`, decide automatically
unsafe_hash : bool, default=False
    Always generate `__hash__` method
frozen : bool, default=False
    Disable `__setattr__` and `__delattr__`
match_args : bool | str, default=False
    Generate `__match_args__` for pattern matching
kw_only : bool, default=False
    Make all fields keyword-only by default
positional_only : bool, default=False
    Make all fields positional-only by default
slots : bool, default=False
    Generate `__slots__` and remove `__dict__`
weakref_slot : bool, default=False
    Generate a weakref slot in `__slots__`
factory : bool, default=False
    Use field type as factory if none is provided
mutable_default : str, default="factory"
    What to do with a mutable default such as `x: list = []`
convert : bool, default=False
    Use field type as converter if none is provided
validate : bool, default=False
    Use field type as validator if none is provided
unresolved_hints : str, default="warn"
    What to do when a type hint still names something undefined the
    first time a field needs it: "warn", "raise" or "ignore"
mapping : bool, default=False
    Implement the `Mapping` protocol; a subclass cannot turn it off.
    Only a field that is holding a value is a key
override : bool | str | list, default=False
    Decide the settings of an inherited field again from this class;
    a name, or a list of names, decides only those
polymorphic : bool | str, default=False
    Build one of this class's subclasses instead of this class,
    chosen from the arguments it was given. A subclass says which
    arguments it stands for with `on=` on its own class statement.
    With "strict", a call matching none of them is refused rather
    than building this class.
pin_discriminant : {"pin", "classvar", "keep"}, default="pin"
    What a subclass does with a field it matches on exactly. "pin"
    gives the field that value as its default, so it still shows in
    the repr and survives a round trip; "classvar" makes it a class
    attribute that is not stored per instance, still accepted by the
    constructor and discarded; "keep" leaves the field alone.
reverse : bool, default=False
    Use the reverse MRO order to determine field order
doc : bool | str, default=True
    Add field documentation to class docstring

Examples
--------
It also differs from a standard dataclass in that field-specific options
are assigned via annotations, rather than via a `field` function:

```python
# - Default factories
#   instead of x: list = field(factory=list)
x: Factory[list, list_factory]
x: Annotated[list, Factory(list_factory)]

#   if no factory is provided, it will use the type as the default factory
x: Factory[list] -> x: Annotated[list, Factory(list)]

# - Include in the init method
#   instead of x: int = field(init=True)
x: Init[int]
x: Annotated[int, Init()]
x: Annotated[int, Init(True)]
x: NoInit[int]
x: Annotated[int, NoInit()]
x: Annotated[int, Init(False)]

# - Keyword-only arguments
#   instead of x: int = field(kw_only=True)
x: KwOnly[int]
x: Annotated[int, KwOnly()]
x: Annotated[int, KwOnly(True)]
x: NotKwOnly[int]
x: Annotated[int, NotKwOnly()]
x: Annotated[int, KwOnly(False)]
```

It supports additional features such as automatic conversion of field
values via annotations:

```python
x: ConvertTo[int, partial(int, base=16)]
x: Annotated[int, ConvertTo(partial(int, base=16))]

# if no converter is provided, it will use the type as the default converter
x: ConvertTo[int] -> x: Annotated[int, ConvertTo(int)]
```

Frozen or unfrozen fields:

```python
x: Frozen[int]
x: Annotated[int, Frozen()]
x: Annotated[int, Frozen(True)]
x: NotFrozen[int]
x: Annotated[int, NotFrozen()]
x: Annotated[int, Frozen(False)]
```
"""
from __future__ import annotations

__all__ = ["Magic", "magic", "HIDE_IF_NONE"]
# stdlib
import ast
import builtins
import copy
import operator
import sys
import warnings
from abc import ABCMeta
from collections import abc as _abc
from functools import partial
from inspect import Parameter, Signature, signature
from textwrap import dedent, indent
from types import MemberDescriptorType

# externals
import typing_extensions as tx
from bagof.core.magic import UnionType as _UnionType

# internals
from ._arguments import *  # noqa: F401, F403
from ._arguments import Arguments
from ._arguments import __all__ as __all_arguments__
from ._constants import (
    _ARGUMENTS,
    _CONVERTER,
    _DEFAULT,
    _DISCARD,
    _ERROR,
    _EXCEPTION,
    _FIELD_ERROR,
    _FIELDS,
    _GENERATED,
    _HAS_FACTORY,
    _HINTS,
    _ISINSTANCE,
    _MAGIC,
    _OBJECT,
    _OPTIONS,
    _PINNED,
    _POLYMORPHS,
    _POST_INIT_NAME,
    _PRE_INIT_NAME,
    _REGISTRATION,
    _REQUIRED_ARG,
    _RETURN_TYPE,
    _SELF,
    _TYPE,
    _VALIDATOR,
    _VALUE,
    HIDE_IF_NONE,
    MISSING,
    REQUIRED,
    SHOW_ATTR,
    _HasFactory,
)
from ._errors import field_error
from ._fields import *  # noqa: F401, F403
from ._fields import _OVERRIDABLE, Field, _stored
from ._fields import __all__ as __all_fields__
from ._generics import substitute as _substitute
from ._generics import type_arguments as _type_arguments
from ._options import *  # noqa: F401, F403
from ._options import Options
from ._options import __all__ as __all_options__
from ._polymorph import *  # noqa: F401, F403
from ._polymorph import __all__ as __all_polymorph__
from ._polymorph import check as _check_invariant
from ._polymorph import invariant as _keep_invariant
from ._polymorph import register as _register_polymorph
from ._polymorph import select as _select_polymorph
from ._polymorph import specifications as _specifications
from ._resolve import POLICIES as _HINT_POLICIES
from ._resolve import Hints
from ._utils import _get_origin, rebuild_cls

__all__ += __all_arguments__
__all__ += __all_fields__
__all__ += __all_options__
__all__ += __all_polymorph__


# ----------------------------------------------------------------------
# Builder
# ----------------------------------------------------------------------
# Adapted from Python's standard library `dataclasses` module.
# Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved.
# Licensed under the Python Software Foundation License Version 2; see
# LICENSE-PSF-2.0.txt for its text and NOTICE.md for the list of derived
# components and the summary of changes.

def __post_new__(cls: type) -> type:
    # These methods have to be assigned post-new, because they
    # use super and therefore need to reference the class.

    # A class that names itself in an annotation -- `parent: Node` in
    # `class Node` -- cannot be looked up by name until now, and a class
    # written inside a function is never in its module at all. Put it
    # where its own fields will look for it.
    hints = cls.__dict__.get(_HINTS)
    if hints is not None:
        hints.namespace[cls.__name__] = cls

    # The class exists now, so it can be registered with the one that
    # will build it. Under "strict" it also keeps its own registration,
    # to refuse a direct call that contradicts it.
    registration = cls.__dict__.get(_REGISTRATION)
    if registration is not None:
        polymorphic_base, specs, priority = registration
        strict = getattr(polymorphic_base, _OPTIONS).polymorphic == "strict"
        _register_polymorph(polymorphic_base, cls, specs, priority, strict)
        if getattr(cls, _OPTIONS).polymorphic == "strict":
            _keep_invariant(cls, specs)

    fields = getattr(cls, _FIELDS, {})
    fields = {name: field for name, field in fields.items() if not field.var}
    __delattr__, __setattr__ = _make_assign(cls)
    if "__setattr__" not in cls.__dict__:
        cls.__setattr__ = __setattr__
    if "__delattr__" not in cls.__dict__:
        cls.__delattr__ = __delattr__

    return cls


#: The attributes a field can take from the field it replaces, and the
#: values that mean "this field did not say".
#:
#: What counts as "did not say" is per attribute, and has to be, because
#: None is a real answer for some of them. A resolved field has
#: `doc = None` when no documentation was given, so for `doc` both None
#: and MISSING mean unset -- but `hash = None` means "follow whatever
#: `eq` says", which is an answer, and would be wrong to overwrite.
#: Anything added here needs its own decision.
_INHERITABLE = {
    "doc": (MISSING, None),
}


def _inherit_attrs(
    field: Field,
    other: Field,
    attrs: tx.Sequence[str],
) -> None:
    # Copy into `field`, from `other`, the attributes `field` leaves
    # unset -- see `_INHERITABLE` for what unset means for each.
    for attr in attrs:
        value = getattr(field, attr, MISSING)
        # Compared by identity: `==` on an arbitrary field value can do
        # anything, including returning something that is not a bool.
        if not any(value is unset for unset in _INHERITABLE[attr]):
            continue
        inherited = getattr(other, attr, MISSING)
        if inherited is not MISSING:
            setattr(field, attr, inherited)


def _fill_in_type(
    field: Field,
    arguments: tx.Dict[tx.Any, tx.Any],
    hints: Hints,
) -> None:
    # Replace the type variables in a field's type with what the class
    # being built says they stand for, and work out again whatever was
    # worked out from that type. A converter, validator or factory the
    # field was given rather than asked for is left alone: filling in a
    # type variable says nothing about it.
    #
    # The field is one this class owns -- `_add_fields` copies on the way
    # in -- so it is changed in place.
    filled = _substitute(field.type, arguments)
    if filled is field.type:
        return
    field.type = filled
    field._rebuild(hints)

def _override_attrs(override: tx.Any, clsname: str) -> tx.Tuple[str, ...]:
    # The field attributes an inherited field works out again from this
    # class's settings.
    #
    # `override` names settings; a field stores their answers under
    # names of its own, so `_OVERRIDABLE` maps between the two.
    if override is True:
        names = tuple(_OVERRIDABLE)
    elif not override:
        return ()
    elif isinstance(override, str):
        names = (override,)
    elif isinstance(override, tx.Iterable):
        names = tuple(override)
    else:
        raise ValueError(
            f"{clsname} passes override={override!r}, which is neither a "
            f"setting name nor a list of them. Pass override=True for "
            f"every setting a subclass can decide again, the name of one "
            f"of them, or a list of names."
        )

    attrs = []
    for name in names:
        if name not in _OVERRIDABLE:
            raise ValueError(
                f"{clsname} asks to override {name!r}, which is not one of "
                f"the settings a field takes from its class: "
                f"{', '.join(sorted(_OVERRIDABLE))}. Those are the ones "
                f"decided per field; the rest are about the class as a "
                f"whole, and a subclass already decides them for itself."
            )
        for attr in _OVERRIDABLE[name]:
            if attr not in attrs:
                attrs.append(attr)
    return tuple(attrs)


def _wrap_show_attrs(field: Field) -> None:
    # `repr` and `key` each answer two questions -- whether the field
    # takes part, and under which name -- so once resolved they are held
    # as a `SHOW_ATTR` rather than as a plain value.
    # (This is hacky and ugly -- should be reworked)
    if field.key is HIDE_IF_NONE:
        field.key = HIDE_IF_NONE(field.public_name)
    if not isinstance(field.key, SHOW_ATTR):
        field.key = SHOW_ATTR(field.key)

    if field.repr is HIDE_IF_NONE:
        if field.var:
            field.repr = SHOW_ATTR(False)
        else:
            field.repr = HIDE_IF_NONE(field.public_name)
    if not isinstance(field.repr, SHOW_ATTR):
        field.repr = SHOW_ATTR(field.repr)

def _add_fields(
    fields: dict[str, Field],
    new_fields: tx.Iterable[Field],
    replace: bool = False,
    reverse: bool = False,
    inherit: tx.Sequence[str] = tuple(_INHERITABLE),
) -> None:
    # Add fields to an existing dict of fields.
    #
    # This is used when constructing the dictionary of inherited fields.
    # * replace :
    #   If True, then new fields will replace existing fields.
    #   If False, then existing fields will be preserved.
    # * reverse :
    #   If True, then new fields will be added before existing fields.
    #   If False, then new fields will be added after existing fields.
    #   In both case, the order of `new_fields` is preserved.
    # * inherit :
    #   Names of the attributes that the field being dropped passes on to
    #   the field being kept, when both declare a field of the same name
    #   and the kept one leaves them unset.
    #
    # New fields are copied on the way in: a field is mutated in place
    # while its class is built, so a class must never hold a field that
    # another class holds too.
    if replace and not reverse:
        for new_field in new_fields:
            field = new_field.copy()
            old_field = fields.get(field.name, None)
            if old_field is not None:
                _inherit_attrs(field, old_field, inherit)
            fields[field.name] = field

    elif replace and reverse:
        old_fields = dict(fields)
        fields.clear()
        for new_field in new_fields:
            field = new_field.copy()
            old_field = old_fields.get(field.name, None)
            if old_field is not None:
                _inherit_attrs(field, old_field, inherit)
            fields[field.name] = field
        for name, old_field in old_fields.items():
            fields.setdefault(name, old_field)

    elif not replace and not reverse:
        for new_field in new_fields:
            old_field = fields.get(new_field.name, None)
            if old_field is None:
                fields[new_field.name] = new_field.copy()
            else:
                _inherit_attrs(old_field, new_field, inherit)

    else:  # not replace and reverse
        old_fields = dict(fields)
        fields.clear()
        for new_field in new_fields:
            old_field = old_fields.get(new_field.name, None)
            if old_field is None:
                fields[new_field.name] = new_field.copy()
            else:
                _inherit_attrs(old_field, new_field, inherit)
                fields[new_field.name] = old_field
        for name, old_field in old_fields.items():
            fields.setdefault(name, old_field)


def _check_public_names(clsname: str, fields: dict[str, Field]) -> None:
    # Two fields cannot answer to one outside name.
    #
    # A field is known outside the class by its alias, or by its own name
    # with any leading underscore removed. That one name is the
    # constructor parameter, the key `repr()` shows, the key of the
    # dict-like view, and the key `fields_dict`, `asdict` and `replace`
    # speak -- so when two fields share it, only one of them is ever
    # reachable and the other is silently unreachable under it. The class
    # is refused here, whether or not the pair would meet in a signature,
    # so that every accessor can key by that name and trust it.
    seen = {}
    for name, field in fields.items():
        public = field.public_name
        if public in seen:
            raise TypeError(
                f"{clsname} has two fields, {seen[public]!r} and {name!r}, "
                f"and both are known as {public!r} outside the class: that "
                f"is the name the constructor takes and repr() shows. A "
                f"field is known by its alias, or by its own name with any "
                f"leading underscore removed. Rename one of the two fields, "
                f"or give one of them an alias of its own."
            )
        seen[public] = name


def _check_public_keys(clsname: str, fields: dict[str, Field]) -> None:
    # Two fields cannot answer to one key of the dict-like view.
    #
    # A field's key is the one `Key("...")` gives it, or its public
    # name. The view has room for only one field under a key, so when
    # two share one, the second silently wins the key and the first is
    # unreachable through the view -- and `len()` counts one field
    # fewer than the class has.
    #
    # The class is refused whether or not it is dict-like. A key is a
    # property of the field, so it is inherited, and `mapping` can be
    # turned on further down the chain: a pair of keys written on a
    # class with no view is a collision waiting for the first subclass
    # that asks for one, and refusing it there would name two fields
    # the reader did not write there.
    #
    # A pseudo-field is left out: it is not stored on the instance, so
    # it is never part of the view and has no key to clash with. A
    # `ClassVar` named after another field's key is a class whose view
    # is perfectly well-formed.
    seen = {}
    for name, field in fields.items():
        if field.var:
            continue
        key = field.public_key
        if key is None:
            continue
        if key in seen:
            raise TypeError(
                f"{clsname} has two fields, {seen[key]!r} and {name!r}, "
                f"and both take {key!r} as their key: only one of them "
                f"can be reached under {key!r} in the dict-like view, and "
                f"len() would count one field fewer than the class has. A "
                f"field's key is the one Key() gives it, or its public "
                f"name -- and a key stays with the field, so a subclass "
                f"built with mapping=True inherits both. Give one of the "
                f"two a key of its own, or leave it out of the view with "
                f"NotKey."
            )
        seen[key] = name


#: Names that mark the *structure* of an annotation: the family declared
#: in `_fields.py` (`KwOnly`, `Frozen`, `ClassVar`, ...) plus the typing
#: spellings the builder reads. Used to recognise a structural marker by
#: name when the name itself is not defined at runtime.
_STRUCTURAL_NAMES = frozenset(__all_fields__) | {"Annotated", "ClassVar"}

#: The expression nodes a *type* may be made of. A type is a name, an
#: attribute of one, a subscript, a union, a literal, or a tuple of
#: those -- never a call, so reading an annotation back never runs it.
_TYPE_NODES = tuple(
    node
    for node in (
        ast.Name, ast.Attribute, ast.Subscript, ast.Tuple, ast.List,
        ast.Constant, ast.BinOp, ast.BitOr, ast.UnaryOp, ast.USub,
        ast.Load, ast.Slice,
        # `Index` wrapped every subscript before Python 3.9 and is gone
        # again from 3.14, so it is asked for rather than named. A
        # literal `...` needs nothing of its own: it has parsed as a
        # `Constant` since 3.8.
        getattr(ast, "Index", None),
    )
    if node is not None
)

#: What may be added to those in a metadata slot -- `Annotated[int,
#: Field(alias="n")]` and the extra arguments of the family's own
#: spellings, `Doc[int, "..."]`. A call is allowed there, and only
#: there, and only to a member of the annotation family.
_METADATA_NODES = _TYPE_NODES + (
    ast.Call, ast.keyword, ast.Dict, ast.Set, ast.Starred, ast.Lambda,
)


class _UnreadableAnnotation(UserWarning):
    """An annotation whose structure the builder could not read back."""


def _caller_stacklevel() -> int:
    # How far up the stack the class statement is, so a warning about an
    # annotation is reported against the line that wrote it rather than
    # against the builder.
    frame = sys._getframe(1)
    level = 1
    while frame is not None and frame.f_globals.get("__name__") == __name__:
        frame = frame.f_back
        level += 1
    return level


def _dotted_name(node: ast.AST) -> tx.Optional[tx.List[str]]:
    # ["registry", "Port"] for `registry.Port`, None for anything that
    # is not a plain (possibly dotted) name.
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    parts.append(node.id)
    parts.reverse()
    return parts


def _lookup_dotted(parts: tx.List[str], globals: dict) -> tx.Any:
    # The object a dotted name refers to in the defining module, or
    # MISSING when any step of it is not defined there. Only names are
    # looked up this way, so nothing is ever called.
    name = parts[0]
    if name in globals:
        value = globals[name]
    elif hasattr(builtins, name):
        value = getattr(builtins, name)
    else:
        return MISSING
    for attr in parts[1:]:
        try:
            value = getattr(value, attr)
        except AttributeError:
            return MISSING
    return value


def _is_structural(value: tx.Any) -> bool:
    # Does this marker decide how a field is built, rather than what it
    # holds? `ClassVar[...]`, `Annotated[...]`, and every member of the
    # family in `_fields.py` do.
    if value is tx.ClassVar or value is tx.Annotated:
        return True
    return isinstance(value, type) and issubclass(value, Field)


def _subscript_args(node: ast.Subscript) -> tx.List[ast.AST]:
    # What is written between the brackets, one node per argument.
    inner = node.slice
    index = getattr(ast, "Index", None)
    if index is not None and isinstance(inner, index):
        # Python 3.8 wraps a subscript in an `Index` node.
        inner = inner.value  # pragma: no cover
    if isinstance(inner, ast.Tuple):
        return list(inner.elts)
    return [inner]


def _is_type_expression(node: ast.AST) -> bool:
    return all(isinstance(child, _TYPE_NODES) for child in ast.walk(node))


def _is_metadata_expression(node: ast.AST, globals: dict) -> bool:
    # A lambda is a value, not a call, so its body is never run here and
    # is not inspected. Everything else must be made of metadata nodes,
    # and a call in it must be to a member of the annotation family.
    if isinstance(node, ast.Lambda):
        return True
    if not isinstance(node, _METADATA_NODES):
        return False
    if isinstance(node, ast.Call):
        called = _dotted_name(node.func)
        value = MISSING if called is None else _lookup_dotted(called, globals)
        if not (isinstance(value, type) and issubclass(value, Field)):
            return False
    return all(
        _is_metadata_expression(child, globals)
        for child in ast.iter_child_nodes(node)
    )


def _evaluate(source: str, globals: dict) -> tx.Any:
    # Evaluate text that has already been checked for what it is allowed
    # to contain. A name that is not defined -- a type imported under
    # `if TYPE_CHECKING:`, a spelling the running Python is too old for
    # -- gives MISSING, and the caller keeps the text instead.
    try:
        return eval(source, globals)
    except Exception:
        return MISSING


def _segment(source: str, node: ast.AST) -> str:
    # The text a node was written as. `get_source_segment` answers None
    # for a node without a position, which the parser does not produce.
    return ast.get_source_segment(source, node) or source


def _read_type(node: ast.AST, source: str, globals: dict) -> tx.Any:
    # The type a node describes, or the text it was written as when the
    # names in it are not available (or the spelling needs a newer
    # Python than the one running).
    text = _segment(source, node)
    if not _is_type_expression(node):
        return text
    value = _evaluate(text, globals)
    return text if value is MISSING else value


def _read_annotation(
    node: ast.AST, source: str, globals: dict, where: str
) -> tx.Any:
    # Read one annotation back from its text. The structure -- the
    # marker a field is built by -- is recovered first and on its own,
    # so a type that cannot be resolved never costs the field its
    # `ClassVar`, `KwOnly` or `Frozen`.
    marker = _structural_marker(node, globals, where)
    if marker is MISSING:
        return _read_type(node, source, globals)
    payload, *metadata = _subscript_args(node)
    type = _read_annotation(payload, source, globals, where)
    if isinstance(type, str):
        # The type is not available yet: carry it by name, the way a
        # quoted annotation is carried.
        type = tx.ForwardRef(type)
    values = []
    for meta in metadata:
        if not _is_metadata_expression(meta, globals):
            return _decline(node, source, where, _segment(source, meta))
        value = _evaluate(_segment(source, meta), globals)
        if value is MISSING:
            return _decline(node, source, where, _segment(source, meta))
        values.append(value)
    try:
        return marker[(type,) + tuple(values)] if values else marker[type]
    except Exception:
        return _decline(node, source, where, _segment(source, node))


def _structural_marker(node: ast.AST, globals: dict, where: str) -> tx.Any:
    # The marker a subscripted annotation is built by (`KwOnly` in
    # `KwOnly[int]`), or MISSING when the annotation is a plain type.
    if not isinstance(node, ast.Subscript):
        return MISSING
    parts = _dotted_name(node.value)
    if parts is None:
        return MISSING
    marker = _lookup_dotted(parts, globals)
    if marker is MISSING:
        if parts[-1] in _STRUCTURAL_NAMES:
            warnings.warn(
                f"{where} is annotated with {'.'.join(parts)}, which is "
                f"not defined where the class is written, so it cannot be "
                f"applied to the field. A name only imported under `if "
                f"TYPE_CHECKING:` is not there at runtime -- import "
                f"{parts[0]} normally for the annotation to take effect.",
                _UnreadableAnnotation,
                stacklevel=_caller_stacklevel(),
            )
        return MISSING
    return marker if _is_structural(marker) else MISSING


def _decline(node: ast.AST, source: str, where: str, part: str) -> str:
    # The marker was recognised but could not be rebuilt. Say so, and
    # keep the annotation as the text it arrived as.
    text = _segment(source, node)
    warnings.warn(
        f"{where} is annotated with {text}, and {part} could not be read "
        f"back, so the annotation is kept as text and has no effect on "
        f"how the field is built.",
        _UnreadableAnnotation,
        stacklevel=_caller_stacklevel(),
    )
    return text


def _namespace_annotations(
    namespace: dict, globals: dict, clsname: str
) -> dict:
    # The annotations declared in a class body, read from the namespace the
    # metaclass receives -- before the class object exists.
    #
    # Up to Python 3.13 the namespace holds ``__annotations__`` directly.
    # From 3.14 (PEP 649/749) annotations are lazy: the namespace instead
    # carries an ``__annotate__`` function, retrieved via ``annotationlib``.
    if "__annotations__" in namespace:
        # Python <= 3.13: coverage runs on 3.14+, where annotations are lazy
        # and the namespace never carries __annotations__, so this is dead.
        annotations = namespace["__annotations__"]  # pragma: no cover
    else:
        try:
            import annotationlib
        except ImportError:  # pragma: no cover  -- Python < 3.14
            return {}
        annotate = annotationlib.get_annotate_from_class_namespace(namespace)
        if annotate is None:
            return {}
        # FORWARDREF never raises on not-yet-defined names (they become
        # ``ForwardRef``), which keeps class creation robust.
        annotations = annotationlib.call_annotate_function(
            annotate, annotationlib.Format.FORWARDREF
        )
    return _resolve_string_annotations(annotations, globals, clsname)


def _resolve_string_annotations(
    annotations: dict, globals: dict, clsname: str
) -> dict:
    # Annotations that are text -- every one of them under `from
    # __future__ import annotations`, and any single quoted one
    # otherwise -- are read back far enough to see how each field is
    # meant to be built. Whatever already arrived as an object is left
    # alone, so on Python 3.14+, where the runtime hands over
    # `ForwardRef`s of its own, there is nothing here to redo.
    resolved = {}
    for name, hint in annotations.items():
        if not isinstance(hint, str):
            resolved[name] = hint
            continue
        source = hint.strip()
        try:
            node = ast.parse(source, mode="eval").body
        except SyntaxError:
            resolved[name] = hint
            continue
        resolved[name] = _read_annotation(
            node, source, globals, f"{clsname}.{name}"
        )
    return resolved


class _BadSignature(SyntaxError):
    """A field layout that cannot produce an `__init__` signature."""


def _unbuildable_init(clsname: str, reason: str) -> tx.Callable:
    """Stand-in for an `__init__` this class's fields cannot describe."""

    def __magic_init__(self: Magic, *args, **kwargs) -> tx.NoReturn:
        raise TypeError(
            f"no __init__ could be generated for {clsname}: {reason}"
        )

    return __magic_init__


def _no_order(self: Magic, other: tx.Any) -> tx.Any:
    """Take the place of an ordering method a subclass turned off.

    Returning `NotImplemented` tells Python nobody knows how to compare
    these two, so it raises its usual "'<' not supported between
    instances of ..." -- which is what a class without ordering should
    do. There is no `object.__lt__` to fall back on, hence this.
    """
    return NotImplemented


#: The four comparison methods the `order` option generates: the name
#: each is normally bound under, and the operator it applies to the
#: tuple of values of the fields that take part in the ordering.
_ORDER_METHODS = {
    "lt": ("__lt__", operator.lt),
    "le": ("__le__", operator.le),
    "gt": ("__gt__", operator.gt),
    "ge": ("__ge__", operator.ge),
}


#: What is put in place of a generated method or value when an option
#: is turned off. These are the answers a plain Python class gives:
#: the `<Thing object at 0x...>` repr, comparison by identity, no
#: ordering, no hash once `__eq__` is written, and nothing for a `case`
#: pattern to bind.
_NEUTRAL = {
    "repr": object.__repr__,
    "eq": object.__eq__,
    "lt": _no_order,
    "le": _no_order,
    "gt": _no_order,
    "ge": _no_order,
    "hash": None,
    # An empty tuple is what a class with no pattern-matching support
    # has: `case C(x)` refuses to bind anything positionally.
    "match_args": (),
}


def _generated_methods(cls: type) -> dict:
    """Which of this class's attributes Magic wrote, and for what.

    Covers the generated methods and the `__match_args__` tuple. Maps
    the name each was bound under to the option that produced it --
    `{"__eq__": "eq"}` normally, `{"__same__": "eq"}` if the class asked
    for `eq="__same__"`.

    Only the names a subclass might have to replace are listed, so the
    private `__magic_*__` names are left out: every class writes its own,
    and they must never be mistaken for something inherited.

    This is not the same question as "is this a Magic class". A Magic
    class can perfectly well have a hand-written `__eq__`, because a
    method in the class body always wins over the generated one. Only
    this record can tell the two apart, and telling them apart is what
    decides whether a subclass may replace the method.

    It is a record on the class rather than a mark on what was bound,
    because most of what gets bound cannot carry a mark: a generated
    `__hash__` is sometimes `None`, a turned-off option leaves behind
    `object.__eq__`, which is a built-in, and `__match_args__` is a
    tuple.
    """
    return cls.__dict__.get(_GENERATED) or {}


def _defining_class(mro: tx.Tuple[type, ...], name: str) -> tx.Any:
    """Which class actually provides `name` -- the one Python will use."""
    for base in mro:
        if name in base.__dict__:
            return base
    return None


def _inherited_generated(
    mro: tx.Tuple[type, ...], slot: str
) -> tx.List[str]:
    """Names inherited from a base that hold a method Magic generated.

    There can be more than one: a base may have asked for the method
    under a name of its own (`eq="__same__"`) while a class further up
    still has it under `__eq__`.

    A name only counts if the class actually providing it is the class
    that generated it. That way a hand-written method closer to the
    front of the inheritance chain -- the one Python would really call
    -- hides a generated one behind it, and is left alone.
    """
    names = []
    for base in mro:
        for name, base_slot in _generated_methods(base).items():
            if base_slot != slot or name in names:
                continue
            owner = _defining_class(mro, name)
            if owner is not None and name in _generated_methods(owner):
                names.append(name)
    return names


def _install(
    namespace: dict,
    generated: dict,
    mro: tx.Tuple[type, ...],
    slot: str,
    public: str,
    fn: tx.Any,
    enabled: bool,
) -> bool:
    """
    Put one generated method or value on the class being built.

    Everything here is a method apart from `__match_args__`, which is a
    tuple of field names.

    It is always bound under its private name (`__magic_eq__` and
    friends), so that a hand-written method can reach the generated
    one. It is bound under its public name (`__eq__`) only if the class
    asked for it.

    If the class did *not* ask for it, anything generated it would
    otherwise inherit is replaced by the plain-Python behaviour. What
    is generated belongs to the class it was made for: it only knows
    that class's fields, so letting it answer for a different class
    gives wrong answers. Whatever you wrote yourself is never replaced.

    Returns whether the public name ended up holding ours.
    """
    private = _MAGIC(slot)
    if private in namespace:
        raise TypeError(
            f"{private} is written by Magic, so a class cannot define its "
            f"own. Write {public} instead, and use {private} from there if "
            f"you want what Magic generated."
        )
    namespace[private] = fn

    # Replace any inherited generated method for this option, apart from
    # the one this class is about to write. This also covers a class
    # that renamed the method: asking for it under another name is a way
    # of saying you do not want the usual one.
    for name in _inherited_generated(mro, slot):
        if name != public and name not in namespace:
            namespace[name] = _NEUTRAL[slot]
            generated[name] = slot

    if enabled:
        if public in namespace:
            return False
        namespace[public] = fn
        generated[public] = slot
        return True

    if public not in namespace and public in _inherited_generated(mro, slot):
        namespace[public] = _NEUTRAL[slot]
        generated[public] = slot
    return False


def _slot_names(
    mro: tx.Tuple[type, ...], namespace: dict
) -> tx.Tuple[str, ...]:
    """Every slot an instance of the class being built can hold.

    Slots are inherited, so this is the whole chain of bases and not
    just what the class itself declares. `__dict__` and `__weakref__`
    are left out: they are places to keep attributes, not attributes.
    """
    names = set()
    for base in mro:
        names.update(_get_slots(base))
    own = namespace.get("__slots__")
    names.update((own,) if isinstance(own, str) else (own or ()))
    names -= {"__dict__", "__weakref__"}
    return tuple(sorted(names))


def _install_state(
    namespace: dict,
    generated: dict,
    mro: tx.Tuple[type, ...],
    qualname: str,
    frozen: bool,
) -> None:
    """
    Bind the two methods `pickle` and `copy` use to save and restore an
    object, if this class needs them.

    A frozen class needs them: restoring an object means putting the
    saved values back on it, which a frozen class refuses through the
    usual attribute assignment.

    Every class below one of those needs a pair of its own as well. The
    pair carries the names of the slots to save, so a base's pair leaves
    out each slot the class has added, and a copy comes back missing
    them.

    There is no option to turn these off, and no plain-Python method to
    put in their place, so the only question is whether to write them.
    Methods you wrote yourself are left alone: the two have to agree
    with each other, so writing one of them means both are yours.
    """
    if not frozen and not _inherited_generated(mro, "state"):
        return
    names = ("__getstate__", "__setstate__")
    if any(name in namespace for name in names):
        return
    pair = _make_state(qualname, _slot_names(mro, namespace))
    for name, fn in zip(names, pair):
        namespace[name] = fn
        generated[name] = "state"


def _install_hash(
    namespace: dict,
    generated: dict,
    mro: tx.Tuple[type, ...],
    options: Options,
    qualname: str,
    real_fields: dict,
    has_explicit_hash: bool,
    eq_is_identity: bool,
) -> None:
    """
    Work out what `__hash__` should be for this class, and bind it.

    A hash built from the fields is always available under
    `__magic_hash__`. What ends up on `__hash__` itself is decided here
    rather than simply inherited, because Python drops `__hash__` from
    any class that defines `__eq__` without also defining `__hash__` --
    so once an `__eq__` has been written, leaving `__hash__` alone is
    not one of the choices.
    """
    private = _MAGIC("hash")
    if private in namespace:
        raise TypeError(
            f"{private} is written by Magic, so a class cannot define its "
            f"own. Write __hash__ instead, and call {private} from it if "
            f"you want the generated one."
        )
    namespace[private] = _hash_add(qualname, real_fields)

    # A truthy `hash` means "generate one", the same force the
    # `unsafe_hash` column applies. `False` means never, and `None` (the
    # default) leaves the table to decide.
    force = bool(options.unsafe_hash) or bool(
        options.hash is not None and options.hash
    )
    make = _hash_action[force, bool(options.eq), bool(options.frozen),
                        has_explicit_hash]
    if options.hash is False:
        make = False

    public = options.hash if isinstance(options.hash, str) else "__hash__"
    inherited = _inherited_generated(mro, "hash")

    if make:
        # `_hash_exception` raises here, which is the point of it.
        value = make(qualname, real_fields)
    elif options.hash is False:
        # Explicitly unhashable, whatever any base offers.
        value = None
    elif eq_is_identity:
        # Identity equality wants identity hashing -- but a class we did
        # not generate gets the last word, including when it declares
        # itself unhashable (`collections.abc.Mapping.__hash__ = None`).
        # Our own entries are skipped: a `__hash__ = None` on `Magic`
        # says something about `Magic`, not about this class. `object`
        # ends the walk, which is how the identity hash is reached.
        owner = next(
            (base for base in mro
             if "__hash__" in base.__dict__
             and "__hash__" not in _generated_methods(base)),
            None,
        )
        value = owner.__dict__["__hash__"] if owner else object.__hash__
    elif inherited:
        # Nothing generated here, but a base's field-wise hash would
        # answer over this class's fields.
        value = None
    else:
        return

    for name in [public] + inherited:
        if name not in namespace:
            namespace[name] = value
            generated[name] = "hash"


# Types whose values can always be changed in place. A default of one
# of these would be handed out, as the very same object, to every
# instance -- so appending to `a.x` would also change `b.x`.
_MUTABLE_TYPES = (list, dict, set, bytearray)

# The accepted values of the `mutable_default` class option.
_MUTABLE_DEFAULT_ACTIONS = ("factory", "raise", "allow")

# The accepted values of the `polymorphic` class option. "strict" means
# "if I have registrations and none of them match, refuse to build" --
# not "never build me": every subclass of a polymorphic class is
# polymorphic too, so the other reading would leave the leaves of a
# hierarchy unbuildable.
_POLYMORPHIC = (False, True, "strict")

# The accepted values of the `pin_discriminant` class option.
_PIN_ACTIONS = ("pin", "classvar", "keep")


def _polymorphic_base(mro: tx.Tuple[type, ...]) -> tx.Optional[type]:
    # The nearest class up the chain that builds its subclasses. A
    # subclass registers with that one rather than with the root, so
    # each level narrows the choice by one step.
    for base in mro:
        if getattr(getattr(base, _OPTIONS, None), "polymorphic", False):
            return base
    return None


def _pin_discriminants(
    fields: dict,
    namespace: dict,
    declared: tx.Container[str],
    specs: tx.Sequence,
    action: str,
) -> tx.Set[str]:
    # A subclass registered for one exact value already says what that
    # field holds, so it does not have to say it twice: the field is
    # given that value as its default ("pin"), or becomes a class
    # attribute that is not stored per instance ("classvar"). A field
    # the subclass writes out itself is left exactly as written.
    #
    # Under "classvar" the field stays a parameter of `__init__` and its
    # value is thrown away, so both `Chord(mode="minor", root="A")` --
    # which passes the argument straight through -- and
    # `MinorChord(mode="minor", root="A")` keep working.
    pinned = set()
    for spec in specs:
        if spec.value is MISSING:
            # More than one value would satisfy this constraint, so
            # there is nothing to pin the field to.
            continue
        field = fields[spec.name]
        if field.name in declared:
            continue
        field.default = spec.value
        field.factory = False
        if action == "classvar":
            field.var = True
            field.repr = SHOW_ATTR(False)
            field.key = SHOW_ATTR(False)
            field.eq = field.order = False
            field.hash = False
            namespace[field.name] = spec.value
        pinned.add(field.name)
    return pinned


def _is_mutable(value: tx.Any) -> bool:
    # Besides the obvious builtins, anything unhashable counts: a class
    # that defines `__eq__` without `__hash__` is saying its values
    # compare by content and can change, which is exactly the case we
    # must not share.
    return (
        isinstance(value, _MUTABLE_TYPES) or
        value.__class__.__hash__ is None
    )


def _handle_mutable_default(field: Field, action: str) -> bool:
    # Deal with a default that every instance would otherwise share,
    # such as `x: list = []`. Returns True if the default was turned
    # into a factory, in which case the class attribute holding the
    # original must go, exactly as it would for a hand-written factory.
    #
    # A `ClassVar` keeps its default as a class attribute and is never
    # assigned per instance, so there is nothing to promote and nothing
    # to warn about: that value is meant to be shared. Every other
    # field's default reaches an instance -- as a parameter's default,
    # or assigned by the generated `__init__` to a field that has no
    # parameter of its own.
    default = field.default
    if (
        action == "allow" or
        default is MISSING or
        field.factory or
        (field.var and not field.init) or
        not _is_mutable(default)
    ):
        return False

    typename = type(default).__name__
    hint = (
        f"give the field a factory instead -- "
        f"`{field.name}: Factory[{typename}]` builds a new {typename} "
        f"per instance -- or pass mutable_default='allow' to share one "
        f"on purpose"
    )

    if action == "raise":
        raise ValueError(
            f"the default {default!r} of field {field.name!r} would be "
            f"shared by every instance, and any one of them could "
            f"change it; {hint}"
        )

    try:
        copy.copy(default)
    except Exception as exc:
        raise ValueError(
            f"the default {default!r} of field {field.name!r} would be "
            f"shared by every instance, and it cannot be copied to give "
            f"each one its own; {hint}"
        ) from exc

    # A shallow copy, so each instance gets its own container while
    # what the container holds stays shared -- the same thing a factory
    # written as `lambda: copy(default)` would give.
    # Recorded as the field's own, so that a subclass resolving the
    # field again against its own settings does not undo it.
    field._redeclare(factory=partial(copy.copy, default))
    field.default = MISSING
    return True


def _find_hook(
    namespace: dict, mro: tx.Tuple[type, ...], name: str
) -> tx.Any:
    """The `__pre_init__` or `__post_init__` this class will call.

    A hook written in the class body wins; failing that, one inherited
    from a Magic base counts too, so that a family of classes can share
    a single hook rather than repeating it in every subclass.

    Only a Magic base is looked at. A class of somebody else's that
    happens to have a method by one of these names wrote it for their
    own library, and calling it with our arguments would do something
    unwanted.

    The search follows the real inheritance order and reads the class
    dictionary directly, so it finds the same hook Python will call. A
    plain attribute lookup would answer with the first base that has one
    rather than the first in the inheritance order, and would fall
    through to the metaclass if no base had one at all.

    What comes back is what the class body held -- a plain function, or
    a `staticmethod`, or anything else callable. `_bind_hook` turns that
    into the thing the instance will actually call.
    """
    if name in namespace:
        return namespace[name]
    for base in mro:
        if getattr(base, _FIELDS, None) is None:
            continue
        if name in base.__dict__:
            return base.__dict__[name]
    return None


#: Stand-in instance for working out what a hook's parameters will be.
#: Binding a function to it gives the same signature binding it to a real
#: instance would, and the class does not exist yet at this point.
_HOOK_SELF = object()


def _bind_hook(hook: tx.Any) -> tx.Any:
    """The hook as the instance will call it.

    The generated `__init__` calls `self.__post_init__(...)`, so what
    matters is the parameters left *after* attribute access has done its
    work: a plain method loses `self`, a `classmethod` loses `cls`, and
    a `staticmethod` loses nothing. Letting the descriptor protocol
    answer that is the only way to get all three right.
    """
    bind = getattr(type(hook), "__get__", None)
    if bind is None:
        # Not a descriptor -- a callable object, say, whose own
        # `__call__` already hides its `self`.
        return hook
    return bind(hook, _HOOK_SELF, type(_HOOK_SELF))


def _hook_wants_arguments(clsname: str, name: str, hook: tx.Any) -> bool:
    """Whether this hook is to be handed the values `__init__` got.

    A hook that declares a parameter wants them; one that declares none
    is called with nothing. Declaring more than one is a mistake, since
    there is only ever a single object to pass.
    """
    try:
        parameters = list(signature(_bind_hook(hook)).parameters.values())
    except (TypeError, ValueError):
        # Nothing readable to go on. Passing the values is the safer
        # guess: a hook that wanted none fails loudly on the extra
        # argument, where a hook that wanted them and got none would
        # quietly do the wrong thing.
        return True

    positional = [
        parameter for parameter in parameters
        if parameter.kind in (
            Parameter.POSITIONAL_ONLY,
            Parameter.POSITIONAL_OR_KEYWORD,
            Parameter.VAR_POSITIONAL,
        )
    ]
    required = [
        parameter for parameter in positional
        if parameter.default is Parameter.empty
        and parameter.kind is not Parameter.VAR_POSITIONAL
    ]
    if len(required) > 1:
        listed = ", ".join(parameter.name for parameter in required)
        raise TypeError(
            f"{clsname}.{name} takes several arguments ({listed}), but it "
            f"is called with one: an object holding every value passed to "
            f"__init__. Give it a single parameter and read the values off "
            f"that -- `arguments.{required[0].name}` in place of "
            f"`{required[0].name}`."
        )
    return bool(positional)


def _prepost_hooks(
    clsname: str, namespace: dict, mro: tx.Tuple[type, ...]
) -> tx.Dict[str, bool]:
    """Which init hooks to call, and whether each wants the values.

    Maps `__pre_init__` and/or `__post_init__` -- whichever the class
    has -- to whether the generated `__init__` should hand it an
    `Arguments` object.
    """
    hooks = {}
    for name in (_PRE_INIT_NAME, _POST_INIT_NAME):
        hook = _find_hook(namespace, mro, name)
        if hook is not None:
            hooks[name] = _hook_wants_arguments(clsname, name, hook)
    return hooks


def _mro(
    bases: tx.Tuple[type, ...], namespace: dict
) -> tx.Tuple[type, ...]:
    """The resolution order of a class built from `bases`.

    Python works an order out for a class that exists, so a throwaway
    class is built here just to read it back off. Its first entry is
    that throwaway class; every entry after it is an ancestor the real
    class will have, ending with `object`.

    A class written as `class Box(Magic, Generic[T])` reaches this
    module with `Generic[T]` already replaced by plain `Generic` in its
    bases, and `Generic` refuses to be a base on its own. What tells
    the two apart is `__orig_bases__` -- the bases as they were
    written -- so the throwaway is given the same one, and is measured
    against the same bases as the real class.
    """
    stand_in_namespace = {}
    if "__orig_bases__" in namespace:
        stand_in_namespace["__orig_bases__"] = namespace["__orig_bases__"]
    return type(_DISCARD, bases, stand_in_namespace).__mro__


def __pre_new__(

    metacls: MetaMagic,
    clsname: str,
    bases: tuple[type, ...],
    namespace: dict,
    **kwargs
) -> tuple[str, tuple[type, ...], dict]:

    if clsname == _DISCARD:
        # This is a dummy class used to compute the MRO of our class
        # without including the class itself.
        return clsname, bases, namespace

    # `on=` and `priority=` describe this one class rather than setting
    # an option, so they are taken out before the options are read --
    # nothing inherits them.
    on = kwargs.pop("on", MISSING)
    priority = kwargs.pop("priority", MISSING)
    if priority is not MISSING and on is MISSING:
        raise TypeError(
            f"{clsname} sets priority= without on=, and priority only "
            f"decides between subclasses that match the same arguments. "
            f"Say what {clsname} stands for as well -- "
            f"`class {clsname}(..., on={{'mode': 'minor'}}, priority=1)`."
        )

    # `_FIELDS` in the namespace means this class has been through here
    # before. A direct lookup, so a base class having it does not count.
    if _FIELDS in namespace:
        raise TypeError(
            f"{clsname} is already a Magic class, so it cannot be built a "
            f"second time. This happens when @magic is used twice on the "
            f"same class, or when it is used on a class that already "
            f"inherits from Magic. Put the options on the class statement "
            f"instead -- `class {clsname}(Magic, frozen=True)` -- which "
            f"does the same job."
        )

    # Get globals of the module where this class is defined.
    # `__module__` is absent when the class is built through the
    # functional API (`MetaMagic(name, bases, namespace)`) rather than a
    # class statement.
    module = namespace.get("__module__")
    if module in sys.modules:
        globals = sys.modules[module].__dict__
    else:
        # Theoretically this can happen if someone writes
        # a custom string to cls.__module__.  In which case
        # such dataclass won't be fully introspectable
        # (w.r.t. typing.get_type_hints) but will still function
        # correctly.
        globals = {}

    fnbuilder = _FuncBuilder(globals)

    # Save qualified name -- we will use it when generating methods.
    qualname = namespace.get("__qualname__", None)

    # Now that dicts retain insertion order, there's no reason to use
    # an ordered dict.  I am leveraging that ordering here, because
    # derived class fields overwrite base class fields, but the order
    # is defined by the base class, which is found first.
    fields = {}

    # Class options that are not explicitly set are inherited from
    # base classes in MRO order. Derived classes only override base
    # classes if options are explicitly set (not MISSING).
    options = Options.make_default()

    # Find our base classes in reverse MRO order, so that order is
    # obtained from MRO, but value is obtained from most derived class.
    mro = _mro(bases, namespace)

    # What this class fills in for the type variables its bases were
    # written with: `class IntBox(Box[int])` says that `Box`'s `T` is
    # `int` here. Kept per base, so that two parameterised bases fill in
    # their own variables and not each other's.
    arguments = _type_arguments(namespace)

    # Which of those applies to each inherited field, once every base has
    # had its say. A field a later base also declares is that base's, so
    # the last word on the field is the last word on its type variables
    # too -- including "none", when that base fills nothing in.
    inherited_arguments = {}

    # `mro[0]` is the throwaway class built above to work out the
    # inheritance order. It has no fields of its own -- it only inherits
    # the most derived base's, which the loop reads off that base
    # anyway -- and nothing was written as one of *its* type variables,
    # so reading it would only undo what that base said.
    for b in reversed(mro[1:]):
        # Only process classes that have been processed by our
        # decorator.  That is, they have a _FIELDS attribute.
        base_fields = getattr(b, _FIELDS, None)
        if base_fields is not None:
            base_options = getattr(b, _OPTIONS)
            options.update(base_options)
            _add_fields(
                fields,
                base_fields.values(),
                replace=True,
                reverse=options.reverse
            )
            if arguments:
                for field_name in base_fields:
                    inherited_arguments[field_name] = arguments.get(b)

    # Save final options for this class.
    options.update(Options(**kwargs))
    namespace[_OPTIONS] = options

    # Once a class is dict-like, none of its subclasses can stop being
    # one, so a subclass that turns `mapping` off is asking for
    # something that cannot be delivered. The class to name is the
    # furthest one along the chain that is dict-like: `mapping` is
    # inherited, so every class below the one that asked for it has the
    # option set too, and turning it off on any of those would only
    # raise this again. `mro[0]` is the throwaway class built above to
    # work out the inheritance order; it is not a base of anything.
    mapping_base = None
    for b in mro[1:]:
        if getattr(getattr(b, _OPTIONS, None), "mapping", False):
            mapping_base = b
    if mapping_base is not None and not options.mapping:
        raise TypeError(
            f"{clsname} gets its dict-like behaviour from "
            f"{mapping_base.__name__}, and a subclass cannot take it "
            f"away: {clsname} would still answer yes to an isinstance "
            f"check against Mapping, while the dict-like methods it "
            f"inherited would report {mapping_base.__name__}'s fields "
            f"instead of its own. Either leave mapping alone here, or "
            f"turn it off on {mapping_base.__name__} and ask for it only "
            f"on the subclasses that want it."
        )

    if options.mutable_default not in _MUTABLE_DEFAULT_ACTIONS:
        raise ValueError(
            f"mutable_default must be 'factory', 'raise' or 'allow', "
            f"not {options.mutable_default!r}"
        )

    if options.polymorphic not in _POLYMORPHIC:
        raise ValueError(
            f"polymorphic must be False, True or 'strict', "
            f"not {options.polymorphic!r}"
        )

    if options.pin_discriminant not in _PIN_ACTIONS:
        raise ValueError(
            f"pin_discriminant must be 'pin', 'classvar' or 'keep', "
            f"not {options.pin_discriminant!r}"
        )

    if options.unresolved_hints not in _HINT_POLICIES:
        raise ValueError(
            f"unresolved_hints must be 'warn', 'raise' or 'ignore', "
            f"not {options.unresolved_hints!r}"
        )

    # Where a type this class was annotated with by name is looked up
    # when a field first needs it. The class itself is added to the
    # namespace once it exists, by `__post_new__`.
    hints = Hints(globals, {}, clsname, options.unresolved_hints)
    namespace[_HINTS] = hints

    # Fill the type variables in on the fields that came from a base
    # written with them. A field this class declares again is built from
    # its own annotation further down and replaces the one filled in
    # here, so only what really is inherited is touched.
    for field_name, base_arguments in inherited_arguments.items():
        if base_arguments:
            _fill_in_type(fields[field_name], base_arguments, hints)
    # An inherited field was resolved against the settings of the class
    # that declared it, and keeps those answers. `override` names the
    # settings this class decides again for every field it inherits --
    # only where the field itself said nothing, since what a field asked
    # for is restored unchanged. A field this class redeclares is built
    # from its annotation below and replaces the inherited one, so it
    # never goes through here.
    #
    # A converter, validator or factory rebuilt here looks a type named
    # in text up where *this* class is written, which is where the class
    # asking for the conversion can be read. A base in another module
    # that annotated a field by name is the one case that reaches for a
    # name this module may not have, and `unresolved_hints` says what
    # happens then.
    override = _override_attrs(options.override, clsname)
    if override:
        for field in fields.values():
            field._reresolve(options, override, hints)
            _wrap_show_attrs(field)
    # Annotations that are defined in this class (not in base
    # classes).  If __annotations__ isn't present, then this class
    # adds no new   We use this to compute fields that are
    # added by this class.
    #
    # Fields are found from cls_annotations, which is guaranteed to be
    # ordered.  Default values are from class attributes, if a field
    # has a default.  If the default value is a Field(), then it
    # contains additional info beyond (and possibly including) the
    # actual default value.  Pseudo-fields ClassVars and InitVars are
    # included, despite the fact that they're not real fields.  That's
    # dealt with later.
    cls_annotations = _namespace_annotations(namespace, globals, clsname)

    # Now find fields in our class.  While doing so, validate some
    # things, and set the d
    cls_fields = []
    for field_name, type_ in cls_annotations.items():

        if field_name[:2] == "__":
            # Dunder name -> ignore (same behavior as attrs)
            continue

        # Make Field from annotation
        field = Field.from_hint(field_name, type_)

        # If the class attribute (which is the default value for this
        # field) exists and is of type `Field`, replace it with the real
        # default. This is so that normal class introspection sees a
        # real default value, not a `Field`.
        if isinstance(namespace.get(field.name), Field):
            field.update(namespace[field.name])
            if field.default is MISSING:
                # If there's no default, delete the class attribute.
                # This happens if we specify field(repr=False), for
                # example (that is, we specified a field object, but
                # no default value).  Also if we're using a default
                # factory.  The class attribute should not be set at
                # all in the post-processed class.
                namespace.pop(field.name, None)
            else:
                namespace[field.name] = field.default

        # If the class attribute exists and is not a Field, then use it
        # as the default value for this field.
        elif field.name in namespace:
            field.default = namespace[field.name]

        # Set unset field options from class options
        field.setdefault(options, hints)

        # A mutable default is promoted to a factory (or rejected),
        # so that instances do not end up sharing one object.
        if _handle_mutable_default(field, options.mutable_default):
            namespace.pop(field.name, None)

        # Python refuses to create a class where the same name is both
        # a slot and a class attribute, so a default that is going to be
        # stored in a slot cannot stay in the namespace. Every field
        # that is stored on the instance -- that is, every field but a
        # pseudo-field -- gets a slot, and the generated `__init__`
        # assigns it its default, so the class attribute is dropped
        # here. On a class that generates no `__init__` of its own the
        # default is then only reachable through `__magic_init__`.
        if options.slots and not field.var:
            namespace.pop(field.name, None)

        _wrap_show_attrs(field)

        cls_fields.append(field)

    # Insert fields from this class, in correct order.
    _add_fields(fields, cls_fields, replace=True, reverse=options.reverse)

    # Which fields carry a default only because a registration pinned
    # them -- here or further up. `_make_init` has to know, because a
    # pinned default can leave a parameter without one behind it.
    pinned = set()
    for base in mro[1:]:
        pinned.update(getattr(base, _PINNED, ()))

    # What this class stands for, if it said. The constraints are read
    # against the class it registers with -- so a misspelled field name
    # is refused here, where it was written, rather than the first time
    # something is built. The registration itself waits until the class
    # exists; `__post_new__` does it.
    if on is not MISSING:
        polymorphic_base = _polymorphic_base(mro[1:])
        if polymorphic_base is None:
            raise TypeError(
                f"{clsname} says with on= which arguments it stands for, "
                f"but none of the classes it inherits from builds its "
                f"subclasses. Add polymorphic=True to the one that "
                f"should -- `class Chord(Magic, polymorphic=True)`."
            )
        specs = _specifications(polymorphic_base, clsname, on)
        namespace[_REGISTRATION] = (
            polymorphic_base,
            specs,
            0 if priority is MISSING else priority,
        )
        if options.pin_discriminant != "keep":
            pinned.update(_pin_discriminants(
                fields, namespace, cls_annotations, specs,
                options.pin_discriminant,
            ))

    # A subclass that declares the field again, with no default of its
    # own, has taken the pin away.
    pinned = {
        name for name in pinned
        if name in fields and fields[name].default is not MISSING
    }
    if pinned:
        namespace[_PINNED] = frozenset(pinned)

    # Do we have any Field members that don't also have annotations?
    for attr_name, value in namespace.items():
        if isinstance(value, Field) and attr_name not in cls_annotations:
            raise TypeError(
                f'{attr_name!r} is a field but has no type annotation'
            )

    _check_public_names(clsname, fields)
    _check_public_keys(clsname, fields)

    # Remember all of the fields on our class (including bases).
    namespace[_FIELDS] = fields

    # Was this class defined with an explicit __hash__?  Note that if
    # __eq__ is defined in this class, then python will automatically
    # set __hash__ to None.  This is a heuristic, as it's possible
    # that such a __hash__ == None was not auto-generated, but it's
    # close enough.
    class_hash = namespace.get('__hash__', MISSING)
    has_explicit_hash = not (class_hash is MISSING or
                             (class_hash is None and '__eq__' in namespace))

    # If we're generating ordering methods, we must be generating the
    # eq methods. Total ordering over the fields combined with identity
    # equality gives `not (a < b) and not (b < a) and a != b`, which
    # breaks everything that sorts.
    if options.order and not options.eq:
        raise ValueError('eq must be true if order is true')
    for field in fields.values():
        if field.order and not field.eq:
            raise ValueError('eq must be true if order is true')

    prepost = _prepost_hooks(clsname, namespace, mro)

    # Every generated method is also bound under a private name, whether
    # or not the class asked for the public one, so that a hand-written
    # method can call the generated one:
    #
    #     def __init__(self, raw):
    #         self.__magic_init__(int(raw))
    #
    # `generated` collects what gets bound here, and is stored on the
    # finished class so that a subclass can tell a generated method from
    # one you wrote.
    generated = {}
    init_name = (
        ("__init__" if options.init is True else options.init)
        if options.init else None
    )

    # Build __init__. The builder writes source, so binding the public
    # name has to wait until `insert_fns` has compiled it (below).
    try:
        init_kwargs = _make_init(
            fields, prepost, clsname,
            {fields[name].public_name for name in pinned},
        )
    except _BadSignature as error:
        if init_name:
            raise
        # This class does not want an `__init__`, so being unable to
        # build one must not stop the class being created. It still gets
        # its own `__magic_init__`, one that explains the problem if it
        # is ever called -- without it, `self.__magic_init__(...)` would
        # quietly find a base class's version and set the wrong fields.
        init_kwargs = None
        namespace.setdefault(
            _MAGIC("init"), _unbuildable_init(clsname, str(error))
        )
    if init_kwargs is not None:
        fnbuilder.add_fn(
            name=_MAGIC("init"),
            overwrite_error=(
                f"-- define {init_name or '__init__'!r} instead and call it "
                f"from there"
            ),
            **init_kwargs
        )

    # TODO
    # _set_new_attribute(cls, '__replace__', _replace)

    # Include only real fields.  This is used in all of the following methods.
    real_fields = {name: f for name, f in fields.items() if not f.var}

    if options.mapping:
        # Only real fields: a `ClassVar` belongs to the class and an
        # `InitVar` is a constructor argument, so neither is part of the
        # data and neither is stored on the instance. Reading one back
        # off an instance answers with the class attribute, or with
        # nothing at all.
        dict_fields = {
            f.public_key: f for f in real_fields.values() if f.key
        }
        for name, func in _make_mapping(qualname, dict_fields).items():
            namespace.setdefault(name, func)
        Mapping = _abc.Mapping if options.frozen else _abc.MutableMapping
        if not any(issubclass(base, Mapping) for base in bases):
            bases += (Mapping,)

    # The generated methods are installed here, once `bases` is settled:
    # the `mapping` option can add one, and working out what a class
    # would otherwise inherit means looking at the bases it really has.
    base_mro = _mro(bases, namespace)[1:]

    _install(
        namespace, generated, base_mro, "match_args",
        (
            options.match_args
            if isinstance(options.match_args, str)
            else "__match_args__"
        ),
        # Only the fields that can be matched by position: a
        # keyword-only field, or one the constructor does not take at
        # all, has no place to be matched from.
        tuple(f.public_name for f in fields.values() if f.positional),
        bool(options.match_args),
    )

    repr_fields = {name: f for name, f in fields.items() if f.repr}
    _install(
        namespace, generated, base_mro, "repr",
        options.repr if isinstance(options.repr, str) else "__repr__",
        _make_repr(qualname, repr_fields), bool(options.repr),
    )

    _install(
        namespace, generated, base_mro, "eq",
        options.eq if isinstance(options.eq, str) else "__eq__",
        _make_eq(qualname, real_fields), bool(options.eq),
    )

    # The four comparisons are generated as a set, so that they always
    # agree with each other. `order=True` binds each to its operator;
    # `order="<name>"` binds the `<` comparison under that name and
    # binds none of the operators. A comparison written in the class
    # body wins, and then none of the other three is bound either --
    # they would answer beside it with a different answer. All four are
    # written under their private names whatever happens.
    named_order = isinstance(options.order, str)
    order_names = [dunder for dunder, _ in _ORDER_METHODS.values()]
    if named_order:
        order_names.append(options.order)
    hand_written_order = any(name in namespace for name in order_names)
    for slot, (dunder, _) in _ORDER_METHODS.items():
        _install(
            namespace, generated, base_mro, slot,
            options.order if named_order and slot == "lt" else dunder,
            _make_order(qualname, real_fields, slot),
            bool(options.order) and not hand_written_order
            and (slot == "lt" or not named_order),
        )

    # Whether this class compares by identity is read back out of the
    # namespace: what matters is where `__eq__` ended up, not how it got
    # there. And it is `__eq__` under that exact name, no other, that
    # makes Python drop `__hash__`.
    _install_hash(
        namespace, generated, base_mro, options, qualname or clsname,
        real_fields,
        has_explicit_hash, namespace.get("__eq__") is object.__eq__,
    )

    # It's an error to specify weakref_slot if slots is False.
    if options.weakref_slot and not options.slots:
        raise TypeError('weakref_slot is True but slots is False')
    if options.slots:
        if '__slots__' in namespace:
            raise TypeError(f'{clsname} already specifies __slots__')
        weakref_slot = options.weakref_slot
        # Every class this one inherits from, `object` aside: a field
        # already given a slot by one of them does not need another.
        namespace["__slots__"] = _make_slots(
            base_mro[:-1], real_fields, weakref_slot
        )

    # Saving an object means saving its slots, so this waits until
    # `__slots__` is settled as well as `bases`.
    _install_state(
        namespace, generated, base_mro, qualname, bool(options.frozen),
    )

    fnbuilder.insert_fns(clsname, namespace)

    # `__magic_init__` has been compiled by now. Give it the name people
    # will see -- it appears in error messages and tracebacks -- and
    # bind the public name to the same function if the class wants one.
    magic_init = namespace.get(_MAGIC("init"))
    if magic_init is not None and init_kwargs is not None:
        # When the class asked for no `__init__`, the only name this is
        # reachable by is the private one, so that is what it is called.
        magic_init.__name__ = init_name or _MAGIC("init")
        magic_init.__qualname__ = (
            f"{qualname or clsname}.{magic_init.__name__}"
        )
        # Before Python 3.10 the interpreter words "missing a required
        # argument" from the compiled code object rather than from the
        # function, so that has to be renamed too -- otherwise the error
        # names the private method on the older versions.
        magic_init.__code__ = magic_init.__code__.replace(
            co_name=magic_init.__name__
        )
        if init_name and init_name not in namespace:
            namespace[init_name] = magic_init
            generated[init_name] = "init"

    namespace[_GENERATED] = generated

    # Add attributes to class documentation
    # `python -OO` asks for docstrings to be dropped; a generated one is
    # no different, so honour the flag rather than reintroducing them.
    if options.doc and sys.flags.optimize < 2:
        docname = '__doc__' if options.doc is True else options.doc
        doc = namespace.get(docname, '') or ''
        doc = doc.rstrip("\n")
        doc = "\n\n".join([doc, _make_doc_class(fields)])
        namespace[docname] = doc

    return clsname, bases, namespace


class _FuncBuilder:
    # Also adapted from `dataclasses` (see the notice above the Builder
    # section, and NOTICE.md).

    def __init__(self, globals: dict) -> None:
        self.methods = {}  # name -> function
        self.globals = globals
        self.locals = {}
        self.overwrite_errors = {}
        self.unconditional_adds = {}

    def add_fn(
        self, name: str, args: tx.List[str], body: tx.List[str], *,
        doc: tx.Optional[tx.List[str]] = None,
        locals: tx.Optional[dict] = None,
        return_type: tx.Any = MISSING,
        overwrite_error: tx.Union[bool, str] = False,
        unconditional_add: bool = False,
        decorator: tx.Optional[str] = None
    ) -> None:
        if locals is not None:
            self.locals.update(locals)

        if overwrite_error:
            self.overwrite_errors[name] = overwrite_error

        if unconditional_add:
            self.unconditional_adds[name] = True

        if return_type is not MISSING:
            self.locals[_RETURN_TYPE(name)] = return_type
            return_annotation = f'->{_RETURN_TYPE(name)}'
        else:
            return_annotation = ''

        args = ','.join(args or [])
        body = '\n'.join(body or ['pass'])
        doc = '\n'.join(['"""'] + (doc or []) + ['"""'])

        src = "\n".join([
            f"def {name}({args}){return_annotation}:",
            indent(doc, " " * 4),
            indent(body, " " * 4),
        ])
        if decorator:
            src = f'{decorator}\n{src}'
        self.methods[name] = src

    def insert_fns(self, clsname: str, namespace: dict) -> None:
        # The source to all of the functions we're generating.
        fns_src = '\n'.join(self.methods.values())

        # The locals they use.
        local_vars = ','.join(self.locals.keys())

        # The names of all of the functions, used for the return value of the
        # outer function.  Need to handle the 0-tuple specially.
        if len(self.methods) == 0:
            return_names = "()"
        else:
            return_names  =f'({",".join(self.methods.keys())},)'

        # txt is the entire function we're going to execute, including the
        # bodies of the functions we're defining.  Here's a greatly simplified
        # version:
        # def __create_fn__():
        #  def __init__(self, x, y):
        #   self.x = x
        #   self.y = y
        #  @recursive_repr
        #  def __repr__(self):
        #   return f"cls(x={self.x!r},y={self.y!r})"
        # return __init__,__repr__

        txt = "\n".join([
            f"def __create_fn__({local_vars}):",
            indent(f"{fns_src}", " " * 4),
            indent(f"return {return_names}", " " * 4)
        ])
        temporary_namespace = {}
        exec(txt, self.globals, temporary_namespace)
        fns = temporary_namespace['__create_fn__'](**self.locals)

        # Now that we've generated the functions, assign them into cls.
        qualname = namespace.get("__qualname__", None)
        for name, fn in zip(self.methods, fns):
            fn.__qualname__ = f"{qualname}.{fn.__name__}"
            if self.unconditional_adds.get(name, False):
                namespace[name] = fn
            elif name not in namespace:
                namespace[name] = fn
            elif self.overwrite_errors.get(name, False):
                msg_extra = self.overwrite_errors[name]
                error_msg = (
                    f'Cannot overwrite attribute {name} in class {clsname}'
                )
                if msg_extra is not True:
                    error_msg = f'{error_msg} {msg_extra}'
                raise TypeError(error_msg)


def _hash_set_none(qualname: str, fields: dict) -> None:
    return None


def _hash_exception(qualname: str, fields: dict) -> tx.NoReturn:
    raise TypeError(
        f'Cannot overwrite attribute __hash__ in class {qualname}')


def _hash_add(qualname: str, fields: dict) -> int:
    # `compare` is a constructor alias for `eq` + `order`, not a slot of
    # its own -- reading it raised AttributeError for `hash=None`.
    fields = [
        f for f in fields.values()
        if (f.eq if f.hash is None else f.hash)
    ]

    def __hash__(self: Magic) -> int:
        # What is hashed is what `__eq__` compares: for each field,
        # whether it is holding a value and the value it holds. Two
        # objects that are equal hash together, a field holding nothing
        # included.
        values = tuple(_stored(self, f) for f in fields)
        return hash(values)

    __hash__.__qualname__ = f"{qualname}.__hash__"
    return __hash__


#
#                +-------------------------------------- unsafe_hash?
#                |      +------------------------------- eq?
#                |      |      +------------------------ frozen?
#                |      |      |      +----------------  has-explicit-hash?
#                |      |      |      |
#                |      |      |      |        +-------  action
#                |      |      |      |        |
#                v      v      v      v        v
_hash_action = {(False, False, False, False): None,
                (False, False, False, True ): None,
                (False, False, True,  False): None,
                (False, False, True,  True ): None,
                (False, True,  False, False): _hash_set_none,
                (False, True,  False, True ): None,
                (False, True,  True,  False): _hash_add,
                (False, True,  True,  True ): None,
                (True,  False, False, False): _hash_add,
                (True,  False, False, True ): _hash_exception,
                (True,  False, True,  False): _hash_add,
                (True,  False, True,  True ): _hash_exception,
                (True,  True,  False, False): _hash_add,
                (True,  True,  False, True ): _hash_exception,
                (True,  True,  True,  False): _hash_add,
                (True,  True,  True,  True ): _hash_exception,
                }


def _make_doc_class(fields: dict[str, Field]) -> str:
    attrdocs, classattrdocs = [], []
    for name, field in fields.items():
        if not field.var:
            attrdocs.append(_make_doc_elem(field, name))
        elif not field.init:
            classattrdocs.append(_make_doc_elem(field, name))
    attrdocs = "\n".join(attrdocs)
    classattrdocs = "\n".join(classattrdocs)
    if attrdocs:
        attrdocs = "Attributes\n----------\n" + attrdocs
    if classattrdocs:
        classattrdocs = "Class Attributes\n----------------\n" + classattrdocs
    return "\n\n".join([attrdocs, classattrdocs])


def _doc_type(type: tx.Any) -> str:
    """Spell a field's type the way the documentation should show it."""
    if isinstance(type, tx.ForwardRef):
        # A type that is not available where the class is written is
        # carried by name. The name is what a reader recognises, so the
        # documentation shows that rather than how it is carried.
        return type.__forward_arg__
    if isinstance(type, str):
        return type
    if isinstance(type, builtins.type):
        return type.__qualname__
    return repr(type)


def _make_doc_elem(field: Field, name: tx.Optional[str] = None) -> str:

    name = name or field.public_name

    default = field.default
    if field.factory:
        default = _HasFactory(field.factory)

    doctype = field.type
    if _get_origin(doctype) in (tx.Optional, tx.Annotated):
        doctype = tx.get_args(doctype)[0]
    elif _get_origin(doctype) in (tx.Union, _UnionType):
        # Simplify the representation of optional unions.
        if (
            len(tx.get_args(doctype)) == 2 and (
                None in tx.get_args(doctype) or
                type(None) in tx.get_args(doctype)
            )
        ):
            doctype = next(iter(
                arg
                for arg in tx.get_args(doctype)
                if arg not in (None, type(None))
            ))
        else:
            doctype = " | ".join([
                _doc_type(arg) for arg in tx.get_args(doctype)
            ])
    doctype = _doc_type(doctype)
    doc = (
        f"{name} : {doctype}, optional"
        if default is None else
        f"{name} : {doctype}, default={default!r}"
        if default is not MISSING else
        f"{name} : {doctype}"
    )
    if field.doc:
        doc += "\n" + indent(dedent(field.doc).strip(), " " * 4)
    return doc


def _make_init(
    fields: dict[str, Field],
    prepost: tx.Mapping[str, bool],
    clsname: str,
    pinned: tx.Container[str] = (),
) -> dict:

    # The body below is written in terms of these; each is carried
    # under a namespaced name because the parameters of the function
    # being generated are named after the fields, and a field is free to
    # be called `object`, `isinstance` or anything else.
    locals = {
        _OBJECT: object,
        _ISINSTANCE: isinstance,
        _EXCEPTION: Exception,
        _HAS_FACTORY: _HasFactory,
    }
    positional_onlys, args, kw_onlys = {}, {}, {}

    SELF = "self"
    # Fields that are stored on the instance without being a parameter:
    # they are assigned their own default. A pseudo-field (`ClassVar`,
    # `InitVar`) is not stored on the instance, and a field with neither
    # a default nor a factory has nothing to assign -- `__post_init__`
    # is where such a field gets its value.
    own_defaults = {}
    for name, field in fields.items():
        if field.positional and not field.kw:
            positional_onlys[name] = field
        elif field.positional and field.kw:
            args[name] = field
        elif field.kw:
            kw_onlys[name] = field
        else:
            # Neither by position nor by name: no parameter at all.
            if not field.var and (
                field.default is not MISSING or field.factory
            ):
                own_defaults[name] = field
            continue
        # The parameter is named after the field's *public* name, which
        # differs from the field name for an aliased or underscored
        # field. No two fields reach here under one public name: a class
        # whose fields collide that way is refused before any method is
        # built.
        if field.public_name == "self":
            SELF = _SELF

    # Pinning a field gives it a default, which can leave a parameter
    # without one behind it -- `MinorChord(mode="minor", root)`, which
    # Python's syntax has no way to write. Those parameters are given a
    # sentinel default instead, and the body turns a sentinel that is
    # still there back into the usual "missing a required argument". A
    # class that pins nothing is untouched: two hand-written fields in
    # that order are still refused, with the error that says so.
    required = set()
    if pinned:
        after_pin = False
        for field in list(positional_onlys.values()) + list(args.values()):
            if field.public_name in pinned:
                after_pin = True
            elif after_pin and field.default is MISSING and not field.factory:
                required.add(field.public_name)

    def _make_signature_elem(field: Field) -> tx.Tuple[str, str]:
        name = field.public_name
        default = field.default
        if field.factory:
            default = _HasFactory(field.factory)
        elif name in required:
            default = REQUIRED
        locals[_TYPE(name)] = field.type
        if default is MISSING:
            signature = f"{name}: {_TYPE(name)}"
        else:
            locals[_DEFAULT(name)] = default
            signature = f"{name}: {_TYPE(name)}={_DEFAULT(name)}"
        doc = _make_doc_elem(field, name)
        return signature, doc

    def _check_signature(signature: tx.List[str]) -> None:
        has_default = False
        for elem in signature:
            if elem == "*":
                break
            if elem == "/":
                continue
            if "=" in elem:
                has_default = True
            elif has_default:
                raise _BadSignature(
                    f"parameter without a default follows parameter with a "
                    f"default: {elem}"
                )

    signature, doc = [], ["Parameters", "----------"]
    for _name, field in positional_onlys.items():
        signature_elem, doc_elem = _make_signature_elem(field)
        signature.append(signature_elem)
        doc.append(doc_elem)
    if positional_onlys:
        signature.append("/")
    for _name, field in args.items():
        signature_elem, doc_elem = _make_signature_elem(field)
        signature.append(signature_elem)
        doc.append(doc_elem)
    if kw_onlys:
        signature.append("*")
    for _name, field in kw_onlys.items():
        signature_elem, doc_elem = _make_signature_elem(field)
        signature.append(signature_elem)
        doc.append(doc_elem)

    _check_signature(signature)

    parameters = list(positional_onlys.values())
    parameters += list(args.values())
    parameters += list(kw_onlys.values())

    def _make_prepost_call(func: str) -> str:
        # A hook that declares no parameter is called with nothing; one
        # that declares a parameter is handed every value `__init__` was
        # called with, keyed by the name the caller would have used.
        if not prepost[func]:
            return f"{SELF}.{func}()"
        locals[_ARGUMENTS] = Arguments
        values = ", ".join(
            f"{field.public_name!r}: {field.public_name}"
            for field in parameters
        )
        return f"{SELF}.{func}({_ARGUMENTS}({{{values}}}))"

    def _guarded(
        call: str,
        field: Field,
        action: str,
        value: tx.Optional[str] = None
    ) -> str:
        # A converter, a validator and a factory each say what went
        # wrong and nothing about where, so the class and the field are
        # put in front of the failure on its way out. The field is named
        # the way it is written in the class, which is also the way
        # `__setattr__` names it -- an aliased field's parameter goes by
        # another name, but the value it fills in is this one.
        #
        # Only the call itself is guarded: nothing else that goes wrong
        # nearby should be described as this field's fault.
        locals[_FIELD_ERROR] = field_error
        blamed = [repr(clsname), repr(field.name), repr(action), _ERROR]
        if value is not None:
            blamed.append(value)
        blamed = ", ".join(blamed)
        return dedent(f"""
        try:
            {call}
        except {_EXCEPTION} as {_ERROR}:
            {_FIELD_ERROR}({blamed})
        """)

    def _make_factory_elem(field: Field) -> str:
        # A defaulted-by-factory parameter arrives holding the factory
        # rather than a value. Every one of them is resolved before the
        # first hook runs, so that `__pre_init__` sees real values.
        if not field.factory:
            return ""
        name = field.public_name
        call = _guarded(f"{name} = {name}()", field, "build")
        return dedent(f"""
        if {_ISINSTANCE}({name}, {_HAS_FACTORY}):
        """) + indent(call, " " * 4)

    def _make_body_elem(field: Field) -> str:
        # The body reads the *parameter*, which is named after the
        # field's public name, and writes the *field*, which keeps its
        # own name.
        name = field.public_name
        body = ""
        if field.converter:
            locals[_CONVERTER(name)] = field.converter
            body += _guarded(
                f"{name} = {_CONVERTER(name)}({name})",
                field, "convert", name
            )
        if field.validator:
            locals[_VALIDATOR(name)] = field.validator
            body += _guarded(
                f"{name} = {_VALIDATOR(name)}({name})",
                field, "validate", name
            )
        if not field.var:
            # NOTE: we by pass the object's __setattr__ to avoid running
            # through conversion and validation multiple times.
            body += dedent(f"""
            {_OBJECT}.__setattr__({SELF}, {field.name!r}, {name})
            """)
        return body

    def _make_own_default_elem(field: Field) -> str:
        # The value comes from the field itself rather than from a
        # parameter, and goes through the same converter and validator a
        # parameter would. The locals are keyed by the field name, which
        # no parameter uses: a parameter is named after the field's
        # public name.
        default = _DEFAULT(field.name)
        locals[default] = field.factory if field.factory else field.default
        if not (field.factory or field.converter or field.validator):
            return dedent(f"""
            {_OBJECT}.__setattr__({SELF}, {field.name!r}, {default})
            """)
        # Building, converting and validating are taken one at a time,
        # so that whichever of them fails can say what it was doing.
        value = _VALUE(field.name)
        if field.factory:
            body = _guarded(f"{value} = {default}()", field, "build")
        else:
            body = dedent(f"""
            {value} = {default}
            """)
        if field.converter:
            locals[_CONVERTER(field.name)] = field.converter
            body += _guarded(
                f"{value} = {_CONVERTER(field.name)}({value})",
                field, "convert", value
            )
        if field.validator:
            locals[_VALIDATOR(field.name)] = field.validator
            body += _guarded(
                f"{value} = {_VALIDATOR(field.name)}({value})",
                field, "validate", value
            )
        return body + dedent(f"""
        {_OBJECT}.__setattr__({SELF}, {field.name!r}, {value})
        """)

    def _make_required_elem(name: str) -> str:
        # `REQUIRED` is the package's own sentinel and nothing else
        # hands it out, so a parameter still holding it was not passed.
        locals[_REQUIRED_ARG] = REQUIRED
        message = f"{clsname}() missing a required argument: {name!r}"
        return dedent(f"""
        if {name} is {_REQUIRED_ARG}:
            raise TypeError({message!r})
        """)

    body = [_make_required_elem(name) for name in sorted(required)]
    body += [_make_factory_elem(field) for field in parameters]
    if _PRE_INIT_NAME in prepost:
        body.append(_make_prepost_call(_PRE_INIT_NAME))
    body += [_make_body_elem(field) for field in parameters]
    body += [_make_own_default_elem(field) for field in own_defaults.values()]
    if _POST_INIT_NAME in prepost:
        body.append(_make_prepost_call(_POST_INIT_NAME))

    return {
        "args": [SELF] + signature,
        "body": body,
        "doc": doc,
        "locals": locals,
        "return_type": None,
    }


def _make_repr(qualname: str, fields: dict[str, Field]) -> tx.Callable:
    """Build `__repr__`, over the fields that are shown.

    A field is shown while it is holding a value, so which fields an
    instance shows is a question about that instance rather than about
    its class. A field holds nothing when the constructor does not take
    it and it has no default -- one like that is only ever set by hand
    -- and a field can also ask to be left out for as long as its value
    is `None`.
    """

    def __repr__(self: Magic) -> str:
        params = []
        for field in fields.values():
            has_value, value = _stored(self, field)
            if has_value and field.repr(value):
                params.append(f"{field.public_name}={value!r}")
        params = ", ".join(params)
        return f"{self.__class__.__name__}({params})"

    __repr__.__qualname__ = f"{qualname}.__repr__"
    return __repr__


def _matching(
    this: tx.Tuple[bool, tx.Any], that: tx.Tuple[bool, tx.Any]
) -> tx.Any:
    """Whether two fields hold the same thing, or neither holds one.

    Both halves of what `_stored` reports are compared, not just the
    value. Two objects that differ in *which* of their fields have been
    given a value are different objects, even where the values they do
    have match -- otherwise `a == b` would be true while reading `a.x`
    raises and reading `b.x` does not.
    """
    (this_has_value, this_value), (that_has_value, that_value) = this, that
    if this_has_value != that_has_value:
        return False
    return not this_has_value or this_value == that_value


def _make_eq(qualname: str, fields: dict[str, Field]) -> tx.Callable:

    def __eq__(self: Magic, other: tx.Any) -> bool:
        if self is other:
            return True
        if other.__class__ is self.__class__:
            return all(
                _matching(_stored(self, field), _stored(other, field))
                for field in fields.values()
                if field.eq
            )
        return NotImplemented

    __eq__.__qualname__ = f"{qualname}.__eq__"
    return __eq__


def _make_order(
    qualname: str, fields: dict[str, Field], slot: str
) -> tx.Callable:
    # Build one of the four comparisons -- `slot` is "lt", "le", "gt" or
    # "ge". All four compare the same thing: the values of the fields
    # that take part in the ordering, as a tuple.
    name, compare = _ORDER_METHODS[slot]

    def ordered_values(obj: Magic) -> tx.Tuple:
        """The values being compared, in field order.

        A field holding no value stops the comparison, with a message
        naming it. Skipping it would move every field after it up a
        position, so one position would stand for a different field
        from one object to the next and the answer would mean nothing.
        """
        values = []
        for field in fields.values():
            if not field.order:
                continue
            has_value, value = _stored(obj, field)
            if not has_value:
                raise AttributeError(
                    f"{type(obj).__name__}.{field.name} has never been "
                    f"given a value, so these two cannot be ordered: a "
                    f"comparison reads every field that takes part in the "
                    f"ordering, and this one has nothing to read. Give the "
                    f"field a default, set it in __post_init__, or leave "
                    f"it out of the ordering with NoOrder."
                )
            values.append(value)
        return tuple(values)

    def method(self: Magic, other: tx.Any) -> tx.Any:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return compare(ordered_values(self), ordered_values(other))

    method.__name__ = name
    method.__qualname__ = f"{qualname}.{name}"
    return method


def _make_assign(cls: type) -> type:

    # Bind the `__class__` closure cell so that a zero-arg super() would
    # resolve to `cls` inside the generated methods below. Intentionally
    # retained to preserve behavior; must not be removed.
    __class__ = cls  # noqa: F841
    fields = getattr(cls, _FIELDS, {})
    fields = {name: field for name, field in fields.items() if not field.var}

    # We are calling object methods instead of super(), because
    # super() falls back to inherited magic methods, which we don't want.

    def __delattr__(self: Magic, name: str) -> None:
        field = fields.get(name)
        if field:
            if getattr(field, 'frozen', False):
                raise AttributeError(f"Cannot delete frozen field {name!r}")
        elif getattr(type(self), _OPTIONS).frozen:
            raise AttributeError(
                f"Cannot delete attribute {name!r} on frozen class"
            )
        object.__delattr__(self, name)

    def __setattr__(self: Magic, name: str, value: tx.Any) -> None:
        field = fields.get(name)
        if field and not field.var:
            if field.frozen:
                raise AttributeError(f"Cannot set frozen field {name!r}")
            # A converter and a validator say what went wrong and
            # nothing about where, so the class and the field are put in
            # front of the failure on its way out.
            if field.converter:
                try:
                    value = field.converter(value)
                except Exception as error:
                    field_error(
                        type(self).__name__, name, "convert", error, value
                    )
            if field.validator:
                try:
                    value = field.validator(value)
                except Exception as error:
                    field_error(
                        type(self).__name__, name, "validate", error, value
                    )
        elif getattr(type(self), _OPTIONS).frozen:
            raise AttributeError(
                f"Cannot set attribute {name!r} on frozen class"
            )
        object.__setattr__(self, name, value)

    __delattr__.__qualname__ = f"{cls.__qualname__}.__delattr__"
    __setattr__.__qualname__ = f"{cls.__qualname__}.__setattr__"
    return __delattr__, __setattr__


def _make_state(
    qualname: str, slot_names: tx.Tuple[str, ...]
) -> tx.Tuple[tx.Callable, tx.Callable]:
    """
    Build the pair `pickle` and `copy` use to save and restore an
    object.

    What is saved is everything an object is really carrying: its
    attribute dictionary, and whichever of its slots have been given a
    value. Fields are not singled out, so an attribute that was set on
    the object without ever being declared survives a copy like any
    other.

    The saved value is a pair, `(attributes, slots)`, either half of
    which is `None` when there is nothing of that kind to save. This is
    the shape Python itself uses from 3.11 on for a class that does not
    say otherwise -- written out here because the versions before that
    have no method to borrow it from.
    """

    def __getstate__(self: Magic) -> tx.Tuple:
        attributes = getattr(self, "__dict__", None)
        slots = {}
        for name in slot_names:
            try:
                slots[name] = getattr(self, name)
            except AttributeError:
                # A slot that was never given a value stays empty on
                # the copy too.
                pass
        return (dict(attributes) if attributes else None, slots or None)

    def __setstate__(self: Magic, state: tx.Tuple) -> None:
        attributes, slots = state
        if attributes:
            self.__dict__.update(attributes)
        for name, value in (slots or {}).items():
            # Straight through to the object, since assigning the usual
            # way is what a frozen class refuses.
            object.__setattr__(self, name, value)

    __getstate__.__qualname__ = f"{qualname}.__getstate__"
    __setstate__.__qualname__ = f"{qualname}.__setstate__"
    return __getstate__, __setstate__


def _get_slots(cls: type) -> tx.Iterator[str]:
    slots = cls.__dict__.get('__slots__')
    if slots is None:
        # `__dictoffset__` and `__weakrefoffset__` can tell us whether
        # the base type has dict/weakref slots, in a way that works correctly
        # for both Python classes and C extension types. Extension types
        # don't use `__slots__` for slot creation
        if getattr(cls, '__weakrefoffset__', -1) != 0:
            yield '__weakref__'
        if getattr(cls, '__dictoffset__', -1) != 0:
            yield '__dict__'
    elif isinstance(slots, str):
        yield slots
    elif not hasattr(slots, '__next__'):
        # Slots may be any iterable, but we cannot handle an iterator
        # because it will already be (partially) consumed.
        yield from slots
    else:
        raise TypeError(f"Slots of '{cls.__name__}' cannot be determined")


def _make_slots(
    ancestors: tx.Sequence[type],
    fields: dict[str, Field],
    weakref_slot: bool = False,
) -> tx.Union[tuple[str, ...], dict[str, tx.Optional[str]]]:
    inherited_slots = set(
        slot
        for base in ancestors
        for slot in _get_slots(base)
    )

    slots, has_doc = {}, False
    for field in fields.values():
        if field.name in inherited_slots:
            continue
        slots[field.name] = field.doc
        if field.doc:
            has_doc = True

    if weakref_slot and '__weakref__' not in inherited_slots:
        slots['__weakref__'] = None

    if not has_doc:
        slots = tuple(slots)

    return slots


def _make_mapping(
    qualname: str, fields: dict[str, Field]
) -> tx.Mapping[str, tx.Callable]:
    """The dict-like methods, over the fields that carry a key.

    A key is there while the field behind it is holding a value, so
    which keys an instance has is a question about that instance rather
    than about its class. A field holds nothing when the constructor
    does not take it and it has no default -- one like that is only ever
    set by hand -- and a field can also ask to be left out for as long
    as its value is `None`.
    """

    def _is_key(self: Magic, field: Field) -> bool:
        """Whether a field is one of the keys as things stand."""
        has_value, value = _stored(self, field)
        return has_value and bool(field.key(value))

    def _value(self: Magic, key: str, field: Field) -> tx.Any:
        """The value behind a key, or a `KeyError` saying why there is none.

        A field holding nothing gets a written message: it is a real
        field of a usable object, so "no such key" on its own reads as
        if the name had been misspelt.
        """
        has_value, value = _stored(self, field)
        if not has_value:
            raise KeyError(
                f"{type(self).__name__}.{field.name} has no value, so "
                f"{key!r} is not one of the keys. Give the field a "
                f"default, or set it in __post_init__."
            )
        if not field.key(value):
            raise KeyError(key)
        return value

    def __getitem__(self: Magic, key: str) -> tx.Any:
        """The value behind a key.

        Raises `KeyError` if the class has no such key, or if the field
        behind it is holding no value.
        """
        field = fields.get(key)
        if field is None:
            raise KeyError(key)
        return _value(self, key, field)

    def __setitem__(self: Magic, key: str, value: tx.Any) -> None:
        """Give a key its value, adding it if it had none."""
        field = fields.get(key)
        if field is None:
            raise KeyError(key)
        setattr(self, field.name, value)

    def __delitem__(self: Magic, key: str) -> None:
        """Take a key's value away, so the key goes with it."""
        field = fields.get(key)
        if field is None:
            raise KeyError(key)
        # Turn down a key that is not there before touching anything.
        _value(self, key, field)
        # A default sits on the class itself, where deleting cannot
        # reach it: the field would go straight back to that value and
        # the key would still be there afterwards. Under `slots` the
        # class carries a slot rather than a value, and the field is
        # left holding nothing, which is what deleting a key means.
        standing_by = getattr(type(self), field.name, MISSING)
        if standing_by is not MISSING and not isinstance(
            standing_by, MemberDescriptorType
        ):
            raise TypeError(
                f"{type(self).__name__}.{field.name} has a default, so "
                f"deleting {key!r} would only put the default back and "
                f"leave the key where it is. Give it another value "
                f"instead."
            )
        delattr(self, field.name)

    def __iter__(self: Magic) -> tx.Iterator[str]:
        """The keys that have a value, in field order."""
        for key, field in fields.items():
            if _is_key(self, field):
                yield key

    def __len__(self: Magic) -> int:
        """How many keys have a value.

        Only the fields holding a value are counted, so two instances of
        the same class can be of different lengths, and one instance's
        length can change as it is filled in.
        """
        return sum(_is_key(self, field) for field in fields.values())

    __getitem__.__qualname__ = f"{qualname}.__getitem__"
    __setitem__.__qualname__ = f"{qualname}.__setitem__"
    __delitem__.__qualname__ = f"{qualname}.__delitem__"
    __iter__.__qualname__ = f"{qualname}.__iter__"
    __len__.__qualname__ = f"{qualname}.__len__"
    return {
        "__getitem__": __getitem__,
        "__setitem__": __setitem__,
        "__delitem__": __delitem__,
        "__iter__": __iter__,
        "__len__": __len__,
    }


# ----------------------------------------------------------------------
# Base
# ----------------------------------------------------------------------
# MetaMagic derives from ABCMeta so that derivatives of Magic can
# derive from ABCs (e.g. Mapping).


class MetaMagic(ABCMeta):
    """
    Examples
    --------
    ```python
    # Functional API
    MetaMagic(name, bases, namespace, **options) -> type: ...

    # Class-based API
    class Magic(*bases, metaclass=MetaMagic, **options):
        ...

    # Decorator API
    @magic(**options)
    class MyStruct:
        ...
    ```

    Parameters
    ----------
    name : str
        The name of the class being defined.
    bases : tuple[type, ...]
        The base classes of the class being defined.
    namespace : dict
        The namespace of the class being defined.

    Other Parameters
    ----------------
    init : bool | str, default=True
        Generate `__init__` method.
    repr : bool | str, default=True
        Generate `__repr__` method. A field is shown while it is
        holding a value, so a field the constructor does not take, with
        no default, is left out until something sets it.
    eq : bool | str, default=True
        Generate `__eq__` method. Two objects are equal when the same
        fields are holding values and those values match: one that has
        been given a value is never equal to one that is still without.
    order : bool | str, default=False
        Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods.
        Given a name, generate the `<` comparison under that name; the
        class is then left with none of the four comparison operators,
        including any it would otherwise inherit. A field holding no
        value stops the comparison and says so, since an order over
        part of an object is not an order over the object.
    hash : bool | str, default=None
        Generate `__hash__` method.
        If `None`, decide automatically.
    unsafe_hash : bool, default=False
        Always generate `__hash__` method.
    frozen : bool, default=False
        Disable `__setattr__` and `__delattr__`.
    match_args : bool | str, default=False
        Generate `__match_args__` for pattern matching.
    kw_only : bool, default=False
        Make all fields keyword-only by default.
    positional_only : bool, default=False
        Make all fields positional-only by default.
    slots : bool, default=False
        Generate `__slots__` and remove `__dict__`.
    weakref_slot : bool, default=False
        Generate a weakref slot in `__slots__`.
    factory : bool, default=False
        Use field type as factory if none is provided.
    mutable_default : {"factory", "raise", "allow"}, default="factory"
        What to do with a mutable default such as `x: list = []`.
        "factory" gives each instance its own copy, "raise" refuses the
        class, and "allow" shares one object between instances.
    convert : bool, default=False
        Use field type as converter if none is provided.
    validate : bool, default=False
        Use field type as validator if none is provided.
    unresolved_hints : str, default="warn"
        What to do when a field is annotated with a type that is still
        not defined the first time the field needs it. "warn" says so
        once and carries on without converting or validating, "raise"
        turns it into an error, and "ignore" says nothing. A default
        value that cannot be built raises whichever is chosen, since
        there is no value to hand back.
    mapping : bool, default=False
        Implement the `Mapping` protocol. A subclass cannot turn it off
        again. Only a field that is holding a value is a key, so which
        keys an instance has is a question about that instance: the
        length can differ between two instances of one class, and can
        change over an instance's life.
    override : bool | str | list, default=False
        Decide the settings of an inherited field again from this
        class. A field is resolved against the settings of the class
        that declares it and keeps those answers, so by default
        `frozen=False` on a subclass only reaches the fields that
        subclass declares itself; `override=True` applies this class's
        settings to the fields it inherits as well. What a field asked
        for in its own annotation always wins, whichever way this is
        set. Give the name of a setting, or a list of names, to decide
        only those again: frozen, kw_only, positional_only, convert,
        validate, factory and repr are the ones a field takes from its
        class.
    polymorphic : bool | str, default=False
        Build one of this class's subclasses instead of this class,
        chosen from the arguments it was given. A subclass says which
        arguments it stands for with `on=` on its own class statement.
        With "strict", a call matching none of them is refused rather
        than building this class.
    pin_discriminant : {"pin", "classvar", "keep"}, default="pin"
        What a subclass does with a field it matches on exactly. "pin"
        gives the field that value as its default, so it still shows in
        the repr and survives a round trip; "classvar" makes it a class
        attribute that is not stored per instance, still accepted by the
        constructor and discarded; "keep" leaves the field alone.
    reverse : bool, default=False
        Use the reverse MRO order to determine field order.
        This only affects the relative order of the fields of one class
        with respect to the fields of its base classes.
    doc : bool | str, default=True
        Add field documentation to class docstring.

    Returns
    -------
    cls : type
        The class being defined.
    """

    def __new__(
        metacls,
        name: str,
        bases: tx.Tuple[type, ...],
        namespace: tx.Dict[str, tx.Any],
        **kwargs,
    ) -> type:
        name, bases, namespace = __pre_new__(
            metacls, name, bases, namespace, **kwargs
        )
        cls = super().__new__(metacls, name, bases, namespace)
        cls = __post_new__(cls)
        return cls

    @property
    def __signature__(cls) -> Signature:
        # `inspect.signature(SomeClass)` reads the metaclass `__call__`
        # when there is one, and would report `(*args, **kwargs)` for
        # every Magic class. What a reader is asking for is how the
        # class is built, so answer with the constructor's own
        # signature, without the `self` it is written with.
        found = signature(cls.__init__)
        parameters = list(found.parameters.values())
        return found.replace(parameters=parameters[1:])

    def __call__(cls, *args, **kwargs) -> tx.Any:
        # A class no subclass has registered with has nothing here, so
        # the ordinary case pays one failed dictionary lookup. The
        # lookup is a direct one: a subclass answers for the subclasses
        # registered with *it*, and never for its parent's.
        found = cls.__dict__.get(_POLYMORPHS)
        if found is None:
            return super().__call__(*args, **kwargs)
        if found.invariant is not None:
            _check_invariant(cls, found, args, kwargs)
        if not found.entries:
            return super().__call__(*args, **kwargs)
        target = _select_polymorph(cls, found, args, kwargs)
        if target is None:
            return super().__call__(*args, **kwargs)
        # The subclass is built the same way it would be if it had been
        # named directly, so a subclass of *it* gets its turn too.
        return target(*args, **kwargs)

    def register_polymorph(
        cls,
        target: type,
        on: tx.Optional[tx.Mapping[str, tx.Any]] = None,
        priority: int = 0,
        **constraints: tx.Any,
    ) -> type:
        """
        Build `target` instead of this class, for these argument values.

        This is the same thing as `class Sub(Base, on={...})`, said
        after the fact -- for a class you did not write, or one whose
        constraints are only known at run time. Registering later only
        affects what is built later; instances that already exist are
        untouched.

        Parameters
        ----------
        target : type
            The subclass to build. It must be a subclass of this class,
            and not this class itself.
        on : dict, optional
            What `target` stands for: field names against the values
            they must take. The same shapes as the `on=` class keyword.
        priority : int, default=0
            Which subclass wins when two match equally well. Higher
            wins, and it is looked at before anything else.
        **constraints
            A friendlier spelling of `on`, for the usual case:
            `Chord.register_polymorph(Diminished, mode="diminished")`.
            Use `on=` for a field named `on`, `target` or `priority`.

        Returns
        -------
        target : type
            What was registered, so this can be used as a decorator.
        """
        options = getattr(cls, _OPTIONS, None)
        if options is None or not options.polymorphic:
            raise TypeError(
                f"{cls.__name__} does not build its subclasses, so nothing "
                f"can be registered with it. Add polymorphic=True to it -- "
                f"`class {cls.__name__}(Magic, polymorphic=True)`."
            )
        wanted = dict(on or {})
        wanted.update(constraints)
        specs = _specifications(cls, getattr(target, "__name__", target),
                                wanted)
        _register_polymorph(
            cls, target, specs, priority, options.polymorphic == "strict"
        )
        return target


class Magic(metaclass=MetaMagic):
    """
    Base class for data structures.

    Examples
    --------
    ```python
    class Point(Magic, frozen=True):
        x: float
        y: float
    ```

    Parameters
    ----------
    init : bool | str, default=True
        Generate `__init__` method.
    repr : bool | str, default=True
        Generate `__repr__` method. A field is shown while it is
        holding a value, so a field the constructor does not take, with
        no default, is left out until something sets it.
    eq : bool | str, default=True
        Generate `__eq__` method. Two objects are equal when the same
        fields are holding values and those values match: one that has
        been given a value is never equal to one that is still without.
    order : bool | str, default=False
        Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods.
        Given a name, generate the `<` comparison under that name; the
        class is then left with none of the four comparison operators,
        including any it would otherwise inherit. A field holding no
        value stops the comparison and says so, since an order over
        part of an object is not an order over the object.
    hash : bool | str, default=None
        Generate `__hash__` method.
        If `None`, decide automatically.
    unsafe_hash : bool, default=False
        Always generate `__hash__` method.
    frozen : bool, default=False
        Disable `__setattr__` and `__delattr__`.
    match_args : bool | str, default=False
        Generate `__match_args__` for pattern matching.
    kw_only : bool, default=False
        Make all fields keyword-only by default.
    positional_only : bool, default=False
        Make all fields positional-only by default.
    slots : bool, default=False
        Generate `__slots__` and remove `__dict__`.
    weakref_slot : bool, default=False
        Generate a weakref slot in `__slots__`.
    factory : bool, default=False
        Use field type as factory if none is provided.
    mutable_default : {"factory", "raise", "allow"}, default="factory"
        What to do with a mutable default such as `x: list = []`.
        "factory" gives each instance its own copy, "raise" refuses the
        class, and "allow" shares one object between instances.
    convert : bool, default=False
        Use field type as converter if none is provided.
    validate : bool, default=False
        Use field type as validator if none is provided.
    unresolved_hints : str, default="warn"
        What to do when a field is annotated with a type that is still
        not defined the first time the field needs it. "warn" says so
        once and carries on without converting or validating, "raise"
        turns it into an error, and "ignore" says nothing. A default
        value that cannot be built raises whichever is chosen, since
        there is no value to hand back.
    mapping : bool, default=False
        Implement the `Mapping` protocol. A subclass cannot turn it off
        again. Only a field that is holding a value is a key, so which
        keys an instance has is a question about that instance: the
        length can differ between two instances of one class, and can
        change over an instance's life.
    override : bool | str | list, default=False
        Decide the settings of an inherited field again from this
        class. A field is resolved against the settings of the class
        that declares it and keeps those answers, so by default
        `frozen=False` on a subclass only reaches the fields that
        subclass declares itself; `override=True` applies this class's
        settings to the fields it inherits as well. What a field asked
        for in its own annotation always wins, whichever way this is
        set. Give the name of a setting, or a list of names, to decide
        only those again: frozen, kw_only, positional_only, convert,
        validate, factory and repr are the ones a field takes from its
        class.
    polymorphic : bool | str, default=False
        Build one of this class's subclasses instead of this class,
        chosen from the arguments it was given. A subclass says which
        arguments it stands for with `on=` on its own class statement.
        With "strict", a call matching none of them is refused rather
        than building this class.
    pin_discriminant : {"pin", "classvar", "keep"}, default="pin"
        What a subclass does with a field it matches on exactly. "pin"
        gives the field that value as its default, so it still shows in
        the repr and survives a round trip; "classvar" makes it a class
        attribute that is not stored per instance, still accepted by the
        constructor and discarded; "keep" leaves the field alone.
    reverse : bool, default=False
        Use the reverse MRO order to determine field order.
        This only affects the relative order of the fields of one class
        with respect to the fields of its base classes.
    doc : bool | str, default=True
        Add field documentation to class docstring.
    """

    # Set __slots__ so that inheriting classes can have slot=True
    __slots__ = ()


# ----------------------------------------------------------------------
# Decorator
# ----------------------------------------------------------------------


@tx.overload
def magic(**kwargs) -> tx.Callable[[type], type]: ...


@tx.overload
def magic(cls: type, **kwargs) -> type: ...


def magic(cls: tx.Optional[type] = None, **kwargs):
    """
    Decorator for defining a Magic class.
    See `Magic` for parameters and examples.
    """
    if cls is None:
        return partial(magic, **kwargs)
    return rebuild_cls(cls, partial(MetaMagic, **kwargs))


# ----------------------------------------------------------------------
# External methods
# ----------------------------------------------------------------------
