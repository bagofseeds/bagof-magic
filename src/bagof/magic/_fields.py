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
    "PIN",
    "CLASSVAR",
    "KEEP",
    "NARROW",
    "PIN_NARROW",
    "CLASSVAR_NARROW",
    "KEEP_NARROW",
]
import difflib
from functools import partial

import typing_extensions as tx

from ._aliases import (
    alias_option,
    merge_alias,
    merge_property,
    property_option,
    readonly_property,
)
from ._constants import MISSING, REQUIRED
from ._options import Options
from ._resolve import Hints
from ._resolve import make_converter as _make_converter
from ._resolve import make_factory as _make_factory
from ._resolve import make_validator as _make_validator
from ._utils import SlotsBase, _get_origin, slots

T = tx.TypeVar("T")


#: Class settings that fill in a field's unset attributes, and which
#: field attributes each setting controls.
#:
#: The mapping is not one-to-one: `kw_only` and `positional_only` both
#: control `kw` and `positional`, and `convert`, `validate` and `factory`
#: each control a pair. Listed explicitly rather than inferred.
#: `eq`, `order`, `hash` and `mapping` are absent because a field
#: resolves those from its own values, not from its class.
_OVERRIDABLE = {
    "alias": ("alias",),
    "property": ("property",),
    "convert": ("converter",),
    "factory": ("factory",),
    "frozen": ("frozen",),
    "kw_only": ("kw", "positional"),
    "positional_only": ("kw", "positional"),
    "repr": ("repr",),
    "validate": ("validator",),
}

#: Every field attribute a class setting decides, in a stable order.
_RESOLVED_ATTRS = tuple(dict.fromkeys(
    attr for attrs in _OVERRIDABLE.values() for attr in attrs
))


def _chain(first: tx.Callable, second: tx.Callable) -> tx.Callable:
    """Feed one callable's result into another: `first`, then `second`."""
    def chained(value: tx.Any) -> tx.Any:
        return second(first(value))
    return chained


