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
    Generate `__repr__` method
eq : bool | str, default=True
    Generate `__eq__` method
order : bool | str, default=False
    Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods
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
mapping : bool, default=False
    Implement the `Mapping` protocol; a subclass cannot turn it off
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
import builtins
import copy
import operator
import sys
from abc import ABCMeta
from collections import abc as _abc
from functools import partial
from inspect import Parameter, signature
from textwrap import dedent, indent

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
    _FIELDS,
    _GENERATED,
    _MAGIC,
    _OPTIONS,
    _POST_INIT_NAME,
    _PRE_INIT_NAME,
    _RETURN_TYPE,
    _SELF,
    _TYPE,
    _VALIDATOR,
    HIDE_IF_NONE,
    MISSING,
    SHOW_ATTR,
    _HasFactory,
)
from ._fields import *  # noqa: F401, F403
from ._fields import Field
from ._fields import __all__ as __all_fields__
from ._options import *  # noqa: F401, F403
from ._options import Options
from ._options import __all__ as __all_options__
from ._utils import _get_origin, rebuild_cls

__all__ += __all_arguments__
__all__ += __all_fields__
__all__ += __all_options__


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


class _ForwardRefScope(dict):
    # A scope in which a name that is bound nowhere evaluates to a
    # `ForwardRef` instead of raising `NameError`. Evaluating an
    # annotation in such a scope recovers the *shape* of the hint --
    # `ClassVar[...]`, `Annotated[...]`, and so the whole annotation
    # family -- even when the type it refers to does not exist yet.

    def __missing__(self, name: str) -> tx.ForwardRef:
        return tx.ForwardRef(name)


def _annotation_scope(namespace: dict, globals: dict) -> _ForwardRefScope:
    # The names an annotation written in this class body can refer to:
    # the builtins, then the defining module, then the class body itself
    # (each shadowing the one before, as Python resolves them).
    scope = _ForwardRefScope(vars(builtins))
    scope.update(globals)
    scope.update(namespace)
    return scope


def _evaluate_annotation(source: str, scope: _ForwardRefScope) -> tx.Any:
    # An annotation reaches us as text under `from __future__ import
    # annotations`, and as text whenever it is quoted. Read back the
    # object it describes, so the annotation family is seen at all.
    #
    # An unbound *name* becomes a `ForwardRef`, but an unbound name used
    # as anything more than a name does not survive: `Outer.Nested` asks
    # a `ForwardRef` for an attribute, `Missing(1)` calls one. Those, and
    # anything else that fails to evaluate, keep the string they came
    # from -- the field then carries the annotation exactly as written,
    # which is all that was ever available for it.
    try:
        return eval(source, {}, scope)
    except Exception:
        return source


def _namespace_annotations(namespace: dict, globals: dict) -> dict:
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
    return _resolve_string_annotations(annotations, namespace, globals)


def _resolve_string_annotations(
    annotations: dict, namespace: dict, globals: dict
) -> dict:
    # Annotations that are text -- every one of them under `from
    # __future__ import annotations`, and any single quoted one
    # otherwise -- are read back into the objects they name. Whatever
    # already arrived as an object is left alone, so on Python 3.14+,
    # where the runtime hands over `ForwardRef`s of its own, there is
    # nothing here to redo.
    if not any(isinstance(hint, str) for hint in annotations.values()):
        return annotations
    scope = _annotation_scope(namespace, globals)
    return {
        name: (
            _evaluate_annotation(hint, scope)
            if isinstance(hint, str) else hint
        )
        for name, hint in annotations.items()
    }


class _BadSignature(SyntaxError):
    """A field layout that cannot produce an `__init__` signature."""


