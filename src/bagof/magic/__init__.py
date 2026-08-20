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
    Generate `__lt__` method
unsafe_hash : bool, default=False
    Always generate `__hash__` method
frozen : bool, default=False
    Disable `__setattr__` and `__delattr__`
match_args : bool | str, default=False
    Generate `__match_args__` for pattern matching
kw_only : bool, default=False
    Make all fields keyword-only by default
slots : bool, default=False
    Generate `__slots__` and remove `__dict__`
weakref_slot : bool, default=False
    Generate a weakref slot in `__slots__`
factory : bool, default=False
    Use field type as factory if none is provided
convert : bool, default=False
    Use field type as converter if none is provided
validate : bool, default=False
    Use field type as validator if none is provided

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
import sys
from abc import ABCMeta
from collections import abc as _abc
from functools import partial
from textwrap import dedent, indent

# externals
import typing_extensions as tx
from bagof.core.magic import UnionType as _UnionType

# internals
from .constants import (
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
from .fields import *  # noqa: F401, F403
from .fields import Field
from .fields import __all__ as __all_fields__
from .options import *  # noqa: F401, F403
from .options import Options
from .options import __all__ as __all_options__
from .utils import _get_origin, rebuild_cls

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


def _add_fields(
    fields: dict[str, Field],
    new_fields: tx.Iterable[Field],
    replace: bool = False,
    reverse: bool = False,
    inherit: tx.List[str] = ("doc",),
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
    if replace and not reverse:
        if inherit:
            for new_field in new_fields:
                if new_field.name in fields:
                    old_field = fields[new_field.name]
                    for attr in inherit:
                        if getattr(new_field, attr, MISSING) is MISSING:
                            continue
                        setattr(new_field, attr, getattr(old_field, attr))
                fields[new_field.name] = new_field
        else:
            fields.update({f.name: f for f in new_fields})

    elif replace and reverse:
        prev_fields = fields.copy()
        fields.clear()
        fields.update({f.name: f for f in new_fields})
        for name, field in prev_fields.items():
            fields.setdefault(name, field)
            for attr in inherit:
                if getattr(fields[name], attr, MISSING) is MISSING:
                    setattr(fields[name], attr, getattr(field, attr))

    elif not replace and not reverse:
        for f in new_fields:
            fields.setdefault(f.name, f)
            for attr in inherit:
                if getattr(fields[f.name], attr, MISSING) is MISSING:
                    setattr(fields[f.name], attr, getattr(f, attr))

    elif not replace and reverse:
        prev_fields = fields.copy()
        fields.clear()
        fields.update(prev_fields)
        for f in new_fields:
            fields.setdefault(f.name, f)
            for attr in inherit:
                if getattr(fields[f.name], attr, MISSING) is MISSING:
                    setattr(fields[f.name], attr, getattr(f, attr))


def _namespace_annotations(namespace: dict) -> dict:
    # The annotations declared in a class body, read from the namespace the
    # metaclass receives -- before the class object exists.
    #
    # Up to Python 3.13 the namespace holds ``__annotations__`` directly.
    # From 3.14 (PEP 649/749) annotations are lazy: the namespace instead
    # carries an ``__annotate__`` function, retrieved via ``annotationlib``.
    if "__annotations__" in namespace:
        # Python <= 3.13: coverage runs on 3.14+, where annotations are lazy
        # and the namespace never carries __annotations__, so this is dead.
        return namespace["__annotations__"]  # pragma: no cover
    try:
        import annotationlib
    except ImportError:  # pragma: no cover  -- Python < 3.14
        return {}
    annotate = annotationlib.get_annotate_from_class_namespace(namespace)
    if annotate is None:
        return {}
    # FORWARDREF never raises on not-yet-defined names (they become
    # ``ForwardRef``), which keeps class creation robust.
    return annotationlib.call_annotate_function(
        annotate, annotationlib.Format.FORWARDREF
    )


def _no_order(self: Magic, other: tx.Any) -> tx.Any:
    """Stand-in for a generated ordering a derived class turned off."""
    return NotImplemented


#: What a turned-off option leaves in place of a generated method.
#: `object` has no `__lt__`, so ordering falls back to a
#: `NotImplemented` -- which lets Python raise its usual "not supported
#: between instances" rather than "NoneType is not callable".
_NEUTRAL = {
    "repr": object.__repr__,
    "eq": object.__eq__,
    "lt": _no_order,
    "hash": None,
}


def _written(cls: type) -> dict:
    """The `{name: slot}` this package bound on `cls` itself.

    Recorded per class rather than marked on the function, because a
    generated slot may hold something unmarkable -- `__hash__ = None`,
    or a slot wrapper like `object.__eq__` left by a turned-off option.
    """
    return cls.__dict__.get(_GENERATED) or {}


def _defines(mro: tx.Tuple[type, ...], name: str) -> tx.Any:
    """The first class in `mro` that defines `name`, or `None`."""
    for base in mro:
        if name in base.__dict__:
            return base
    return None


def _generated_names(mro: tx.Tuple[type, ...], slot: str) -> tx.List[str]:
    """Names in the bases whose *resolved* method for `slot` is ours.

    More than one, because a base may have bound it under a name of its
    own (`eq="__same__"`) while an ancestor still holds the dunder. A
    name is only included when the class that actually provides it --
    the first in the MRO, which is the one Python will use -- is the
    class that recorded it, so a hand-written method nearer the front
    shadows a generated one behind it and is left alone.
    """
    names = []
    for base in mro:
        for name, base_slot in _written(base).items():
            if base_slot != slot or name in names:
                continue
            owner = _defines(mro, name)
            if owner is not None and name in _written(owner):
                names.append(name)
    return names


def _install(
    namespace: dict,
    written: dict,
    mro: tx.Tuple[type, ...],
    slot: str,
    public: str,
    fn: tx.Any,
    enabled: bool,
) -> bool:
    """
    Bind a generated method, and report whether the public name is ours.

    The private name is always bound, so a hand-written method can
    delegate to the generated one. The public name is bound only when
    the option asks for it -- and when it does not, every name in the
    bases holding a *generated* method for this slot is neutralised,
    because each was built for another class's fields and would
    otherwise answer in this one's place. A hand-written method, in
    this class or a base, is never touched.
    """
    private = _MAGIC(slot)
    if private in namespace:
        raise TypeError(
            f"{private!r} is generated; define {public!r} instead and call "
            f"{private!r} from it"
        )
    namespace[private] = fn

    if enabled:
        if public in namespace:
            return False
        namespace[public] = fn
        written[public] = slot
        return True

    ours = False
    for name in _generated_names(mro, slot):
        if name not in namespace:
            namespace[name] = _NEUTRAL[slot]
            written[name] = slot
            ours = ours or name == public
    return ours


def _install_hash(
    namespace: dict,
    written: dict,
    mro: tx.Tuple[type, ...],
    options: Options,
    qualname: str,
    real_fields: dict,
    has_explicit_hash: bool,
    eq_is_identity: bool,
) -> None:
    """
    Decide what `__hash__` should be, and bind it.

    The field-wise hash is always available privately. What lands on the
    public name is chosen here rather than left to inheritance, because
    writing `__eq__` into a class body makes Python drop `__hash__`
    unless one is given too -- so "leave it alone" is not an option once
    an `__eq__` has been installed.
    """
    namespace[_MAGIC("hash")] = _hash_add(qualname, real_fields)

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
    inherited = _generated_names(mro, "hash")

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
             and "__hash__" not in _written(base)),
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
            written[name] = "hash"


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
    mro = type(_DISCARD, bases, {}).__mro__
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
    cls_annotations = _namespace_annotations(namespace)

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

    # Check if pre and/or post init methods are defined in this class.
    prepost = []
    if _PRE_INIT_NAME in namespace:
        prepost += ["pre"]
    if _POST_INIT_NAME in namespace:
        prepost += ["post"]
    prepost = "+".join(prepost)

    # Every generated method is bound under a private name whatever the
    # options say, so a hand-written one can delegate to it:
    #     def __init__(self, raw): self.__magic_init__(int(raw))
    # The public name is bound only when the option asks for it.
    #
    # `written` records `{name: slot}` for everything bound here, so a
    # derived class can tell one of ours from a hand-written method even
    # when the value cannot carry a marker (`__hash__ = None`, or a slot
    # wrapper left by a turned-off option).
    written = {}
    init_name = (
        ("__init__" if options.init is True else options.init)
        if options.init else None
    )

    # Build __init__. The builder writes source, so binding the public
    # name has to wait until `insert_fns` has compiled it (below).
    try:
        init_kwargs = _make_init(fields, prepost)
    except (SyntaxError, TypeError):
        if init_name:
            raise
        # The class opted out of `__init__`, so the private one is only
        # a convenience: a field layout that cannot produce a signature
        # (a non-default after a default, two fields sharing a public
        # name) must not stop the class being built.
        init_kwargs = None
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

    if options.match_args:
        fnname = (
            options.match_args
            if isinstance(options.match_args, str)
            else "__match_args__"
        )
        namespace.setdefault(fnname, tuple(
            f.public_name for f in fields.values() if f.init and f.positional
        ))

    if options.frozen:
        getstate, setstate = _make_state(qualname, real_fields)
        namespace.setdefault("__getstate__", getstate)
        namespace.setdefault("__setstate__", setstate)

    if options.mapping:
        dict_fields = {f.public_key: f for f in fields.values() if f.key}
        for name, func in _make_mapping(qualname, dict_fields).items():
            namespace.setdefault(name, func)
        Mapping = _abc.Mapping if options.frozen else _abc.MutableMapping
        if not any(issubclass(base, Mapping) for base in bases):
            bases += (Mapping,)

    # The generated methods go in here, after `bases` is final: the
    # mapping option can add a base, and what an inherited method would
    # be has to be read from the MRO this class will really have.
    base_mro = type(_DISCARD, bases, {}).__mro__[1:]

    repr_fields = {name: f for name, f in fields.items() if f.repr}
    _install(
        namespace, written, base_mro, "repr",
        options.repr if isinstance(options.repr, str) else "__repr__",
        _make_repr(qualname, repr_fields), bool(options.repr),
    )

    eq_is_ours = _install(
        namespace, written, base_mro, "eq",
        options.eq if isinstance(options.eq, str) else "__eq__",
        _make_eq(qualname, real_fields), bool(options.eq),
    )

    _install(
        namespace, written, base_mro, "lt",
        options.order if isinstance(options.order, str) else "__lt__",
        _make_lt(qualname, real_fields), bool(options.order),
    )

    _install_hash(
        namespace, written, base_mro, options, qualname, real_fields,
        has_explicit_hash, eq_is_ours and not options.eq,
    )

    # It's an error to specify weakref_slot if slots is False.
    if options.weakref_slot and not options.slots:
        raise TypeError('weakref_slot is True but slots is False')
    if options.slots:
        if '__slots__' in namespace:
            raise TypeError(f'{clsname} already specifies __slots__')
        weakref_slot = options.weakref_slot
        namespace["__slots__"] = _make_slots(bases, real_fields, weakref_slot)

    fnbuilder.insert_fns(clsname, namespace)

    # `__magic_init__` is compiled by now; give it the name it will be
    # known by -- it shows up in every TypeError and traceback -- and
    # bind the public name to the same object when `init` asks for it.
    magic_init = namespace.get(_MAGIC("init"))
    if magic_init is not None and init_kwargs is not None:
        magic_init.__name__ = init_name or "__init__"
        magic_init.__qualname__ = f"{qualname}.{magic_init.__name__}"
        if init_name and init_name not in namespace:
            namespace[init_name] = magic_init
            written[init_name] = "init"

    namespace[_GENERATED] = written

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
    fields: dict[str, Field], prepost: str=""
) -> dict:

    locals = {"object": object, "_HasFactory": _HasFactory}
    positional_onlys, args, kw_onlys = {}, {}, {}

    SELF = "self"
    seen_params = {}
    for name, field in fields.items():
        if field.init and field.positional and not field.kw:
            positional_onlys[name] = field
        elif field.init and field.positional and field.kw:
            args[name] = field
        elif field.init and not field.positional and field.kw:
            kw_onlys[name] = field
        else:
            continue
        # The parameter is named after the field's *public* name, which
        # differs from the field name for an aliased or underscored
        # field. Two fields that reduce to the same parameter would
        # generate a signature with a duplicate argument.
        public = field.public_name
        if public in seen_params:
            raise TypeError(
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
                raise SyntaxError(f"parameter without a default follows "
                                  f"parameter with a default: {elem}")

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

    def _make_prepost_call(func: str) -> str:
        prepost_args = []
        for field in positional_onlys.values():
            if field.var:
                prepost_args.append(f"{field.public_name}")
        for field in args.values():
            if field.var:
                prepost_args.append(f"{field.public_name}")
        for field in kw_onlys.values():
            if field.var:
                name = field.public_name
                prepost_args.append(f"{name}={name}")
        prepost_args = ", ".join(prepost_args)
        return f"{SELF}.{func}({prepost_args})"

    def _make_body_elem(field: Field) -> str:
        # The body reads the *parameter*, which is named after the
        # field's public name, and writes the *field*, which keeps its
        # own name.
        name = field.public_name
        body = ""
        if field.factory:
            body += dedent(f"""
            if isinstance({name}, _HasFactory):
                {name} = {name}()
            """)
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

    body = []
    if "pre" in prepost:
        body.append(_make_prepost_call(_PRE_INIT_NAME))
    for field in positional_onlys.values():
        body.append(_make_body_elem(field))
    for field in args.values():
        body.append(_make_body_elem(field))
    for field in kw_onlys.values():
        body.append(_make_body_elem(field))
    if "post" in prepost:
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


def _make_lt(qualname: str, fields: dict[str, Field]) -> tx.Callable:

    def __lt__(self: Magic, other: tx.Any) -> bool:
        if other.__class__ is self.__class__:
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
            return this_value < other_value
        return NotImplemented

    __lt__.__qualname__ = f"{qualname}.__lt__"
    return __lt__


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


def _make_state(qualname: str, fields: dict[str, Field]) -> tx.Callable:

    def __getstate__(self: Magic) -> tx.Tuple:
        kept = [f for f in fields.values() if not f.var]
        return tuple(getattr(self, f.name) for f in kept)

    def __setstate__(self: Magic, state: tx.Tuple) -> None:
        kept = [f for f in fields.values() if not f.var]
        for field, value in zip(kept, state):
            # use setattr because dataclass may be frozen
            object.__setattr__(self, field.name, value)

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
    bases: tuple[type, ...],
    fields: dict[str, Field],
    weakref_slot: bool = False,
) -> tx.Union[tuple[str, ...], dict[str, tx.Optional[str]]]:
    mro = type(_DISCARD, bases, {}).__mro__[1:-1]
    inherited_slots = set(
        slot
        for base in mro
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


_DOC_OPTIONS = """
init : bool | str, default=True
    Generate `__init__` method.
repr : bool | str, default=True
    Generate `__repr__` method.
eq : bool | str, default=True
    Generate `__eq__` method.
order : bool | str, default=False
    Generate `__lt__` method.
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
convert : bool, default=False
    Use field type as converter if none is provided.
validate : bool, default=False
    Use field type as validator if none is provided.
mapping : bool, default=False
    Implement the `Mapping` protocol.
reverse : bool, default=False
    Use the reverse MRO order to determine field order.
    This only affects the relative order of the fields of one class
    with respect to the fields of its base classes.
doc : bool | str, default=True
    Add field documentation to class docstring.
""".strip()


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
        Generate `__lt__` method.
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
    convert : bool, default=False
        Use field type as converter if none is provided.
    validate : bool, default=False
        Use field type as validator if none is provided.
    mapping : bool, default=False
        Implement the `Mapping` protocol.
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
        Generate `__lt__` method.
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
    convert : bool, default=False
        Use field type as converter if none is provided.
    validate : bool, default=False
        Use field type as validator if none is provided.
    mapping : bool, default=False
        Implement the `Mapping` protocol.
    reverse : bool, default=False
        Use the reverse MRO order to determine field order.
        This only affects the relative order of the fields of one class
        with respect to the fields of its base classes.
    doc : bool | str, default=True
        Add field documentation to class docstring.
    """

    # Set __slots__ so that inheriting classes can have slot=True
    __slots__ = ()


# `python -OO` strips docstrings, so there may be nothing to format.
if MetaMagic.__doc__:
    MetaMagic.__doc__ = MetaMagic.__doc__.format(DOC_OPTIONS=_DOC_OPTIONS)
if Magic.__doc__:
    Magic.__doc__ = Magic.__doc__.format(DOC_OPTIONS=_DOC_OPTIONS)


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


def fields(cls: type) -> tx.Tuple[Field]:
    """
    Get the fields of a Magic class.

    Parameters
    ----------
    cls : type
        The class to get the fields of.

    Returns
    -------
    fields : tuple[Field]
        All concrete fields (that are not `ClassVar` or `InitVar`).
    """
    return tuple(
        field for field in getattr(cls, _FIELDS, {}).values()
        if not field.var
    )