@slots(
    'name',             # Field name
    'type',             # Field type (or type hint)
    'default',          # Default value for this field.
    'factory',          # Default: False (none), True (from hint), callable.
    'repr',             # In __repr__: True, False, or a function of the value.
    'hash',             # Include this field in the generated __hash__ method.
    'eq',               # Include this field in the generated __eq__ method.
    'order',            # Include this field in the generated __lt__ methods.
    'metadata',         # User-defined metadata
    'kw',               # Field is a keyword argument in __init__.
    'positional',       # Field is a positional argument in __init__.
    'frozen',           # Make this field immutable after initialization.
    'converter',        # Convert: False (no), True (from hint), callable.
    'validator',        # Validate: False (no), True (from hint), callable.
    '_derived',         # Which tools were worked out from the hint.
    'var',              # Whether this field is a pseudo-field
    'doc',              # Docstring for this field.
    'key',              # Field is a key in the dict-like interface.
    'alias',            # Alternative names for this field.
    'property',         # Forwarding attribute names and access modes.
    '_declared',        # What the field asked for (bookkeeping for override).
    '_narrowed_by',     # Which constraints narrowed it (bookkeeping).
    'pin',              # What a subclass matching on it does with it.
)
class Field(SlotsBase):
    """A single field in a Magic class.

    Every annotation in a Magic class body becomes a `Field`. You rarely
    create one directly. The annotation family (`Factory`, `KwOnly`,
    `ConvertTo`, ...) and the `field()` function are the usual ways in.
    """

    def __init__(self, *arg, **kwargs) -> None:
        """
        Parameters
        ----------
        name : str
            The field's name in the class body.
        type : type or type hint
            The field's type. Used for conversion, validation and
            factory defaults when those are turned on.
        default : any
            The default value.
        factory : bool or Callable[[], any], default=`Options().factory`
            How a fresh default is built per instance, rather than one
            value shared across instances: `False` builds nothing,
            `True` works the factory out from the type, and a callable
            is called to build it. The `build` property reads this as a
            plain "is a default built?" boolean. The `build=` keyword is
            an alias that sets this: `build=True`/`build=False`.
        init : bool, optional
            Whether this field appears in `__init__`. Not stored
            directly: it reads as `kw or positional`. Setting
            `init=False` forbids both ways. Setting `init=True` changes
            nothing (a field is a parameter unless something says
            otherwise). Assigning `field.init = value` afterwards sets
            both `kw` and `positional`.
        repr : bool or Callable[[any], any], default=True
            Include this field in the generated `__repr__`. A function
            of the value decides how: a string it returns is shown as
            the value, `None` or `False` hides the field, and any other
            answer shows `repr(value)` when true and hides the field
            when false. `ShowIf`, `HideIf`, `HideIfNone` and
            `HideIfDefault` are ready-made tests. A pseudo-field
            defaults to False.
        hash : bool, default=None (follows `eq`)
            Include this field in the generated `__hash__`. Defaults to
            following `eq`, since equal instances must hash equally.
        eq : bool, default=True
            Include this field in the generated `__eq__`.
        order : bool, default=follows `eq`
            Include this field in the generated ordering. A field out
            of `__eq__` is out of ordering too. Setting `eq=False` with
            `order=True` is an error.
        metadata : dict, optional
            Arbitrary user-defined metadata.
        kw : bool, default=`not Options().positional_only`
            Allow this field to be passed by keyword. To make it
            keyword-only, also set `positional=False`. With both set to
            False, the field takes its default (same as `init=False`).
        positional : bool, default=`not Options().kw_only`
            Allow this field to be passed by position. To make it
            positional-only, also set `kw=False`.
        frozen : bool, default=`Options().frozen`
            Forbid assignment after construction.
        converter : bool or Callable[[any], any], default=`Options().convert`
            How the incoming value is converted: `False` not at all,
            `True` using a converter worked out from the type, or a
            callable that converts it. The `convert` property reads this
            as a boolean. The `convert=` keyword is an alias that sets
            this: `convert=True`/`convert=False`.
        validator : bool or Callable[[any], any], default=`Options().validate`
            How the incoming value is validated, in the same three forms
            as `converter` (a validator returns the value unchanged when
            valid and raises when not). The `validate` property reads
            this as a boolean; `validate=` is an alias that sets it.
        var : bool, default=False
            Mark this as a pseudo-field. An `InitVar` is passed to the
            constructor but not stored. A `ClassVar` is a class
            attribute, shared by every instance and absent from the
            constructor. Using the `InitVar` and `ClassVar` annotations
            is usually clearer.
        doc : str, optional
            Documentation for this field. Also settable through the
            `Doc` annotation.
        key : bool | str | ShowIf | tuple, default=`Options().mapping`
            Include this field in the dict-like interface. A string
            value is used as the key name. A test such as `ShowIf(bool)`
            or `HideIfNone()` keeps the key only while it passes, and a
            `(name, test)` pair does both.
        alias : str | sequence[str] | bool, optional
            Input name or ordered input names. The first is preferred in
            signatures, repr and mapping keys. By default the field is
            known by its own name with any leading underscore removed.
            True adds enabled property names after that default public
            name. False keeps the stored name, including leading
            underscores.
        property : str | sequence[str] | mapping | bool, default=False
            Forwarding attributes. A name or sequence creates read/write
            properties. A mapping chooses True (or "readwrite"),
            "readonly", or False for each name. True or "readonly" alone
            exposes the preferred public name with that access mode. "all"
            exposes every input alias the field accepts (bar the stored
            attribute and any name already in use), read/write.
        pin : str or bool, optional
            What a subclass that matches on this field does with it.
            When left out, each such subclass uses its own
            `pin_discriminant` setting. It
            takes the values the `pin_discriminant` setting takes --
            "pin", "classvar", "keep", "narrow", "pin+narrow",
            "classvar+narrow" or "keep+narrow" -- and also `True` (the
            same as "pin") and `False` (the same as "keep"). It wins
            over `pin_discriminant` on every class that matches on the
            field, including subclasses that inherit it. Also settable
            through the `Pin`, `Narrow` and `NoPin` annotations.

        Other Parameters
        ----------------
        compare : bool, optional
            Shorthand for setting both `eq` and `order` at once.
        kw_only : bool, optional
            The `dataclasses` spelling. `kw_only=True` makes the field
            keyword-only, as the `KwOnly` annotation does. `kw_only=False`
            lets it be passed by position or by keyword, whatever the
            class says.
        default_factory : Callable[[], any], optional
            The `dataclasses` spelling of `factory`: called to build a
            fresh default for each instance.

        Raises
        ------
        TypeError
            When given a keyword not listed here, or both `factory` and
            `default_factory`.
        """
        _check_keywords(type(self), kwargs)
        # The positional argument lets Field act as the opposite of Var.
        if arg and arg[0] is not MISSING:
            kwargs["var"] = not arg[0]
        # Each pipeline step has one tri-state slot: `False` (off),
        # `True` (on, work the callable out from the type) or a callable
        # (on, use it). `convert`/`validate`/`build` are aliases that set
        # the same slot -- `convert=True` is `converter=True` -- and the
        # callable spelling wins if both are given.
        for flag, call in _FLAG_TO_CALL.items():
            if flag in kwargs:
                kwargs.setdefault(call, kwargs.pop(flag))
        # `compare` sets both `eq` and `order` at once.
        compare = kwargs.pop("compare", MISSING)
        if compare is not MISSING:
            kwargs.setdefault("eq", compare)
            kwargs.setdefault("order", compare)
        # `init` has no slot: it maps to the `kw` and `positional` pair.
        # `init=False` forbids both. `init=True` is the default and
        # changes nothing.
        init = kwargs.pop("init", MISSING)
        if init is True:
            init = MISSING
        if init is not MISSING:
            kwargs.setdefault("kw", init)
            kwargs.setdefault("positional", init)
        # `kw_only=` (the `dataclasses` spelling) sets the same pair:
        # keyword-only, or positional-or-keyword. `init=False` wins.
        kw_only = kwargs.pop("kw_only", MISSING)
        if kw_only is not MISSING:
            kwargs.setdefault("kw", True)
            kwargs.setdefault("positional", not kw_only)
        # `default_factory=` (the `dataclasses` spelling) is `factory=`.
        if "default_factory" in kwargs:
            if "factory" in kwargs:
                raise TypeError(
                    "A field takes factory= or default_factory=, not both:"
                    " they are two spellings of the same thing."
                )
            kwargs["factory"] = kwargs.pop("default_factory")
        if "alias" in kwargs:
            kwargs["alias"] = alias_option(kwargs["alias"])
        if "property" in kwargs:
            kwargs["property"] = property_option(kwargs["property"])
        # `repr=Repr(...)` and `key=Key(...)` take the setting the
        # annotation carries, so wrapping one in another never stacks.
        # A test (`ShowIf(...)`) is its own setting and is kept.
        value = kwargs.get("repr", MISSING)
        while isinstance(value, Repr) and value.repr is not value:
            value = value.repr
        if value is not MISSING:
            kwargs["repr"] = value
        value = kwargs.get("key", MISSING)
        while isinstance(value, Key):
            value = value.key
        if value is not MISSING:
            kwargs["key"] = value
        # set slots from keywords
        super().__init__(**kwargs)

    def __class_getitem__(cls, t: tx.Union[type, tx.Tuple]) -> tx.TypeAlias:
        # Support subscript syntax: `Factory[list]` becomes
        # `Annotated[list, Factory(build=True)]`.
        if not isinstance(t, tuple):
            t = (t,)
        t, *args = t
        return tx.Annotated[(t, cls(True)) + tuple(args)]

    @property
    def init(self) -> bool:
        """Whether the generated `__init__` takes this field.

        True when the field can be passed by keyword, by position, or
        both. False when it can be passed neither way. Computed from
        `kw` and `positional`.

        Setting `field.init = True` or `field.init = False` sets both
        `kw` and `positional` to that value. `Field(init=False)` (or
        `NoInit`) forbids both ways. `Field(init=True)` (or `Init`)
        changes nothing, since a field is a parameter by default.
        """
        return bool(self.kw or self.positional)

    @init.setter
    def init(self, value: bool) -> None:
        self.kw = self.positional = value

    @property
    def convert(self) -> bool:
        """Whether the incoming value is converted.

        Reads `converter`: `True` for a converter worked out from the
        type or a callable given directly, `False` when conversion is
        off. Set conversion through `converter`, or the `convert=`
        keyword when building the field.
        """
        return self.converter is not False

    @property
    def validate(self) -> bool:
        """Whether the incoming value is validated.

        Reads `validator`, the same way `convert` reads `converter`.
        """
        return self.validator is not False

    @property
    def build(self) -> bool:
        """Whether a fresh default is built for this field per instance.

        Reads `factory`, the same way `convert` reads `converter`.
        """
        return self.factory is not False

    @property
    def aliases(self) -> tx.Tuple[str, ...]:
        """Accepted input names, with the preferred public name first."""
        if self.alias is False:
            return (self.name,)
        if isinstance(self.alias, str):
            return (self.alias,)
        if isinstance(self.alias, tuple):
            return self.alias
        names = (self.name.lstrip("_"),)
        if self.alias is True and isinstance(self.property, tuple):
            names += tuple(name for name, mode in self.property
                           if mode is not False and name not in names)
        return names

    @property
    def properties(self) -> tx.Mapping[str, tx.Union[bool, str]]:
        """Forwarding attribute names and their access modes, as a copy."""
        if self.property is MISSING or self.property is False:
            return {}
        if isinstance(self.property, tuple):
            return dict(self.property)
        if self.property in ("all", "readonly-all"):
            # Forward every input alias the field accepts, bar the stored
            # attribute itself (already reachable) and any double-underscore
            # name (which Python reserves). Read/write unless the read-only
            # form asked otherwise; a name already taken is left alone when
            # the class is built.
            mode = "readonly" if self.property == "readonly-all" else True
            return {
                name: mode
                for name in self.aliases
                if name != self.name and not name.startswith("__")
            }
        # `True`/`"readonly"` exposes just the preferred public name.
        return {self.public_name: self.property}

    @property
    def public_name(self) -> str:
        """The preferred public name, used in generated methods."""
        return self.aliases[0]

    @property
    def public_key(self) -> tx.Optional[str]:
        """The key to use for this field in the generated dict-like
        interface."""
        key = self.key
        if key is MISSING or key is False:
            return None
        if isinstance(key, tuple):
            key = key[0]
        elif isinstance(key, HIDE_IF_NONE):
            key = key._key
        if isinstance(key, str):
            return key
        return self.public_name

    @classmethod
    def from_hint(
        cls, name: str, hint: tx.Any, default: tx.Any = MISSING
    ) -> tx.Self:
        type = hint
        origin = _get_origin(hint)

        if origin is tx.ClassVar:
            # Replace python's ClassVar with our own.
            hint = ClassVar[tx.get_args(hint)]
            return cls.from_hint(name, hint, default)

        field = Field()
        if origin is tx.Annotated:
            type, *hints = tx.get_args(hint)
            if tx.get_origin(type) is tx.ClassVar:
                # Replace python's ClassVar with our own.
                type = tx.get_args(type)[0]
                hints = (ClassVar(), *hints)
            for hint in hints:
                if isinstance(hint, Field):
                    field.update(hint)
                elif isinstance(hint, tx.Doc):
                    field.doc = hint.documentation
        field.update(Field(name=name, type=type, default=default))
        return field

    def update(self, other: tx.Self) -> None:
        # The collection-valued slots accumulate when one field is
        # declared more than once -- stacked annotations, or an annotation
        # and a `field()` default: aliases concatenate, property tables and
        # metadata are unioned, and a converter or validator declared on
        # both is chained (the earlier one runs first) -- rather than the
        # later declaration replacing the earlier. Every other slot is
        # last-wins. A whole-field toggle (`alias=True`, `property="all"`)
        # is not a collection, and a type-derived pipeline step (`True`)
        # is not yet a callable to chain, so those stay last-wins too.
        mine, theirs = self.alias, other.alias
        alias = (
            merge_alias(mine, theirs)
            if isinstance(mine, (str, tuple))
            and isinstance(theirs, (str, tuple))
            else MISSING
        )
        mine, theirs = self.property, other.property
        prop = (
            merge_property(mine, theirs)
            if isinstance(mine, tuple) and isinstance(theirs, tuple)
            else MISSING
        )
        mine, theirs = self.metadata, other.metadata
        meta = (
            {**mine, **theirs}
            if isinstance(mine, dict) and isinstance(theirs, dict)
            else MISSING
        )
        mine, theirs = self.converter, other.converter
        converter = (
            _chain(mine, theirs)
            if callable(mine) and callable(theirs)
            else MISSING
        )
        mine, theirs = self.validator, other.validator
        validator = (
            _chain(mine, theirs)
            if callable(mine) and callable(theirs)
            else MISSING
        )
        super().update(other)
        if alias is not MISSING:
            self.alias = alias
        if prop is not MISSING:
            self.property = prop
        if meta is not MISSING:
            self.metadata = meta
        if converter is not MISSING:
            self.converter = converter
        if validator is not MISSING:
            self.validator = validator

    def copy(self) -> tx.Self:
        # A field is mutated in place during class building, so a copy
        # must not share its `_declared` dict with the original.
        new = super().copy()
        if new._declared is not MISSING:
            new._declared = dict(new._declared)
        return new

    def __repr__(self) -> str:
        # Omit the bookkeeping slots from repr: they are internal to
        # `override`, rebuild-on-substitution and narrowing, and would
        # only make every repr longer.
        shown = (
            slot for slot in self._slots()
            if slot not in ("_declared", "_derived", "_narrowed_by")
            and getattr(self, slot, MISSING) is not MISSING
        )
        params = ", ".join(
            f"{slot}={getattr(self, slot)!r}" for slot in shown
        )
        return f"{type(self).__name__}({params})"

    def _redeclare(self, **values) -> None:
        # Set a value and mark it as the field's own preference, so
        # re-resolving against a different class's options preserves it.
        for attr, value in values.items():
            setattr(self, attr, value)
            if self._declared is not MISSING and attr in self._declared:
                self._declared[attr] = value

    def _reresolve(
        self,
        options: Options,
        attrs: tx.Sequence[str],
        hints: tx.Optional[Hints] = None,
    ) -> None:
        # Reset `attrs` to the field's own declarations, then resolve
        # them again from `options`. The field's own preferences survive.
        for attr in attrs:
            setattr(self, attr, self._declared[attr])
        self.setdefault(options, hints)

    def setdefault(
        self, options: Options, hints: tx.Optional[Hints] = None
    ) -> None:
        # Fill in unset field attributes from the class options.
        #
        # `hints` tells where to look up a forward-referenced type when
        # the converter, validator or factory is first used.
        #
        # The field's own preferences are preserved so that `override`
        # on a subclass can restore and re-resolve them.
        if self._declared is MISSING:
            self._declared = {
                attr: getattr(self, attr) for attr in _RESOLVED_ATTRS
            }
        if options.kw_only and options.positional_only:
            raise ValueError(
                "Cannot set both kw_only and positional_only to True"
            )
        if self.alias is MISSING:
            self.alias = options.alias
        if self.property is MISSING:
            self.property = False if self.var is True else options.property
        if self.doc is MISSING:
            self.doc = None
        if self.var is MISSING:
            self.var = False
        # `repr`, `eq` and `order` are not read from the class options.
        # The class option decides whether the method is generated. The
        # field attribute decides whether this field takes part in it.
        if self.repr is MISSING:
            # A test on the class option (`repr=HideIfNone()`) is a
            # per-field instruction, so it propagates. A plain bool
            # controls whether __repr__ is generated at all.
            test = _test(options.repr, "repr")
            if test is not None and not self.var:
                self.repr = test._spread()
            else:
                self.repr = not self.var
        if self.hash is MISSING:
            # None means "follow eq", which _hash_add reads.
            self.hash = None
        self.repr = _repr_setting(self.repr, self.var)
        if self.key is MISSING:
            # The class option controls whether the dict-like view
            # exists. A real field defaults to being in the view, so
            # it is already included when mapping is turned on later.
            self.key = not self.var
        self.key = _key_setting(self.key)
        if self.eq is MISSING:
            self.eq = True
        if self.order is MISSING:
            # A field out of eq is out of ordering too.
            self.order = self.eq
        if options.kw_only:
            if self.kw is MISSING:
                self.kw = True
            if self.positional is MISSING:
                self.positional = False
        elif options.positional_only:
            if self.kw is MISSING:
                self.kw = False
            if self.positional is MISSING:
                self.positional = True
        else:
            if self.kw is MISSING:
                self.kw = True
            if self.positional is MISSING:
                self.positional = True
        if self.frozen is MISSING:
            self.frozen = options.frozen
        # Each pipeline slot the field left unset takes the class option:
        # `True` (on, from the type) or `False` (off).
        if self.converter is MISSING:
            self.converter = options.convert
        if self.validator is MISSING:
            self.validator = options.validate
        if self.factory is MISSING:
            self.factory = options.factory
        # A slot left as `True` is on but named no callable, so one is
        # worked out from the field's type. Track which, so that filling
        # in a type variable rebuilds only those, not a callable given
        # by hand.
        self._derived = tuple(
            attr for attr in _FROM_TYPE if getattr(self, attr) is True
        )
        self._rebuild(hints)

    def _rebuild(self, hints: tx.Optional[Hints] = None) -> None:
        # Rebuild the type-derived callables from the current type.
        for attr in self._derived or ():
            setattr(self, attr, _FROM_TYPE[attr](self.type, hints, self.name))


