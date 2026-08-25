from __future__ import annotations

__all__ = [
    "Field",
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


@slots(
    'name',             # Field name
    'type',             # Field type (or type hint)
    'default',          # Default value for this field.
    # A factory function that generates a default value for this field.
    'factory',
    'repr',             # Include this field in the generated __repr__ method.
    'hash',             # Include this field in the generated __hash__ method.
    'eq',               # Include this field in the generated __eq__ method.
    'order',            # Include this field in the generated __lt__ methods.
    'metadata',         # User-defined metadata
    # Make this field a keyword in the generated __init__ method.
    'kw',
    # Make this field a positional argument in the generated __init__
    # method.
    'positional',
    'frozen',           # Make this field immutable after initialization.
    # A function that converts the input value for this field.
    'converter',
    # A function that validates the input value for this field.
    'validator',
    # Whether this field is a pseudo-field (InitVar or ClassVar).
    'var',
    'doc',              # Docstring for this field.
    # Include this field in the generated dict-like interface.
    'key',
    # Alternative names for this field in the generated methods.
    'alias',
)
class Field(SlotsBase):
    """A field in a `Magic`."""

    def __init__(self, *arg, **kwargs) -> None:
        """
        Parameters
        ----------
        name : str
            The name of the field.
        type : type or type hint
            The type of the field.
            This is used for type checking, validation, and conversion.
        default : any
            The default value for the field.
        factory : Callable[[], any], default=`Options().factory`
            A factory function that generates a default value for the field.
        init : bool, optional
            Whether this field is a parameter of the generated `__init__`.
            It is not stored but worked out from `kw` and `positional`:
            reading it gives `kw or positional`, so a field that can be
            passed neither by name nor by position is no parameter at
            all. Passing `init=False` here forbids both ways; passing
            `init=True` says nothing, since a field is a parameter
            unless something says otherwise. Assigning to `field.init`
            afterwards always sets both.
            Whether that method is generated at all is the class-level
            `init` option, which is a separate question.
        repr : bool, default=True (False for a pseudo-field)
            Whether to include this field in the generated `__repr__`.
        hash : bool, default=None (follow this field's `eq`)
            Whether to include this field in the generated `__hash__`.
            Equal instances must hash equally, so a field left out of
            the comparison is left out of the hash unless you say
            otherwise.
        eq : bool, default=True
            Whether to include this field in the generated `__eq__`.
        order : bool, default=the field's `eq`
            Whether to include this field in the generated ordering. A
            field out of the comparison is out of the ordering too;
            asking for the reverse explicitly is an error.
        metadata : dict, optional
            User-defined metadata for this field.
        kw : bool, default=`not Options().positional_only`
            Make this field a keyword argument in the generated `__init__`
            method. To make the field keyword-only, set `positional=False`
            as well; with both set to False the field is no argument at
            all, the same as `init=False`.
        positional : bool, default=`not Options().kw_only`
            Make this field a positional argument in the generated `__init__`
            method. To make the field positional-only, set `kw=False` as well.
        frozen : bool, default=`Options().frozen`
            Whether to make this field immutable after initialization.
        converter : bool | Callable[[any], any], default=`Options().convert`
            A function that converts the input value for this field.
            If `True`, a converter will be generated based on the field type.
        validator : bool | Callable[[any], any], default=`Options().validate`
            A function that validates the input value for this field.
            If should be pass-through when the value is valid, and raise
            an exception when it is not.
            If `True`, a validator will be generated based on the field type.
        var : bool, default=False
            Whether this field is a pseudo-field (InitVar or ClassVar).
            Pseudo-fields are not set by the generated `__init__` method,
            but may be one of its arguments (when `init=True`), or used
            in the generated `__repr__` method (when `init=False,
            repr=True`).
            It is often more readable to use the `InitVar` and `ClassVar`
            annotations.
        doc : str, optional
            A docstring for this field.
            The `typing_extensions.Doc` annotation can also be used to
            set this.
        key : bool | str, default=`Options().mapping`
            Whether to include this field in the generated dict-like
            interface. If a string, it will be used as the key.
        alias : str, default=`name.lstrip("_")`
            An alternative name for this field in the generated methods.
            This is useful when the field name is not a valid Python
            identifier, or when you want to use a different name in the
            generated methods for readability or consistency with an
            external API.
            By default, names that start with an underscore will have
            the underscore stripped in the alias.

        Other Parameters
        ----------------
        compare : bool, optional
            Alias for setting both `eq` and `order` at the same time.
        """
        # The positional argument is a special case in which `Field``
        # acts as the opposite of `Var`.
        if arg and arg[0] is not MISSING:
            kwargs["var"] = not arg[0]
        # `compare` is a special alias for setting both `eq` and `order`
        # at the same time.
        compare = kwargs.get("compare", MISSING)
        if compare is not MISSING:
            kwargs.setdefault("eq", compare)
            kwargs.setdefault("order", compare)
        # `init` has no slot of its own, for the same reason `compare`
        # has none: a field is an argument of the generated `__init__`
        # when it can be passed by name, by position, or both, so `init`
        # sets that pair. Only `init=False` says anything, though -- a
        # field is an argument unless something says otherwise, so
        # `init=True` is what it already would have been.
        init = kwargs.pop("init", MISSING)
        if init is True:
            init = MISSING
        if init is not MISSING:
            kwargs.setdefault("kw", init)
            kwargs.setdefault("positional", init)
        # set slots from keywords
        super().__init__(**kwargs)

    def __class_getitem__(cls, t: tx.Union[type, tx.Tuple]) -> tx.TypeAlias:
        # Allow using Field as an annotation.
        # It will likely never be used directly on the `Field` class,
        # but will be useful for subclasses: e.g., `Factory[list]` is
        # more concise than `Annotated[T, Field(factory=list)]`.
        if not isinstance(t, tuple):
            t = (t,)
        t, *args = t
        return tx.Annotated[(t, cls(True)) + tuple(args)]

    @property
    def init(self) -> bool:
        """Whether the generated `__init__` takes this field as an
        argument.

        A field is an argument when it can be passed by keyword, by
        position, or both, and is no argument at all when it can be
        passed neither way. Reading this works that out from `kw` and
        `positional`.

        There are three ways to say it, and they do not all say the
        same thing:

        - `field.init = True` or `field.init = False` sets both `kw`
          and `positional` to that, replacing whatever they held.
          Assignment comes after the declarations have been read, so
          there is nothing left for it to defer to.
        - `Field(init=False)`, like `NoInit`, forbids both ways.
        - `Field(init=True)`, like `Init`, says nothing at all: a field
          is an argument unless something says otherwise, so how it may
          be passed is left to `kw`, `positional` and the class.
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

    def setdefault(
        self, options: Options, hints: tx.Optional[Hints] = None
    ) -> None:
        # When field options are not explicitly set (MISSING), they are
        # inherited from the class options.
        #
        # `hints` says where to look up a type this field was annotated
        # with by name -- a class that names itself, a type imported for
        # type checking only -- when the converter, validator or factory
        # built here is first used.
        if options.kw_only and options.positional_only:
            raise ValueError(
                "Cannot set both kw_only and positional_only to True"
            )
        if self.doc is MISSING:
            self.doc = None
        if self.var is MISSING:
            self.var = False
        # `repr`, `eq` and `order` are deliberately *not* read from the
        # class options. Those decide whether a method is generated at
        # all; this decides whether a field takes part in one. Conflating
        # them made every generated method on a class that had opted out
        # cover no fields -- so `__magic_eq__` on an `eq=False` class
        # compared nothing and answered True for any two instances.
        if self.repr is MISSING:
            # A sentinel on the class option is a per-field instruction
            # ("show it only when it has a value"), so it propagates;
            # a plain bool is only about whether `__repr__` is
            # generated, which is not this field's business.
            sentinel = (
                isinstance(options.repr, SHOW_ATTR)
                or options.repr is HIDE_IF_NONE
            )
            self.repr = (
                options.repr if sentinel and not self.var else not self.var
            )
        if self.hash is MISSING:
            # `None` means "follow `eq`", which `_hash_add` reads. Forcing
            # True here made a field excluded from `__eq__` still count
            # towards `__hash__`, so two equal instances hashed apart and
            # a set kept both.
            self.hash = None
        if self.key is MISSING:
            self.key = options.mapping
        if self.eq is MISSING:
            self.eq = True
        if self.order is MISSING:
            # A field out of the comparison is out of the ordering too.
            # Only an explicit `Field(eq=False, order=True)` is a
            # contradiction, and that is still an error.
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
        if self.converter is MISSING:
            self.converter = options.convert
        if self.converter is True:
            self.converter = _make_converter(self.type, hints, self.name)
        if self.validator is MISSING:
            self.validator = options.validate
        if self.validator is True:
            self.validator = _make_validator(self.type, hints, self.name)
        if self.factory is MISSING:
            self.factory = options.factory
        if self.factory is True:
            # Resolve the default factory from the field's type hint, the
            # same way converters/validators are resolved from their bag.
            self.factory = _make_factory(self.type, hints, self.name)


def _stored(obj: tx.Any, field: Field) -> tx.Tuple[bool, tx.Any]:
    """The value a field holds on an object, and whether it holds one.

    A field that is not a constructor argument and has no default is
    only ever set by hand, so an object can be perfectly usable and
    still have nothing under this name.
    """
    try:
        return True, getattr(obj, field.name)
    except AttributeError:
        return False, None


# ----------------------------------------------------------------------
# Annotations
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
        # No positional value: every slot takes the value its own
        # declaring class set, so an inverse comes out `False` and a
        # mixed pair (`KwOnly`) keeps one of each. Anything after the
        # type stays metadata.
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
