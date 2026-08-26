from __future__ import annotations

__all__ = [
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
]
import typing_extensions as tx

from ._constants import HIDE_IF_NONE, MISSING, REQUIRED, SHOW_ATTR
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
    "convert": ("convert", "converter"),
    "factory": ("build", "factory"),
    "frozen": ("frozen",),
    "kw_only": ("kw", "positional"),
    "positional_only": ("kw", "positional"),
    "repr": ("repr",),
    "validate": ("validate", "validator"),
}

#: Every field attribute a class setting decides, in a stable order.
_RESOLVED_ATTRS = tuple(dict.fromkeys(
    attr for attrs in _OVERRIDABLE.values() for attr in attrs
))


@slots(
    'name',             # Field name
    'type',             # Field type (or type hint)
    'default',          # Default value for this field.
    'build',            # True if default is built by calling something.
    'factory',          # Default factory (None = from hint).
    'repr',             # Include this field in the generated __repr__ method.
    'hash',             # Include this field in the generated __hash__ method.
    'eq',               # Include this field in the generated __eq__ method.
    'order',            # Include this field in the generated __lt__ methods.
    'metadata',         # User-defined metadata
    'kw',               # Field is a keyword argument in __init__.
    'positional',       # Field is a positional argument in __init__.
    'frozen',           # Make this field immutable after initialization.
    'convert',          # Whether the value handed to this field is converted.
    'converter',        # Value converter (None = from hint)
    'validate',         # Whether the value handed to this field is validated.
    'validator',        # Value validator (None = from hint)
    'derived',          # List of hint-derived tools
    'var',              # Whether this field is a pseudo-field
    'doc',              # Docstring for this field.
    'key',              # Field is a key in the dict-like interface.
    'alias',            # Alternative names for this field.
    'declared',         # See description below.
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
        build : bool, default=`Options().factory`
            Build a fresh default per instance by calling something,
            rather than sharing one value across all instances.
        factory : Callable[[], any], optional
            What to call. Omit it and one is worked out from the type.
            Passing a callable turns `build` on. Passing `factory=True`
            turns it on without naming a callable.
        init : bool, optional
            Whether this field appears in `__init__`. Not stored
            directly: it reads as `kw or positional`. Setting
            `init=False` forbids both ways. Setting `init=True` changes
            nothing (a field is a parameter unless something says
            otherwise). Assigning `field.init = value` afterwards sets
            both `kw` and `positional`.
        repr : bool, default=True (False for a pseudo-field)
            Include this field in the generated `__repr__`.
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
        convert : bool, default=`Options().convert`
            Convert the incoming value.
        converter : Callable[[any], any], optional
            What converts it. Omit it and one is worked out from the
            type. Passing a callable turns `convert` on.
        validate : bool, default=`Options().validate`
            Validate the incoming value.
        validator : Callable[[any], any], optional
            What validates it: returns the value unchanged when valid,
            raises when not. Omit it and one is worked out from the
            type. Passing a callable turns `validate` on.
        derived : tuple of str, optional
            Which of `converter`, `validator` and `factory` were worked
            out from the type rather than provided. When a subclass
            fills in a type variable, these are rebuilt from the new
            type. Manually provided callables are left alone.
        var : bool, default=False
            Mark this as a pseudo-field. An `InitVar` is passed to the
            constructor but not stored. A `ClassVar` is a class
            attribute, shared by every instance and absent from the
            constructor. Using the `InitVar` and `ClassVar` annotations
            is usually clearer.
        doc : str, optional
            Documentation for this field. Also settable through the
            `Doc` annotation.
        key : bool | str, default=`Options().mapping`
            Include this field in the dict-like interface. A string
            value is used as the key name.
        alias : str, default=`name.lstrip("_")`
            The name used in generated methods (constructor parameter,
            repr output, dict key). Useful when the field name is not a
            good public name, or when matching an external API.
        declared : dict, optional
            What this field asked for before the class filled in the
            rest. Recorded the first time the field is resolved against
            a class. Used by `override` to restore the field's own
            preferences. No reason to pass it by hand.

        Other Parameters
        ----------------
        compare : bool, optional
            Shorthand for setting both `eq` and `order` at once.
        """
        # The positional argument lets Field act as the opposite of Var.
        if arg and arg[0] is not MISSING:
            kwargs["var"] = not arg[0]
        # Each pipeline step (convert, validate, build) has two slots:
        # a flag for "whether" and a callable for "what". Naming the
        # callable implies the flag: `converter=int` turns convert on,
        # `converter=True` turns it on without naming a callable, and
        # `converter=False` turns it off.
        for call, flag in _PIPELINE.items():
            given = kwargs.get(call, MISSING)
            if given is MISSING:
                continue
            if given is True or given is False:
                kwargs.setdefault(flag, given)
                del kwargs[call]
            else:
                kwargs.setdefault(flag, True)
        # `compare` sets both `eq` and `order` at once.
        compare = kwargs.get("compare", MISSING)
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
    def public_name(self) -> str:
        """The public name of this field, used in generated methods."""
        if self.alias is False:
            return self.name
        if self.alias is not MISSING:
            return self.alias
        return self.name.lstrip("_")

    @property
    def public_key(self) -> tx.Optional[str]:
        """The key to use for this field in the generated dict-like
        interface."""
        if not self.key:
            return None
        if isinstance(self.key, SHOW_ATTR) and isinstance(self.key.key, str):
            return self.key.key
        if isinstance(self.key, str):
            return self.key
        return self.public_name

    @classmethod
    def from_hint(
        cls, name: str, hint: tx.Any, default: tx.Any = MISSING
    ) -> Field:
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

    def copy(self) -> tx.Self:
        # A field is mutated in place during class building, so a copy
        # must not share its `declared` dict with the original.
        new = super().copy()
        if new.declared is not MISSING:
            new.declared = dict(new.declared)
        return new

    def __repr__(self) -> str:
        # Omit `declared` from repr since it is bookkeeping for
        # `override` and would double every repr's length.
        shown = (
            slot for slot in self._slots()
            if slot != "declared"
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
            if self.declared is not MISSING and attr in self.declared:
                self.declared[attr] = value

    def _reresolve(
        self,
        options: Options,
        attrs: tx.Sequence[str],
        hints: tx.Optional[Hints] = None,
    ) -> None:
        # Reset `attrs` to the field's own declarations, then resolve
        # them again from `options`. The field's own preferences survive.
        for attr in attrs:
            setattr(self, attr, self.declared[attr])
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
        if self.declared is MISSING:
            self.declared = {
                attr: getattr(self, attr) for attr in _RESOLVED_ATTRS
            }
        if options.kw_only and options.positional_only:
            raise ValueError(
                "Cannot set both kw_only and positional_only to True"
            )
        if self.doc is MISSING:
            self.doc = None
        if self.var is MISSING:
            self.var = False
        # `repr`, `eq` and `order` are not read from the class options.
        # The class option decides whether the method is generated. The
        # field attribute decides whether this field takes part in it.
        if self.repr is MISSING:
            # A sentinel on the class option is a per-field instruction
            # ("show only when it has a value"), so it propagates. A
            # plain bool controls whether __repr__ is generated at all.
            sentinel = (
                isinstance(options.repr, SHOW_ATTR)
                or options.repr is HIDE_IF_NONE
            )
            self.repr = (
                options.repr if sentinel and not self.var else not self.var
            )
        if self.hash is MISSING:
            # None means "follow eq", which _hash_add reads.
            self.hash = None
        # `repr` and `key` encode both "whether" and "under which name",
        # so once resolved they are stored as a SHOW_ATTR.
        if self.repr is HIDE_IF_NONE:
            if self.var:
                self.repr = SHOW_ATTR(False)
            else:
                self.repr = HIDE_IF_NONE(self.public_name)
        if not isinstance(self.repr, SHOW_ATTR):
            self.repr = SHOW_ATTR(self.repr)
        if self.key is MISSING:
            # The class option controls whether the dict-like view
            # exists. A real field defaults to being in the view, so
            # it is already included when mapping is turned on later.
            self.key = not self.var
        if self.key is HIDE_IF_NONE:
            self.key = HIDE_IF_NONE(self.public_name)
        if not isinstance(self.key, SHOW_ATTR):
            self.key = SHOW_ATTR(self.key)
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
        if self.convert is MISSING:
            self.convert = options.convert
        if self.validate is MISSING:
            self.validate = options.validate
        if self.build is MISSING:
            self.build = options.factory
        # An active step with no callable gets one from the field's type.
        # Track which ones came from the type, so that filling in a type
        # variable rebuilds only those (not manually provided callables).
        for attr in _FROM_TYPE:
            if getattr(self, attr) is MISSING:
                setattr(self, attr, None)
        self.derived = tuple(
            attr for attr in _FROM_TYPE
            if getattr(self, _PIPELINE[attr]) and getattr(self, attr) is None
        )
        self._rebuild(hints)

    def _rebuild(self, hints: tx.Optional[Hints] = None) -> None:
        # Rebuild the type-derived callables from the current type.
        for attr in self.derived or ():
            setattr(self, attr, _FROM_TYPE[attr](self.type, hints, self.name))


#: How each type-derived callable is built.
_FROM_TYPE = {
    "converter": _make_converter,
    "validator": _make_validator,
    "factory": _make_factory,
}

#: Each pipeline step's callable slot mapped to its flag slot.
_PIPELINE = {
    "converter": "convert",
    "validator": "validate",
    "factory": "build",
}


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
    ```

    Takes the same arguments as `Field` and produces the same object.
    The difference is for type checkers: `field(...)` declares its
    return type as the annotated type, so `tags: list = field(...)` reads
    cleanly. `Field(...)` in that position also works.
    """
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
        Factory(build=True)
        >>> Factory(list)
        Factory(build=True, factory=<class 'list'>)
        >>> Factory[list]
        typing.Annotated[list, Factory(build=True)]
        >>> Factory[list, tuple]
        typing.Annotated[list, Factory(build=True, factory=<class 'tuple'>)]
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
        ConvertTo(convert=True)
        >>> ConvertTo(int)
        ConvertTo(convert=True, converter=<class 'int'>)
        >>> ConvertTo[int]
        typing.Annotated[int, ConvertTo(convert=True)]
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
        Validate(validate=True)
        >>> Validate[str]
        typing.Annotated[str, Validate(validate=True)]
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
    Show a field in the generated `__repr__`, or hide it.

    Use `HIDE_IF_NONE` to show it only when it has a value.

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
    """

    __set_slots__ = ('repr',)


@slots
class NoRepr(Repr, InversedBoolAnnotatedField):
    __set_slots__ = ('repr',)


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
    """

    __set_slots__ = ('key',)


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