#: How each type-derived callable is built.
_FROM_TYPE = {
    "converter": _make_converter,
    "validator": _make_validator,
    "factory": _make_factory,
}

#: The `convert`/`validate`/`build` keyword aliases, each mapped to the
#: tri-state slot it sets.
_FLAG_TO_CALL = {
    "convert": "converter",
    "validate": "validator",
    "build": "factory",
}


#: The keywords `Field` takes that are not the name of one of its
#: attributes, each folded onto one or more attributes in `__init__`.
#: Together with the attributes they are what a field accepts.
_KEYWORDS = (
    "build", "compare", "convert", "default_factory", "init", "kw_only",
    "validate",
)


def _test(value: tx.Any, setting: str) -> tx.Optional["ShowIf"]:
    # The test a repr or key setting stands for, or None when it is not
    # one. A test that needs nothing to be built (`HideIfNone`) may be
    # written as the bare class.
    if isinstance(value, type) and issubclass(value, ShowIf):
        if value._takes_test:
            raise TypeError(
                f"{setting}={value.__name__} needs a test to call: write "
                f"{value.__name__}(test), for example "
                f"{value.__name__}(bool)."
            )
        return value()
    if isinstance(value, ShowIf):
        return value
    return None


def _repr_setting(value: tx.Any, var: bool) -> tx.Any:
    # A field's repr setting as the generated `__repr__` reads it: True,
    # False, or a function of the value.
    if isinstance(value, type) and issubclass(value, ShowIf):
        # The bare class says "show it only while it has a value", which
        # a pseudo-field never has on the instance.
        return False if var else _test(value, "repr")
    while isinstance(value, Repr) and value.repr is not value:
        value = value.repr
    if value is True or value is False or callable(value):
        return value
    return bool(value)