class _DuplicateParameter(TypeError):
    """Two fields that would become the same `__init__` parameter."""


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
    field.factory = partial(copy.copy, default)
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
    for b in reversed(mro):
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
    cls_annotations = _namespace_annotations(namespace, globals)

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
        field.setdefault(options)

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

        # Use Key/Repr wrappers
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

        cls_fields.append(field)

    # Insert fields from this class, in correct order.
    _add_fields(fields, cls_fields, replace=True, reverse=options.reverse)

    # Do we have any Field members that don't also have annotations?
    for attr_name, value in namespace.items():
        if isinstance(value, Field) and attr_name not in cls_annotations:
            raise TypeError(
                f'{attr_name!r} is a field but has no type annotation'
            )

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
        init_kwargs = _make_init(fields, prepost)
    except (_BadSignature, _DuplicateParameter) as error:
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
        dict_fields = {f.public_key: f for f in fields.values() if f.key}
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
        tuple(
            f.public_name for f in fields.values() if f.init and f.positional
        ),
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
        values = tuple(getattr(self, f.name) for f in fields)
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
                arg.__qualname__
                if isinstance(arg, type) else
                repr(arg)
                for arg in tx.get_args(doctype)
            ])
    doctype = (
        doctype
        if isinstance(doctype, str) else
        doctype.__qualname__
        if isinstance(doctype, type) else
        repr(doctype)
    )
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
    fields: dict[str, Field], prepost: tx.Mapping[str, bool]
) -> dict:

    locals = {"object": object, "_HasFactory": _HasFactory}
    positional_onlys, args, kw_onlys = {}, {}, {}

    SELF = "self"
    seen_params = {}
    # Fields that are stored on the instance without being a parameter:
    # they are assigned their own default. A pseudo-field (`ClassVar`,
    # `InitVar`) is not stored on the instance, and a field with neither
    # a default nor a factory has nothing to assign -- `__post_init__`
    # is where such a field gets its value.
    own_defaults = {}
    for name, field in fields.items():
        if field.init and field.positional and not field.kw:
            positional_onlys[name] = field
        elif field.init and field.positional and field.kw:
            args[name] = field
        elif field.init and not field.positional and field.kw:
            kw_onlys[name] = field
        else:
            if not field.var and (
                field.default is not MISSING or field.factory
            ):
                own_defaults[name] = field
            continue
        # The parameter is named after the field's *public* name, which
        # differs from the field name for an aliased or underscored
        # field. Two fields that reduce to the same parameter would
        # generate a signature with a duplicate argument.
        public = field.public_name
        if public in seen_params:
            raise _DuplicateParameter(
                f"fields {seen_params[public]!r} and {name!r} both map to "
                f"the __init__ parameter {public!r}"
            )
        seen_params[public] = name
        if public == "self":
            SELF = _SELF

    def _make_signature_elem(field: Field) -> tx.Tuple[str, str]:
        name = field.public_name
        default = field.default
        if field.factory:
            default = _HasFactory(field.factory)
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

    def _make_factory_elem(field: Field) -> str:
        # A defaulted-by-factory parameter arrives holding the factory
        # rather than a value. Every one of them is resolved before the
        # first hook runs, so that `__pre_init__` sees real values.
        if not field.factory:
            return ""
        name = field.public_name
        return dedent(f"""
        if isinstance({name}, _HasFactory):
            {name} = {name}()
        """)

    def _make_body_elem(field: Field) -> str:
        # The body reads the *parameter*, which is named after the
        # field's public name, and writes the *field*, which keeps its
        # own name.
        name = field.public_name
        body = ""
        if field.converter:
            locals[_CONVERTER(name)] = field.converter
            body += dedent(f"""
            {name} = {_CONVERTER(name)}({name})
            """)
        if field.validator:
            locals[_VALIDATOR(name)] = field.validator
            body += dedent(f"""
            {name} = {_VALIDATOR(name)}({name})
            """)
        if not field.var:
            # NOTE: we by pass the object's __setattr__ to avoid running
            # through conversion and validation multiple times.
            body += dedent(f"""
            object.__setattr__({SELF}, {field.name!r}, {name})
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
        value = f"{default}()" if field.factory else default
        if field.converter:
            locals[_CONVERTER(field.name)] = field.converter
            value = f"{_CONVERTER(field.name)}({value})"
        if field.validator:
            locals[_VALIDATOR(field.name)] = field.validator
            value = f"{_VALIDATOR(field.name)}({value})"
        return dedent(f"""
        object.__setattr__({SELF}, {field.name!r}, {value})
        """)

    body = [_make_factory_elem(field) for field in parameters]
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

    def __repr__(self: Magic) -> str:
        params = [
            f"{field.public_name}={getattr(self, field.name)!r}"
            for field in fields.values()
            if field.repr(getattr(self, field.name))
        ]
        params = ", ".join(params)
        return f"{self.__class__.__name__}({params})"

    __repr__.__qualname__ = f"{qualname}.__repr__"
    return __repr__


def _make_eq(qualname: str, fields: dict[str, Field]) -> tx.Callable:

    def __eq__(self: Magic, other: tx.Any) -> bool:
        if self is other:
            return True
        if other.__class__ is self.__class__:
            return all(
                getattr(self, field.name) == getattr(other, field.name)
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

    def method(self: Magic, other: tx.Any) -> tx.Any:
        if other.__class__ is not self.__class__:
            return NotImplemented
        this_value = tuple(
            getattr(self, field.name)
            for field in fields.values()
            if field.order
        )
        other_value = tuple(
            getattr(other, field.name)
            for field in fields.values()
            if field.order
        )
        return compare(this_value, other_value)

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
            if field.converter:
                value = field.converter(value)
            if field.validator:
                value = field.validator(value)
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

    def __getitem__(self: Magic, key: str) -> tx.Any:
        field = fields.get(key)
        if field:
            value = getattr(self, field.name)
            if not field.key(value):
                raise KeyError(key)
            return value
        raise KeyError(key)

    def __setitem__(self: Magic, key: str, value: tx.Any) -> None:
        field = fields.get(key)
        if field:
            setattr(self, field.name, value)
        else:
            raise KeyError(key)

    def __delitem__(self: Magic, key: str) -> None:
        field = fields.get(key)
        if field:
            delattr(self, field.name)
        else:
            raise KeyError(key)

    def __iter__(self: Magic) -> tx.Iterator[str]:
        for key, field in fields.items():
            if field:
                if not field.key(getattr(self, field.name)):
                    continue
                yield key

    def __len__(self: Magic) -> int:
        return sum(
            field.key(getattr(self, field.name))
            for field in fields.values()
        )

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
        Generate `__repr__` method.
    eq : bool | str, default=True
        Generate `__eq__` method.
    order : bool | str, default=False
        Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods.
        Given a name, generate the `<` comparison under that name; the
        class is then left with none of the four comparison operators,
        including any it would otherwise inherit.
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
    mapping : bool, default=False
        Implement the `Mapping` protocol. A subclass cannot turn it off
        again.
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
        Generate `__repr__` method.
    eq : bool | str, default=True
        Generate `__eq__` method.
    order : bool | str, default=False
        Generate `__lt__`, `__le__`, `__gt__` and `__ge__` methods.
        Given a name, generate the `<` comparison under that name; the
        class is then left with none of the four comparison operators,
        including any it would otherwise inherit.
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
    mapping : bool, default=False
        Implement the `Mapping` protocol. A subclass cannot turn it off
        again.
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