def _key_setting(value: tx.Any) -> tx.Any:
    # A field's key setting as the dict-like view reads it: True, False,
    # a name, a test, or a (name, test) pair.
    while isinstance(value, Key):
        value = value.key
    if isinstance(value, tuple):
        if len(value) != 2 or not isinstance(value[0], (str, bool)):
            raise TypeError(
                f"A key setting given as a pair is a name and a test, "
                f"like Key('labels', ShowIf(bool)); got {value!r}."
            )
        name, test = value
        return (name, _key_test(test))
    if isinstance(value, HIDE_IF_NONE) and isinstance(value._key, str):
        return (value._key, value)
    if value is True or value is False or isinstance(value, str):
        return value
    if callable(value) or isinstance(value, type):
        return _key_test(value)
    return bool(value)


def _key_test(value: tx.Any) -> "ShowIf":
    test = _test(value, "key")
    if test is None:
        raise TypeError(
            f"A key setting takes True, False, a name, or a test such as "
            f"ShowIf(...) or HideIfNone(); got {value!r}. A key is kept or "
            f"left out, never reformatted, so a function that formats the "
            f"value belongs on repr instead."
        )
    return test


def _field_key_test(field: Field) -> tx.Optional["ShowIf"]:
    """The test that decides whether a field is in the dict-like view."""
    key = field.key
    if isinstance(key, tuple):
        return key[1]
    if isinstance(key, ShowIf):
        return key
    return None


def _check_keywords(
    cls: tx.Type[Field], kwargs: tx.Mapping[str, tx.Any], owner: str = ""
) -> None:
    # Refuse a keyword a field does not take, naming it and what it could
    # have been. The bookkeeping attributes (a leading underscore) are
    # set by assignment inside the package, never through the constructor.
    accepted = sorted(
        {slot for slot in cls._slots() if not slot.startswith("_")}
        | set(_KEYWORDS)
    )
    for name in kwargs:
        if name not in accepted:
            close = difflib.get_close_matches(name, accepted, n=1)
            hint = f" Did you mean {close[0]!r}?" if close else ""
            raise TypeError(
                f"{owner or cls.__name__}() got an unexpected keyword"
                f" argument {name!r}.{hint}"
                f" A field accepts: {', '.join(accepted)}."
            )


def _stored(obj: tx.Any, field: Field) -> tx.Tuple[bool, tx.Any]:
    """Return (has_value, value) for a field on an object.

    A field with no constructor parameter and no default only gets a
    value when set by hand, so (False, None) is a normal result.
    """
    try:
        return True, getattr(obj, field.name)
    except AttributeError:
        return False, None


# ----------------------------------------------------------------------
# Annotations
def field(**kwargs: tx.Any) -> tx.Any:
    """
    Describe one field, for use as its default value.

    ```python
    class Task(Magic):
        name: str
        tags: list = field(factory=list)
        token: str = field(default="", repr=False)
        retries: int = field(default=0, kw_only=True)
    ```

    Takes the same arguments as `Field` and produces the same object,
    and refuses a keyword it does not know.
    The difference is for type checkers: `field(...)` declares its
    return type as the annotated type, so `tags: list = field(...)` reads
    cleanly. `Field(...)` in that position also works.
    """
    _check_keywords(Field, kwargs, "field")
    return Field(**kwargs)


# ----------------------------------------------------------------------


@slots
class AnnotatedField(Field):

    __set_value__ = MISSING
    __set_slots__ = {}

    @classmethod
    def _set_slots(cls) -> tx.Dict[str, tx.Any]:
        set_slots = {}
        for base in reversed(cls.__mro__):
            # `__dict__`, not `getattr`: the value each slot is set to
            # comes from the class that *declares* it, so an inverse
            # (`NotPositional`) has to restate the slot to flip it, and
            # cannot flip a sibling's (`KwOnly` keeps `Kw`'s `True`).
            cls_set_slots = base.__dict__.get('__set_slots__', {})
            if isinstance(cls_set_slots, str):
                cls_set_slots = (cls_set_slots,)
            if isinstance(cls_set_slots, tuple):
                cls_set_slots = {
                    slot: base.__set_value__
                    for slot in cls_set_slots
                }
            set_slots.update(cls_set_slots)
        return set_slots

    def __init__(self, *values, **kwvalues) -> None:
        cls = type(self)
        set_slots = cls._set_slots()

        for name, value in zip(set_slots, values):
            kwvalues[name] = value
        for name, value in set_slots.items():
            kwvalues.setdefault(name, value)
        if any(value is REQUIRED for value in kwvalues.values()):
            raise TypeError(f"Missing required argument for {cls.__name__!r}")
        super().__init__(**kwvalues)

    def __class_getitem__(
        cls, args: tx.Union[type, tx.Tuple]
    ) -> tx.TypeAlias:
        set_slots = cls._set_slots()
        values = ()
        if not isinstance(args, tuple):
            args = (args,)
        t, *args = args
        if args:
            values, args = args[:len(set_slots)], args[len(set_slots):]
        if any(value is REQUIRED for value in values):
            raise TypeError(
                f"Missing required argument for {cls.__name__!r}[]"
            )
        return tx.Annotated[(t, cls(*values)) + tuple(args)]


@slots
class BoolAnnotatedField(AnnotatedField):

    __set_value__ = True

    def __class_getitem__(
        cls, args: tx.Union[type, tx.Tuple]
    ) -> tx.TypeAlias:
        if not isinstance(args, tuple):
            args = (args,)
        t, *args = args
        # No positional value: each slot takes the value its declaring
        # class set. Anything after the type stays as metadata.
        return tx.Annotated[(t, cls()) + tuple(args)]


@slots
class InversedBoolAnnotatedField(BoolAnnotatedField):
    """Base for the negative half of a pair (`NoInit`, `NotKw`, ...)."""

    __set_value__ = False


@slots
class Alias(AnnotatedField):
    """Accept a name or ordered sequence of names in the constructor.

    Write ``Alias[str, ("label", "name")]`` to accept either keyword,
    with ``label`` preferred. ``Alias[str]`` includes property names.
    """

    __set_slots__ = {"alias": True}


@slots
class Property(AnnotatedField):
    """Expose forwarding attributes for a stored field.

    Write ``Property[str, "label"]`` for read/write access, or
    ``Property[str, {"label": "readonly"}]`` for read-only access.
    A sequence gives every name read/write access. With no configuration,
    expose the preferred public name; ``Property[str, "all"]`` exposes
    every input alias the field accepts.
    """

    __set_slots__ = {"property": True}


@slots
class ReadOnlyProperty(Property):
    """Expose read-only forwarding attributes for a stored field.

    Write ``ReadOnlyProperty[str, "label"]`` to read the field through
    ``label`` without allowing assignment to it. A sequence exposes every
    name read-only. With no configuration, expose the preferred public
    name read-only; ``ReadOnlyProperty[str, "all"]`` exposes every input
    alias. It is the read-only counterpart of ``Property``, so
    ``ReadOnlyProperty[str, names]`` matches ``Property[str, names]`` but
    forbids writes.
    """

    __set_slots__ = {"property": "readonly"}

    def __init__(self, *values: tx.Any, **kwvalues: tx.Any) -> None:
        super().__init__(*values, **kwvalues)
        # Names given by position or in a sequence normalize to read/write
        # pairs; force them read-only so the name alone means read-only.
        self.property = readonly_property(self.property)


@slots
class Default(AnnotatedField):
    """
    Give a field a default value.

    !!! example "How it lowers"
        ```pycon
        >>> Default(10)
        Default(default=10)
        >>> Default[int, 10]
        typing.Annotated[int, Default(default=10)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Point(Magic):
        ...     x: Default[float, 0.0]
        ...     y: Default[float, 0.0]
        ...
        >>> Point()
        Point(x=0.0, y=0.0)
        ```
    """

    __set_slots__ = {'default': REQUIRED}


@slots
class Factory(AnnotatedField):
    """
    Build a field's default by calling something, once per instance.

    Use this instead of a plain default for anything mutable: every instance
    gets its own object. With no argument, the factory is worked out from
    the field's type.

    !!! example "How it lowers"
        ```pycon
        >>> Factory()
        Factory(factory=True)
        >>> Factory(list)
        Factory(factory=<class 'list'>)
        >>> Factory[list]
        typing.Annotated[list, Factory(factory=True)]
        >>> Factory[list, tuple]
        typing.Annotated[list, Factory(factory=<class 'tuple'>)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Basket(Magic):
        ...     items: Factory[list]
        ...
        >>> Basket().items is Basket().items
        False
        ```
    """

    __set_slots__ = {'factory': True}


@slots
class ConvertTo(AnnotatedField):
    """
    Convert whatever is passed in to the field's type.

    With no argument the converter is worked out from the type; pass a
    callable to use your own.

    !!! example "How it lowers"
        ```pycon
        >>> ConvertTo()
        ConvertTo(converter=True)
        >>> ConvertTo(int)
        ConvertTo(converter=<class 'int'>)
        >>> ConvertTo[int]
        typing.Annotated[int, ConvertTo(converter=True)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Server(Magic):
        ...     port: ConvertTo[int]
        ...
        >>> Server("8080")
        Server(port=8080)
        ```
    """

    __set_slots__ = {'converter': True}


@slots
class Validate(AnnotatedField):
    """
    Reject a value that does not match the field's type.

    With no argument the check is worked out from the type; pass a callable
    to use your own. Unlike `ConvertTo`, the value is left exactly as it
    was given.

    !!! example "How it lowers"
        ```pycon
        >>> Validate()
        Validate(validator=True)
        >>> Validate[str]
        typing.Annotated[str, Validate(validator=True)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Server(Magic):
        ...     host: Validate[str]
        ...
        >>> Server("localhost")
        Server(host='localhost')
        >>> Server(1234)
        Traceback (most recent call last):
        TypeValidationError: ...
        ```
    """

    __set_slots__ = {'validator': True}


@slots
class Init(BoolAnnotatedField):
    """
    Include a field in the generated `__init__`, or leave it out.

    `NoInit` lets a field be passed neither by name nor by position: it
    still exists and takes its default or factory value, it just cannot
    be passed in.

    `Init` is the other way round and says nothing new -- a field is a
    parameter unless something says otherwise -- so it changes nothing
    and is there to say so out loud. How the field may be passed stays
    with the class, or with `Kw` and `Positional` if you want to say.

    !!! example "How it lowers"
        ```pycon
        >>> Init()
        Init()
        >>> NoInit()
        NoInit(kw=False, positional=False)
        >>> NoInit[int]
        typing.Annotated[int, NoInit(kw=False, positional=False)]
        ```
    """

    __set_slots__ = ()


@slots
class NoInit(Init, InversedBoolAnnotatedField):
    __set_slots__ = ('kw', 'positional')


@slots
class Kw(BoolAnnotatedField):
    """
    Allow a field to be passed by keyword, or forbid it.

    Pair it with `Positional` to say exactly how a field may be given.
    `KwOnly` and `PositionalOnly` are the two useful combinations, ready
    made; forbidding both is `NoInit`.

    !!! example "How it lowers"
        ```pycon
        >>> Kw()
        Kw(kw=True)
        >>> NotKw()
        NotKw(kw=False)
        >>> KwOnly()
        KwOnly(kw=True, positional=False)
        >>> KwOnly[int]
        typing.Annotated[int, KwOnly(kw=True, positional=False)]
        ```
    """

    __set_slots__ = 'kw'


@slots
class NotKw(Kw, InversedBoolAnnotatedField):
    __set_slots__ = 'kw'


@slots
class Positional(BoolAnnotatedField):
    """
    Allow a field to be passed by position, or forbid it.

    Pair it with `Kw` to say exactly how a field may be given.
    `PositionalOnly` and `KwOnly` are the two useful combinations, ready
    made.

    !!! example "How it lowers"
        ```pycon
        >>> Positional()
        Positional(positional=True)
        >>> NotPositional()
        NotPositional(positional=False)
        >>> PositionalOnly()
        PositionalOnly(kw=False, positional=True)
        ```
    """

    __set_slots__ = 'positional'


@slots
class NotPositional(Positional, InversedBoolAnnotatedField):
    __set_slots__ = 'positional'


@slots
class KwOnly(Kw, NotPositional): ...


# Each inverse negates its own name: not keyword-only means the field may
# also be passed by position, and not positional-only means it may also be
# passed by name. Neither says anything about the other half of the pair.
@slots
class NotKwOnly(Positional): ...


@slots
class PositionalOnly(Positional, NotKw): ...


@slots
class NotPositionalOnly(Kw): ...


@slots
class Frozen(BoolAnnotatedField):
    """
    Forbid assignment to a field after the object is built.

    Useful for freezing part of an otherwise mutable class.

    !!! example "How it lowers"
        ```pycon
        >>> Frozen()
        Frozen(frozen=True)
        >>> NotFrozen()
        NotFrozen(frozen=False)
        >>> Frozen[int]
        typing.Annotated[int, Frozen(frozen=True)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Account(Magic):
        ...     id: Frozen[int]
        ...     balance: float
        ...
        >>> account = Account(1, 0.0)
        >>> account.balance = 10.0
        >>> account.id = 2
        Traceback (most recent call last):
        AttributeError: Cannot set frozen field 'id'
        ```
    """

    __set_slots__ = 'frozen'


@slots
class NotFrozen(Frozen, InversedBoolAnnotatedField):
    __set_slots__ = 'frozen'


@slots
class Var(BoolAnnotatedField):
    """
    Declare something that is not stored on each instance.

    `InitVar` is passed to `__init__`, used, and not kept -- it reaches
    `__pre_init__` and `__post_init__` like any other argument;
    `ClassVar` is a plain class attribute, shared by every instance and
    absent from `__init__`.

    !!! example "How it lowers"
        ```pycon
        >>> Var()
        Var(var=True)
        >>> InitVar()
        InitVar(var=True)
        >>> ClassVar()
        ClassVar(kw=False, positional=False, var=True)
        >>> ClassVar[str]
        typing.Annotated[str, ClassVar(kw=False, positional=False, var=True)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Counter(Magic):
        ...     start: int
        ...     unit: ClassVar[str] = "clicks"
        ...
        >>> Counter(3)
        Counter(start=3)
        >>> Counter(3).unit
        'clicks'
        ```
    """

    __set_slots__ = 'var'


@slots
class InitVar(Var): ...


@slots
class ClassVar(Var, NoInit): ...


@slots
class Repr(BoolAnnotatedField):
    """
    Show a field in the generated `__repr__`, hide it, or choose how.

    Besides `True` and `False`, a field's repr setting can be a function
    of the value. Its answer decides what is shown:

    - a string is shown as the value's text, in place of `repr(value)`;
    - `None` or `False` hides the field;
    - `True`, or anything else that is true, shows `repr(value)`;
    - anything else that is false hides the field.

    So a function can format the value, or decide whether it is shown.
    `ShowIf`, `HideIf`, `HideIfNone` and `HideIfDefault` are ready-made
    tests of the second kind.

    !!! example "How it lowers"
        ```pycon
        >>> Repr()
        Repr(repr=True)
        >>> NoRepr()
        NoRepr(repr=False)
        >>> NoRepr[str]
        typing.Annotated[str, NoRepr(repr=False)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class User(Magic):
        ...     name: str
        ...     password: NoRepr[str]
        ...
        >>> User("ada", "hunter2")
        User(name='ada')
        ```

    !!! example "Formatting the value"
        ```pycon
        >>> one_place = "{:.1f}".format
        >>> class Reading(Magic):
        ...     celsius: Repr[float, one_place]
        ...
        >>> Reading(21.456)
        Reading(celsius=21.5)
        ```
    """

    __set_slots__ = ('repr',)

    def __class_getitem__(
        cls, args: tx.Union[type, tx.Tuple]
    ) -> tx.TypeAlias:
        # `Repr[float, "{:.2f}".format]` puts the function in the repr
        # setting. Anything after the type that is not callable stays as
        # metadata, as it does on every other member of the family.
        if (
            isinstance(args, tuple) and len(args) > 1 and callable(args[1])
            and not issubclass(cls, InversedBoolAnnotatedField)
        ):
            t, how, *rest = args
            return tx.Annotated[(t, cls(how)) + tuple(rest)]
        # Named rather than `super()`: the `slots` decorator rebuilds the
        # class, and before 3.10 a classmethod's `super()` keeps pointing
        # at the class it was first written in.
        return BoolAnnotatedField.__dict__["__class_getitem__"].__func__(
            cls, args
        )


@slots
class NoRepr(Repr, InversedBoolAnnotatedField):
    __set_slots__ = ('repr',)


@slots('_predicate')
class ShowIf(Repr):
    """
    Show a field in `__repr__` only while a test of its value passes.

    `ShowIf(test)` calls `test(value)` and shows the field when the
    answer is true. It also works as a key setting on a dict-like class
    (`Key(ShowIf(test))`), where it leaves the key out while the test
    fails.

    !!! example "How it lowers"
        ```pycon
        >>> ShowIf(bool)
        ShowIf(<class 'bool'>)
        >>> ShowIf[int, bool]
        typing.Annotated[int, ShowIf(<class 'bool'>)]
        >>> Repr(ShowIf(bool))
        Repr(repr=ShowIf(<class 'bool'>))
        ```

    !!! example "In a class"
        ```pycon
        >>> class Order(Magic):
        ...     item: str
        ...     notes: ShowIf[str, bool] = ""
        ...
        >>> Order("tea")
        Order(item='tea')
        >>> Order("tea", "no sugar")
        Order(item='tea', notes='no sugar')
        ```
    """

    __set_slots__ = ('repr',)

    def __init__(self, predicate: tx.Callable[[tx.Any], tx.Any], /) -> None:
        if not callable(predicate):
            raise TypeError(
                f"{type(self).__name__}() takes a function of the value, "
                f"called to decide whether the field is shown; got "
                f"{predicate!r}."
            )
        super().__init__()
        self._predicate = predicate
        # The setting a field takes from this is the test itself.
        self.repr = self

    def __call__(self, value: tx.Any) -> bool:
        return bool(self._predicate(value))

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._predicate!r})"

    def __class_getitem__(
        cls, args: tx.Union[type, tx.Tuple]
    ) -> tx.TypeAlias:
        # `ShowIf[int, test]` is `Annotated[int, ShowIf(test)]`. The
        # subclasses that need no test (`HideIfNone`, `HideIfDefault`)
        # take only the type. Anything further stays as metadata.
        if not isinstance(args, tuple):
            args = (args,)
        if cls._takes_test:
            if len(args) < 2:
                raise TypeError(
                    f"{cls.__name__}[] takes a type and a test: "
                    f"{cls.__name__}[int, bool]."
                )
            t, test, *rest = args
            return tx.Annotated[(t, cls(test)) + tuple(rest)]
        t, *rest = args
        return tx.Annotated[(t, cls()) + tuple(rest)]

    # Whether the constructor and the subscription take a test.
    _takes_test = True

    def _spread(self) -> tx.Self:
        # The test a class setting hands to each of its fields.
        return self

    def _bind(self, field: Field, owner: str) -> tx.Callable:
        # The test as it applies to one field of one class. Only
        # `HideIfDefault` depends on the field; every other test is
        # already complete.
        return self


@slots
class HideIf(ShowIf):
    """
    Hide a field from `__repr__` while a test of its value passes.

    The opposite of `ShowIf`: `HideIf(test)` hides the field when
    `test(value)` is true.

    !!! example "In a class"
        ```pycon
        >>> class Retry(Magic):
        ...     attempts: HideIf[int, lambda n: n < 0] = -1
        ...
        >>> Retry()
        Retry()
        >>> Retry(3)
        Retry(attempts=3)
        ```
    """

    __set_slots__ = ('repr',)

    def __call__(self, value: tx.Any) -> bool:
        return not self._predicate(value)


def _is_none(value: tx.Any) -> bool:
    return value is None


@slots
class HideIfNone(HideIf):
    """
    Hide a field from `__repr__` while it holds `None`.

    The class itself can be written wherever an instance can:
    `Field(repr=HideIfNone)` is `Field(repr=HideIfNone())`. As a class
    setting, `class C(Magic, repr=HideIfNone())`, it applies to every
    field.

    !!! example "In a class"
        ```pycon
        >>> class Person(Magic):
        ...     name: str
        ...     nickname: HideIfNone[tx.Optional[str]] = None
        ...
        >>> Person("Margaret")
        Person(name='Margaret')
        >>> Person("Margaret", "Peggy")
        Person(name='Margaret', nickname='Peggy')
        ```
    """

    __set_slots__ = ('repr',)
    _takes_test = False

    def __init__(self) -> None:
        super().__init__(_is_none)

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"


def _equals(default: tx.Any, value: tx.Any) -> bool:
    # Whether a value is the field's default. A comparison that cannot
    # give a yes or a no -- an array compares element by element, and
    # the answer has no single truth -- counts as "not the default", so
    # the field is shown rather than hidden on a guess.
    if value is default:
        return True
    try:
        return bool(value == default)
    except Exception:
        return False


@slots('_lenient')
class HideIfDefault(HideIf):
    """
    Hide a field from `__repr__` while it holds its default.

    A value counts as the default when it is the default, or compares
    equal to it. A value that cannot be compared with it is shown. The
    field needs a plain default to compare with: one built by a factory
    is refused, since each instance has its own.

    As a class setting, `class C(Magic, repr=HideIfDefault())`, it
    applies to every field that has a plain default, and the others are
    always shown.

    !!! example "In a class"
        ```pycon
        >>> class Request(Magic):
        ...     url: str
        ...     method: HideIfDefault[str] = "GET"
        ...
        >>> Request("/home")
        Request(url='/home')
        >>> Request("/home", "POST")
        Request(url='/home', method='POST')
        ```
    """

    __set_slots__ = ('repr',)
    _takes_test = False

    def __init__(self) -> None:
        super().__init__(_equals)
        self._lenient = False

    def __call__(self, value: tx.Any) -> bool:
        raise TypeError(
            "HideIfDefault compares a value with a field's default, so it "
            "only works on a field of a Magic class."
        )

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    def _spread(self) -> tx.Self:
        # The copy a class setting hands to each of its fields: one with
        # no plain default is shown rather than refused.
        copy = HideIfDefault()
        copy._lenient = True
        return copy

    def _bind(self, field: Field, owner: str) -> tx.Callable:
        if field.default is MISSING or field.build:
            if self._lenient:
                return True
            has = (
                "a default built afresh for each instance (a factory, or"
                " a mutable default such as [])"
                if field.build else "no default"
            )
            raise TypeError(
                f"{owner}.{field.name} uses HideIfDefault, but has {has}, "
                f"so there is no single value to compare with. Give it a "
                f"plain default, or use HideIf with a test of your own."
            )
        return HideIf(partial(_equals, field.default))


@slots('_key')
class HIDE_IF_NONE(HideIfNone):
    """
    The original spelling of `HideIfNone`, still accepted.

    `HIDE_IF_NONE("name")` as a key setting also renames the key, the
    way `Key("name", HideIfNone())` does.
    """

    __set_slots__ = ('repr',)

    def __init__(self, key: tx.Optional[str] = None) -> None:
        super().__init__()
        self._key = key

    def __repr__(self) -> str:
        if isinstance(self._key, str):
            return f"{type(self).__name__}({self._key!r})"
        return f"{type(self).__name__}()"


@slots
class Eq(BoolAnnotatedField):
    """
    Compare a field in the generated `__eq__`, or ignore it.

    An ignored field takes no part in equality, so two objects that differ
    only there compare equal.

    !!! example "How it lowers"
        ```pycon
        >>> Eq()
        Eq(eq=True)
        >>> NoEq()
        NoEq(eq=False)
        >>> NoEq[int]
        typing.Annotated[int, NoEq(eq=False)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Sample(Magic):
        ...     value: int
        ...     measured_at: NoEq[float] = 0.0
        ...
        >>> Sample(1, 100.0) == Sample(1, 999.0)
        True
        ```
    """

    __set_slots__ = ('eq',)


@slots
class NoEq(Eq, InversedBoolAnnotatedField):
    __set_slots__ = ('eq',)


@slots
class Order(BoolAnnotatedField):
    """
    Compare a field in the generated ordering, or ignore it.

    Ordering is off unless the class asks for it with `order=True`.

    !!! example "How it lowers"
        ```pycon
        >>> Order()
        Order(order=True)
        >>> NoOrder()
        NoOrder(order=False)
        >>> NoOrder[int]
        typing.Annotated[int, NoOrder(order=False)]
        ```
    """

    __set_slots__ = ('order',)


@slots
class NoOrder(Order, InversedBoolAnnotatedField):
    __set_slots__ = ('order',)


@slots
class Compare(Eq, Order):
    """
    Use a field for both equality and ordering, or for neither.

    A shorthand for setting `Eq` and `Order` together.

    !!! example "How it lowers"
        ```pycon
        >>> Compare()
        Compare(eq=True, order=True)
        >>> NoCompare()
        NoCompare(eq=False, order=False)
        >>> NoCompare[int]
        typing.Annotated[int, NoCompare(eq=False, order=False)]
        ```
    """


@slots
class NoCompare(Compare, InversedBoolAnnotatedField):
    __set_slots__ = ('eq', 'order')


@slots
class Hash(BoolAnnotatedField):
    """
    Include a field in the generated `__hash__`, or leave it out.

    A field left out of the comparison is left out of the hash too, so you
    rarely need this on its own.

    !!! example "How it lowers"
        ```pycon
        >>> Hash()
        Hash(hash=True)
        >>> NoHash()
        NoHash(hash=False)
        >>> NoHash[int]
        typing.Annotated[int, NoHash(hash=False)]
        ```
    """

    __set_slots__ = ('hash',)


@slots
class NoHash(Hash, InversedBoolAnnotatedField):
    __set_slots__ = ('hash',)


@slots
class Key(BoolAnnotatedField):
    """
    Include a field in the dict-like interface, or leave it out.

    Only relevant on a class built with `mapping=True`. Pass a string to use
    a different key from the field name.

    !!! example "How it lowers"
        ```pycon
        >>> Key()
        Key(key=True)
        >>> NotKey()
        NotKey(key=False)
        >>> Key("id")
        Key(key='id')
        >>> NotKey[int]
        typing.Annotated[int, NotKey(key=False)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Row(Magic, mapping=True):
        ...     name: str
        ...     cached: NotKey[int] = 0
        ...
        >>> dict(Row("ada"))
        {'name': 'ada'}
        ```

    A test such as `ShowIf(bool)` or `HideIfNone()` keeps the key only
    while it passes. Give a name first to rename the key as well.

    !!! example "With a test"
        ```pycon
        >>> class Post(Magic, mapping=True):
        ...     title: str
        ...     tags: tx.Annotated[tuple, Key("labels", ShowIf(bool))] = ()
        ...
        >>> dict(Post("hi"))
        {'title': 'hi'}
        >>> dict(Post("hi", ("news",)))
        {'title': 'hi', 'labels': ('news',)}
        ```
    """

    __set_slots__ = ('key',)

    def __init__(self, *values, **kwvalues) -> None:
        # `Key("labels", ShowIf(bool))`: a name and a test together.
        if len(values) == 2:
            values = (tuple(values),)
        super().__init__(*values, **kwvalues)


@slots
class NotKey(Key, InversedBoolAnnotatedField):
    __set_slots__ = ('key',)


@slots
class Doc(AnnotatedField, tx.Doc):
    """
    Document a field.

    The text appears in the class docstring and in the documentation of the
    generated `__init__`.

    !!! example "How it lowers"
        ```pycon
        >>> Doc("how many times to retry")
        Doc(doc='how many times to retry')
        >>> Doc[int, "how many times to retry"]
        typing.Annotated[int, Doc(doc='how many times to retry')]
        ```
    """

    __set_slots__ = ('doc',)

    def __init__(self, documentation: str, /) -> None:
        tx.Doc.__init__(self, documentation)
        AnnotatedField.__init__(self, documentation)


@slots
class Pin(AnnotatedField):
    """
    Say what a subclass that matches on this field does with it.

    A subclass written with `on={"mode": "minor"}` gives `mode` that value.
    `Pin` decides how, for this field, whatever the subclass's
    `pin_discriminant` says. It takes the same values: "pin" (the
    default), "classvar", "keep", "narrow", "pin+narrow",
    "classvar+narrow" and "keep+narrow", plus `True` for "pin" and
    `False` for "keep". `Narrow[T]` is `Pin[T, "narrow"]`, and `NoPin[T]`
    is `Pin[T, False]`. Each mode is also a constant -- `PIN`,
    `CLASSVAR`, `KEEP`, `NARROW`, `PIN_NARROW`, `CLASSVAR_NARROW`,
    `KEEP_NARROW` -- which a linter reads as a name it knows, where it
    reads `"classvar"` inside the brackets as an undefined type.

    The field keeps its `Pin` in every subclass, so every class that
    matches on it treats it the same way.

    !!! example "How it lowers"
        ```pycon
        >>> Pin()
        Pin(pin='pin')
        >>> Pin[str]
        typing.Annotated[str, Pin(pin='pin')]
        >>> Pin[str, "classvar"]
        typing.Annotated[str, Pin(pin='classvar')]
        >>> Pin[str, CLASSVAR]
        typing.Annotated[str, Pin(pin='classvar')]
        >>> Narrow[str]
        typing.Annotated[str, Narrow(pin='narrow')]
        >>> NoPin[str]
        typing.Annotated[str, NoPin(pin=False)]
        ```

    !!! example "In a class"
        ```pycon
        >>> class Shape(Magic, polymorphic=True):
        ...     kind: Pin[str, "classvar"] = ""
        ...     size: float = 1.0
        ...
        >>> class Circle(Shape, on={"kind": "circle"}):
        ...     pass
        ...
        >>> Circle.kind
        'circle'
        >>> Shape(kind="circle", size=2.0)
        Circle(size=2.0)
        ```
    """

    __set_slots__ = {'pin': 'pin'}


@slots
class Narrow(Pin, BoolAnnotatedField):
    __set_slots__ = {'pin': 'narrow'}


@slots
class NoPin(Pin, BoolAnnotatedField):
    __set_slots__ = {'pin': False}


PIN: tx.Literal["pin"] = "pin"
"""Give the field the value the subclass stands for, as its default."""

CLASSVAR: tx.Literal["classvar"] = "classvar"
"""Make the field a class attribute holding the value; an argument for it
is accepted and dropped."""

KEEP: tx.Literal["keep"] = "keep"
"""Leave the field as it is."""

NARROW: tx.Literal["narrow"] = "narrow"
"""The same as `PIN_NARROW`."""

PIN_NARROW: tx.Literal["pin+narrow"] = "pin+narrow"
"""`PIN`, and refuse any other value for the field."""

CLASSVAR_NARROW: tx.Literal["classvar+narrow"] = "classvar+narrow"
"""`CLASSVAR`, and refuse any other value for the field."""

KEEP_NARROW: tx.Literal["keep+narrow"] = "keep+narrow"
"""`KEEP`, and refuse any other value for the field."""
