"""
Choosing which subclass to build.

A class marked `polymorphic=True` lets its subclasses say which argument
values they stand for, and calling it hands back the subclass that fits:

```python
class Chord(Magic, polymorphic=True):
    mode: str
    root: str

class MinorChord(Chord, on={"mode": "minor"}):
    ...

Chord(mode="minor", root="A")     # MinorChord(mode='minor', root='A')
```

Everything here answers one of three questions.

**What does a constraint mean?** `_specification` turns each value of an
`on={...}` mapping into a predicate and a *precision* -- how narrow a
claim it is. An exact value is the narrowest, a bare `...` (the argument
was supplied at all) the widest.

**Which subclass wins?** A subclass is a candidate when every constraint
it declares matches. Among the candidates, `select` puts first the one
given the highest `priority`, then the one constraining the most fields,
then the one whose constraints are the most precise, then the deepest
subclass. Registration order is deliberately not part of that, so the
answer never depends on the order the modules were imported; a remaining
tie is an `AmbiguousPolymorphError` rather than a coin flip.

**Where does the value come from?** The fields any registration mentions
are known as soon as it registers, so the class can work out once where
each of them arrives -- which position in `__init__`, whether it may be
passed by name, what it defaults to, what converts it. `_Discriminant`
holds that, and `_read` uses it, so dispatch costs a couple of dict
lookups per constrained field rather than binding a signature.

A class with its type parameters filled in -- `Chord[int]` -- answers
all three through `_Parameterised`, a view of the registrations its
origin carries. Nothing registers with it: a subclass of `Chord[int]`
registers with `Chord`, and the view decides which of those
registrations `Chord[int]` can build and hands each back with the same
parameters filled in.
"""

__all__ = [
    "PolymorphError",
    "NoPolymorphError",
    "AmbiguousPolymorphError",
]

# stdlib
import enum

# dependencies
import typing_extensions as tx
from bagof.validators import Validator, ValueValidationError

# internals
from ._constants import (
    _FIELDS,
    _GENERATED,
    _GENERIC_ORIGIN,
    _OPTIONS,
    _POLYMORPHS,
    _REGISTRATION,
    MISSING,
    MaybeMissing,
)
from ._generics import fill_in

# ----------------------------------------------------------------------
# What can go wrong
# ----------------------------------------------------------------------


class PolymorphError(TypeError):
    """
    A class was asked to build one of its subclasses and could not.

    Raised on its own when a subclass is built with a value that
    contradicts the one it registered for, under `polymorphic="strict"`.
    `NoPolymorphError` and `AmbiguousPolymorphError` are the two other
    ways dispatch can fail, and both are kinds of this.
    """


class NoPolymorphError(PolymorphError):
    """
    No registered subclass matches the arguments.

    A class raises this when it cannot stand in for the subclass that
    was not found: under `polymorphic="strict"`, and whenever the class
    is abstract. A plain `polymorphic=True` class builds itself
    instead.
    """


class AmbiguousPolymorphError(PolymorphError):
    """
    Two registered subclasses match the arguments equally well.

    Nothing separates them, and picking either would make the answer
    depend on which module was imported first. Give one of them a
    higher `priority` to say which should win.
    """


# ----------------------------------------------------------------------
# What a constraint means
# ----------------------------------------------------------------------

#: How narrow a claim each shape of constraint makes. A candidate
#: constraining `mode` to exactly `"minor"` says more than one accepting
#: any string, so it wins when both match.
_EXACT = 4
_MEMBER = 3
_PATTERN = 2
_HINT = 1
_LOOSE = 0


class _Spec:
    """One `field: constraint` pair of a registration."""

    __slots__ = ("name", "matches", "precision", "value", "text",
                 "narrowed", "validate", "members", "parts", "pin")

    def __init__(
        self,
        name: str,
        matches: tx.Callable[[tx.Any], bool],
        precision: int,
        value: MaybeMissing[tx.Any],
        text: str,
        narrowed: MaybeMissing[tx.Any],
        validate: tx.Optional[tx.Callable[[tx.Any], tx.Any]],
        members: tx.Optional[tx.Tuple[tx.Any, ...]] = None,
        parts: tx.Optional[tx.Tuple["_Spec", ...]] = None,
        pin: MaybeMissing[str] = MISSING,
    ) -> None:
        self.name = name
        self.matches = matches
        self.precision = precision
        #: The one value this constraint accepts, when it accepts one
        #: value; `MISSING` otherwise. This is what pinning writes as
        #: the subclass's default.
        self.value = value
        #: How the constraint reads in an error message.
        self.text = text
        #: The type a narrowed discriminant should carry, or `MISSING`
        #: when the constraint says nothing a type could capture and the
        #: field keeps the type it was declared with.
        self.narrowed = narrowed
        #: A validator enforcing this constraint, chained onto a narrowed
        #: field; `None` when there is nothing to enforce (a bare `...`).
        self.validate = validate
        #: The values this constraint can accept, when there are finitely
        #: many and they are known (a set), sorted by repr; `None`
        #: otherwise. An exact value is held in `value` instead. A
        #: combination with a callable keeps the values the callable
        #: has yet to be asked about.
        self.members = members
        #: The constraints as they were written that this one is the
        #: conjunction of -- just itself, for one that was written.
        #: Combining two classes' registrations reads it, so that one
        #: constraint reaching the combination along two branches of
        #: the hierarchy counts once.
        self.parts = (self,) if parts is None else parts
        #: The `pin_discriminant` of the class that wrote this
        #: constraint, which says how a class that inherits it pins the
        #: field when the field does not say itself. `MISSING` on a
        #: combination, whose parts each carry their own.
        self.pin = pin


def _is_hint(spec: tx.Any) -> bool:
    # A type, or a typing form built out of one (`Literal[...]`,
    # `Annotated[int, ...]`, `Optional[str]`). Anything of that shape
    # goes to `bagof-validators`, so a registration can say what it
    # accepts in the same language a field does.
    return isinstance(spec, type) or tx.get_origin(spec) is not None


def _guarded(
    matches: tx.Callable[[tx.Any], tx.Any]
) -> tx.Callable[[tx.Any], bool]:
    # A value a constraint cannot even be compared with is not one it
    # accepts. Anything may turn up here -- a registration is checked
    # against whatever the caller passed, before conversion has had a
    # say -- so an `__eq__` that raises, an unhashable value handed to
    # a set, or a value `str()` refuses must all read as "no match"
    # rather than coming out of the constructor as themselves.
    def guard(value: tx.Any) -> bool:
        try:
            return bool(matches(value))
        except Exception:
            return False

    return guard


def _accepts(spec: tx.Any) -> tx.Callable[[tx.Any], bool]:
    validator = Validator.get(spec)

    def accepts(value: tx.Any) -> bool:
        try:
            validator(value)
        except Exception:
            return False
        return True

    return accepts


def _shape(
    spec: tx.Any
) -> tx.Tuple[tx.Callable[[tx.Any], tx.Any], int, MaybeMissing[tx.Any], str]:
    # What one constraint matches, how narrow a claim that is, the one
    # value it accepts when it accepts one, and how it reads.
    if spec is Ellipsis:
        return (lambda value: True), _LOOSE, MISSING, "anything"
    if isinstance(spec, (set, frozenset)):
        # A set has no order, so read it the same way every run: sorted
        # by repr, so the message (and any narrowed Literal built from
        # it) does not vary with the hash seed.
        text = "{" + ", ".join(sorted(map(repr, spec))) + "}"
        return (lambda value: value in spec), _MEMBER, MISSING, text
    if hasattr(spec, "fullmatch"):
        return (
            lambda value: spec.fullmatch(str(value)) is not None,
            _PATTERN,
            MISSING,
            f"matching {spec.pattern!r}",
        )
    if _is_hint(spec):
        return _accepts(spec), _HINT, MISSING, repr(spec)
    if callable(spec):
        return spec, _LOOSE, MISSING, repr(spec)
    return (lambda value: value == spec), _EXACT, spec, repr(spec)


def _specification(name: str, spec: tx.Any, pin: str = "pin") -> _Spec:
    """Read one value of an `on={...}` mapping."""
    matches, precision, value, text = _shape(spec)
    return _Spec(
        name,
        _guarded(matches),
        precision,
        value,
        text,
        _narrowed_type(spec),
        _constraint_validator(spec, matches, text),
        tuple(sorted(spec, key=repr))
        if isinstance(spec, (set, frozenset)) else None,
        pin=pin,
    )


# ----------------------------------------------------------------------
# Narrowing a discriminant's field from what it stands for
# ----------------------------------------------------------------------

#: The value kinds a `Literal` may hold. A constraint over anything else
#: (a regular expression, a callable, a value of some other class) cannot
#: be written as a type, so the field's declared type is left as it is.
_LITERAL_TYPES = (str, bytes, bool, int, enum.Enum)


def _literal_legal(value: tx.Any) -> bool:
    return value is None or isinstance(value, _LITERAL_TYPES)


def _narrowed_type(spec: tx.Any) -> MaybeMissing[tx.Any]:
    # The type a discriminant should carry once its class stands for
    # `spec`, or `MISSING` when the field keeps the type it was declared
    # with. An exact value becomes `Literal[value]`, a set becomes
    # `Literal[a, b, ...]` (both only when every value is one a `Literal`
    # can hold), and a type or typing form is used as it is. A regular
    # expression, a callable, or a bare `...` narrows nothing.
    if spec is Ellipsis:
        return MISSING
    if isinstance(spec, (set, frozenset)):
        # Sorted by repr, so the Literal reads the same every run rather
        # than in the set's hash-seeded order.
        members = tuple(sorted(spec, key=repr))
        if members and all(_literal_legal(member) for member in members):
            return tx.Literal[members]
        return MISSING
    if hasattr(spec, "fullmatch"):
        return MISSING
    if _is_hint(spec):
        return spec
    if callable(spec):
        return MISSING
    if _literal_legal(spec):
        return tx.Literal[spec]
    return MISSING


def _constraint_validator(
    spec: tx.Any,
    matches: tx.Callable[[tx.Any], tx.Any],
    text: str,
) -> tx.Optional[tx.Callable[[tx.Any], tx.Any]]:
    # A validator enforcing `spec`, or None when there is nothing to
    # enforce (a bare `...`). It uses the very predicate dispatch matches
    # on, so a value that would not have chosen this subclass is turned
    # down here -- returning the value unchanged when it fits, and
    # raising a validation error (named against the field by the usual
    # machinery) when it does not.
    if spec is Ellipsis:
        return None
    guarded = _guarded(matches)

    def validate(value: tx.Any) -> tx.Any:
        if not guarded(value):
            raise ValueValidationError(f"expected a value that is {text}")
        return value

    return validate


def specifications(
    clsname: str, on: tx.Mapping[str, tx.Any], pin: str = "pin"
) -> tx.Tuple[_Spec, ...]:
    """Read a whole `on={...}` mapping.

    `pin` is the `pin_discriminant` of the class the mapping describes,
    kept on each constraint for the classes that inherit it.
    """
    if not isinstance(on, tx.Mapping):
        raise TypeError(
            f"on= takes a mapping of field names to the values "
            f"{clsname} stands for, such as on={{'mode': 'minor'}}, "
            f"and was given {on!r}. Write on=None to leave {clsname} "
            f"out of the choice altogether."
        )
    return tuple(
        _specification(name, spec, pin) for name, spec in on.items()
    )


def check_fields(
    owner: type, clsname: str, specs: tx.Iterable[_Spec]
) -> None:
    """
    Refuse a registration naming a field `owner` does not have.

    The keys of `on={...}` name fields the way the class registering
    with declares them, so a misspelled one is refused when the class is
    written, rather than the first time something is built.
    """
    table = getattr(owner, _FIELDS)
    for spec in specs:
        if spec.name not in table:
            raise TypeError(
                f"{clsname} registers on {spec.name!r}, which is not a "
                f"field of {owner.__name__}. Its fields are: "
                f"{', '.join(repr(field) for field in table) or 'none'}."
            )


def has_fields(owner: type, specs: tx.Iterable[_Spec]) -> bool:
    """Whether `owner` has every field `specs` constrains."""
    table = getattr(owner, _FIELDS)
    return all(spec.name in table for spec in specs)


# ----------------------------------------------------------------------
# Combining what several classes stand for
# ----------------------------------------------------------------------


def conjoin(
    clsname: str,
    own: tx.Tuple[_Spec, ...],
    inherited: tx.Sequence[tx.Tuple[type, tx.Tuple[_Spec, ...]]],
) -> tx.Tuple[_Spec, ...]:
    """
    What a class that inherits from several registered classes stands for.

    `own` is what the class says itself, and `inherited` what each of
    the registered classes it inherits from stands for, in MRO order. A
    value has to satisfy all of it, so the constraints on one field are
    combined into one that asks for every one of them. A field is listed
    where it is first mentioned.

    One constraint can reach the combination along two branches of the
    hierarchy -- a class that already combines two others brings their
    constraints with it -- and counts once. A combination that provably
    no value satisfies is refused here, when the class is written: two
    different exact values, or a value (or every value of a set) that
    the other side's value, set, pattern or type turns down. A callable
    is never asked at this point: it is combined, and asked at run time.
    """
    merged: tx.Dict[str, tx.Tuple[_Spec, tx.List[str]]] = {}
    sources = [("its own on=", own)]
    sources += [(base.__name__, specs) for base, specs in inherited]
    for source, specs in sources:
        for spec in specs:
            for part in spec.parts:
                _merge_part(clsname, merged, source, part)
    return tuple(spec for spec, _ in merged.values())


def _merge_part(
    clsname: str,
    merged: tx.Dict[str, tx.Tuple[_Spec, tx.List[str]]],
    source: str,
    part: _Spec,
) -> None:
    # Add one written constraint, coming from `source`, to what the
    # combination asks of its field.
    found = merged.get(part.name)
    if found is None:
        merged[part.name] = (part, [source])
        return
    current, whose = found
    if any(part is known for known in current.parts):
        return
    # A bare `...` asks only that the value be there, which every other
    # constraint asks already.
    if part.validate is None:
        return
    if current.validate is None:
        merged[part.name] = (part, [source])
        return
    both = _both(clsname, current, part, whose, source)
    merged[part.name] = (
        both, whose if source in whose else whose + [source]
    )


def _candidates(spec: _Spec) -> tx.Optional[tx.Tuple[tx.Any, ...]]:
    # Every value `spec` accepts, when there are finitely many known ones.
    if spec.value is not MISSING:
        return (spec.value,)
    return spec.members


def _both(
    clsname: str,
    first: _Spec,
    second: _Spec,
    whose: tx.Sequence[str],
    source: str,
) -> _Spec:
    # One constraint asking for both `first` and `second`.
    #
    # When one side accepts finitely many known values, each is put to
    # the other side's constraints -- but only to the ones that can be
    # asked at build time: an exact value, a set, a pattern or a type. A
    # question the author wrote as a callable may depend on state that
    # is only there at run time, so it is combined and left to be asked
    # then, and never used to refuse the class or to drop a value.
    candidates, other = _candidates(first), second
    if candidates is None:
        candidates, other = _candidates(second), first
    members = candidates
    if candidates is not None:
        judges = [part for part in other.parts if part.precision > _LOOSE]
        members = tuple(
            value for value in candidates
            if all(judge.matches(value) for judge in judges)
        )
        if not members:
            name = first.name
            raise TypeError(
                f"Nothing can build {clsname}: it stands for "
                f"{name}={first.text} through {' and '.join(whose)}, and "
                f"for {name}={second.text} through {source}, and no value "
                f"of {name!r} is both. Write on=None on {clsname} to leave "
                f"it out of the choice, or have it inherit from only one "
                f"of them."
            )
    exact = (
        first if first.value is not MISSING
        else second if second.value is not MISSING
        else None
    )
    if exact is not None:
        members = None
    # Two equal exact values say one thing, and read as it once.
    text = (
        first.text
        if first.value is not MISSING and second.value is not MISSING
        else f"{first.text} and {second.text}"
    )
    first_matches, second_matches = first.matches, second.matches
    first_validate, second_validate = first.validate, second.validate

    def validate(value: tx.Any) -> tx.Any:
        return second_validate(first_validate(value))

    return _Spec(
        first.name,
        _guarded(
            lambda value: first_matches(value) and second_matches(value)
        ),
        max(first.precision, second.precision),
        MISSING if exact is None else exact.value,
        text,
        _conjoined_type(first, second, exact, members),
        validate,
        members,
        first.parts + second.parts,
    )


def _conjoined_type(
    first: _Spec,
    second: _Spec,
    exact: tx.Optional[_Spec],
    members: tx.Optional[tx.Tuple[tx.Any, ...]],
) -> MaybeMissing[tx.Any]:
    # The type a field standing for both would be narrowed to: the exact
    # value's `Literal`, else a `Literal` of the values both accept, else
    # whatever the more precise side narrows to (the earlier one on a
    # tie), else nothing.
    if exact is not None and exact.narrowed is not MISSING:
        return exact.narrowed
    if members and all(_literal_legal(member) for member in members):
        return tx.Literal[members]
    ranked = sorted((first, second), key=lambda spec: -spec.precision)
    for spec in ranked:
        if spec.narrowed is not MISSING:
            return spec.narrowed
    return MISSING


# ----------------------------------------------------------------------
# Where a value comes from
# ----------------------------------------------------------------------


class _Discriminant:
    """Where one constrained field's value arrives, on one class."""

    __slots__ = ("name", "public", "position", "keyword", "default",
                 "convert", "convert_default")

    def __init__(
        self,
        name: str,
        public: str,
        position: tx.Optional[int],
        keyword: bool,
        default: MaybeMissing[tx.Any],
        convert: tx.Optional[tx.Callable[[tx.Any], tx.Any]],
        convert_default: tx.Optional[tx.Callable[[tx.Any], tx.Any]],
    ) -> None:
        self.name = name
        self.public = public
        self.position = position
        self.keyword = keyword
        self.default = default
        #: What converts a value the caller passed, and what converts
        #: the field's own default -- which are not always the same
        #: thing: a class written `convert_defaults=False` stores its
        #: defaults unconverted, and choosing a subclass has to go on
        #: the value the instance will really hold.
        self.convert = convert
        self.convert_default = convert_default


def _generated_init(cls: type) -> bool:
    # Whether the `__init__` Python will call for this class is one
    # Magic wrote. A hand-written one takes its arguments in whatever
    # order it likes, so nothing can be read out of `args` by position.
    # Every class has `object.__init__` behind it, so there is always
    # one to find.
    owner = next(
        base for base in cls.__mro__ if "__init__" in base.__dict__
    )
    return "__init__" in (owner.__dict__.get(_GENERATED) or {})


def discriminants(
    cls: type, names: tx.Iterable[str]
) -> tx.Tuple[_Discriminant, ...]:
    """Work out, once, where each of `names` arrives on `cls`."""
    table = getattr(cls, _FIELDS)
    # A positional-only field comes first in the signature, whatever
    # order it was declared in -- the same order `__init__` is built in.
    positional = [field for field in table.values() if field.positional]
    order = [field for field in positional if not field.kw]
    order += [field for field in positional if field.kw]
    places = {field.name: index for index, field in enumerate(order)}
    by_position = _generated_init(cls)
    converts_defaults = getattr(
        getattr(cls, _OPTIONS, None), "convert_defaults", True
    )

    found = []
    for name in names:
        field = table[name]
        default = field.default
        if field.build:
            # A factory default is built once per instance, and building
            # it here to read it would build it twice. A field defaulted
            # that way is read as absent when it is not passed.
            default = MISSING
        convert = field.converter if field.convert else None
        found.append(_Discriminant(
            name,
            field.public_name,
            places.get(field.name) if by_position else None,
            bool(field.kw),
            default,
            convert,
            convert if converts_defaults else None,
        ))
    return tuple(found)


def _read(
    discriminant: _Discriminant,
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> MaybeMissing[tx.Any]:
    # A keyword-only field is never read out of `args`, and a
    # positional-only one never out of `kwargs`: reading either the
    # wrong way round would quietly hand back a neighbour's value.
    if discriminant.keyword and discriminant.public in kwargs:
        value, convert = kwargs[discriminant.public], discriminant.convert
    elif (
        discriminant.position is not None
        and discriminant.position < len(args)
    ):
        value, convert = args[discriminant.position], discriminant.convert
    else:
        # A default is as good as a value the caller wrote out: the two
        # spellings of one call must build the same class. It is
        # converted the way the class converts its defaults, which is
        # not always the way it converts what it is passed.
        value, convert = discriminant.default, discriminant.convert_default
    if value is MISSING or convert is None:
        return value
    try:
        return convert(value)
    except Exception:
        # The value is not one this field accepts. Matching goes on with
        # what was passed, and `__init__` says what is wrong with it.
        return value


def read(
    found: tx.Tuple[_Discriminant, ...],
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> tx.Dict[str, tx.Any]:
    """The value of every constrained field, for one call."""
    return {d.name: _read(d, args, kwargs) for d in found}


# ----------------------------------------------------------------------
# The registry a polymorphic class carries
# ----------------------------------------------------------------------


class _Plan:
    """How the owner re-spells a delegated call for one subclass.

    Most subclasses take exactly what the owner takes, so the owner
    hands the call straight on -- `target(*args, **kwargs)` -- and needs
    no plan. A subclass that does *not* take one of its discriminants
    (it holds the value as a class attribute or a non-init default
    instead) needs that argument taken back out before the owner calls
    it, and its positional arguments re-spelled by name around the gap.
    """

    __slots__ = ("positions", "positional_only", "drops")

    def __init__(
        self,
        positions: tx.Tuple[str, ...],
        positional_only: int,
        drops: tx.FrozenSet[str],
    ) -> None:
        #: The owner's positional parameters, by public name, in the
        #: order they are passed -- so a positional argument can be
        #: matched to the name it fills.
        self.positions = positions
        #: How many of those lead a positional-only run, which stays
        #: positional because it cannot be passed by name.
        self.positional_only = positional_only
        #: The public names to drop before calling the subclass, which
        #: does not take them.
        self.drops = drops


def _delegation_plan(
    owner: type, target: type, specs: tx.Tuple[_Spec, ...]
) -> tx.Optional[_Plan]:
    # What the owner must do differently to build `target`, or None when
    # it can hand the call straight on. Only a discriminant the owner
    # takes but the target does not needs anything: it has to come out
    # of the call, and the positional arguments re-spelled around it. A
    # target whose `__init__` is hand-written takes its arguments however
    # it likes, so nothing can be re-spelled and the call goes verbatim.
    if not _generated_init(target):
        return None
    owner_fields = getattr(owner, _FIELDS)
    target_fields = getattr(target, _FIELDS)
    drops = []
    for spec in specs:
        owner_field = owner_fields.get(spec.name)
        target_field = target_fields.get(spec.name)
        if owner_field is None or target_field is None:  # pragma: no cover
            # Defensive: a spec name is validated against the owner's
            # fields, and the target is a subclass carrying all of them,
            # so neither lookup misses.
            continue
        if owner_field.init and not target_field.init:
            drops.append(owner_field.public_name)
    if not drops:
        return None
    positional = [f for f in owner_fields.values() if f.positional]
    order = [f for f in positional if not f.kw]
    order += [f for f in positional if f.kw]
    positions = tuple(f.public_name for f in order)
    positional_only = sum(1 for f in order if not f.kw)
    return _Plan(positions, positional_only, frozenset(drops))


class _Polymorph:
    """One subclass, and what it stands for."""

    __slots__ = ("target", "specs", "rank", "respell")

    def __init__(
        self,
        target: type,
        specs: tx.Tuple[_Spec, ...],
        priority: int,
        depth: int,
        respell: tx.Optional[_Plan] = None,
        ranked: tx.Optional[tx.Tuple[_Spec, ...]] = None,
    ) -> None:
        self.target = target
        self.specs = specs
        #: How strong a claim this is, worked out once because none of
        #: it can change: an explicit priority first, then the number
        #: of fields the claim covers, then how precise those
        #: constraints are, then how far down the class hierarchy the
        #: subclass sits -- so refining an existing subclass does not
        #: need a narrower `on=`.
        #:
        #: The claim measured is `ranked`, everything the subclass
        #: stands for -- what it registered and what the registered
        #: classes above it stand for -- rather than `specs`, the part
        #: of it this owner has left to check. Two subclasses reaching
        #: one owner along different paths may have left different
        #: amounts to check, and only the whole claim compares fairly.
        claim = specs if ranked is None else ranked
        self.rank = (
            priority,
            len(claim),
            sum(spec.precision for spec in claim),
            depth,
        )
        #: How the owner re-spells the call to build this subclass, or
        #: None to hand it straight on.
        self.respell = respell

    def standing_for(self, target: type) -> "_Polymorph":
        """This registration, with `target` answering for it instead.

        The rank is kept: `Sub[int]` stands for the same claim `Sub`
        registered, and sits at the same place in the hierarchy as far
        as the choice is concerned. The re-spelling plan is kept too:
        filling in type parameters changes neither which arguments the
        subclass takes nor the order the owner passes them in.
        """
        made = _Polymorph.__new__(_Polymorph)
        made.target = target
        made.specs = self.specs
        made.rank = self.rank
        made.respell = self.respell
        return made

    def matches(self, values: tx.Mapping[str, tx.Any]) -> bool:
        for spec in self.specs:
            value = values[spec.name]
            if value is MISSING or not spec.matches(value):
                return False
        return True

    def __str__(self) -> str:
        written = ", ".join(
            f"{spec.name}={spec.text}" for spec in self.specs
        )
        return f"{self.target.__name__}({written})"


class _Registry:
    """What a class knows about building something other than itself."""

    __slots__ = ("dispatch", "invariant", "strict", "required")

    def __init__(self, strict: bool, required: bool) -> None:
        #: The registered subclasses, where each constrained field
        #: arrives, and the ones left out -- as one value. Rebuilt
        #: whole and stored in a single assignment, so a construction
        #: on another thread reads either the state before a
        #: registration or the state after it, never entries whose
        #: fields the reader has no place to look up. Only a
        #: parameterised class leaves any out.
        self.dispatch = ((), (), ())
        #: This class's own registration, read back on the way in, so
        #: that building it directly with a contradicting value can be
        #: refused. Only kept under `polymorphic="strict"`.
        self.invariant = None
        #: Refuse to build this class when nothing matches.
        self.strict = strict
        #: Refuse even when nothing has registered yet. A strict class
        #: that something else builds -- a leaf of the hierarchy -- is
        #: exempt: it has to stay buildable, since being built is the
        #: whole point of having been registered.
        self.required = required

    def add(
        self,
        owner: type,
        target: type,
        specs: tx.Tuple[_Spec, ...],
        priority: int,
        ranked: tx.Optional[tx.Tuple[_Spec, ...]] = None,
    ) -> None:
        """Have `owner` build `target` for the arguments `specs` describe."""
        entry = _Polymorph(
            target, specs, priority, target.__mro__.index(owner),
            _delegation_plan(owner, target, specs), ranked,
        )
        entries = _replacing(self.dispatch[0], entry)
        self.dispatch = (
            entries, discriminants(owner, _constrained(entries)), ()
        )


def _replacing(
    entries: tx.Tuple[_Polymorph, ...], entry: _Polymorph
) -> tx.Tuple[_Polymorph, ...]:
    # `entries` with `entry` added, and any earlier registration of the
    # same class dropped. A class registering a second time -- a
    # reloaded module, a decorator applied twice -- replaces its entry
    # rather than adding one that would then tie with itself. Same name
    # in the same module is the same registration, whether or not it is
    # the same object.
    same = (entry.target.__module__, entry.target.__qualname__)
    kept = [
        other for other in entries
        if (other.target.__module__, other.target.__qualname__) != same
    ]
    kept.append(entry)
    return tuple(kept)


def _constrained(entries: tx.Iterable[_Polymorph]) -> tx.List[str]:
    # Every field any of these registrations mentions, in the order
    # they were first mentioned.
    names = []
    for entry in entries:
        for spec in entry.specs:
            if spec.name not in names:
                names.append(spec.name)
    return names


def _setting(cls: type) -> tx.Tuple[bool, bool]:
    # What this class's own `polymorphic` setting asks of its registry.
    strict = getattr(
        getattr(cls, _OPTIONS, None), "polymorphic", False
    ) == "strict"
    return strict, strict and _REGISTRATION not in cls.__dict__


class _Parameterised:
    """The registry of a class built by filling a generic's parameters in.

    `Box[int]` chooses between the subclasses registered with `Box` --
    including the ones registered after it was built -- and answers for
    each with its own parameters filled in the same way, so `Box[int]`
    hands back a `Sub[int]`. A subclass that fills them in differently,
    `class Sub(Box[str], on=...)` where `Box[int]` was asked for, is
    left out, and is named in the error when nothing matches.

    It stands in for a `_Registry` and is read the same way. Nothing is
    registered here: it is a view of the origin's registrations, as
    they stand at the call.
    """

    __slots__ = ("cls", "origin", "arguments", "strict", "unarmed",
                 "inherited", "view", "rule", "checked")

    def __init__(
        self,
        cls: type,
        origin: type,
        arguments: tx.Tuple,
        strict: bool,
        required: bool,
    ) -> None:
        self.cls = cls
        self.origin = origin
        self.arguments = arguments
        self.strict = strict
        #: Whether to refuse when nothing has registered, for as long as
        #: the origin has no registry of its own to say so.
        self.unarmed = required
        #: The origin's invariant this class's was worked out from, and
        #: this class's -- kept for the same reason as the view below.
        self.rule = None
        self.checked = None
        #: The origin's entries this view was made from, and the view
        #: itself. The origin publishes its entries in a single
        #: assignment, so holding on to that tuple is enough to tell
        #: that nothing has registered since.
        self.inherited = None
        self.view = None

    @property
    def required(self) -> bool:
        # Read off the origin on every call, like the entries: the origin
        # stops being required when it is registered by hand, which can
        # happen after this class was built.
        found = self.origin.__dict__.get(_POLYMORPHS)
        return self.unarmed if found is None else found.required

    @property
    def invariant(self) -> tx.Optional[tx.Tuple]:
        # The origin's own constraints, with where each field arrives
        # worked out against this class. Read live for the same reason
        # `required` is, and worked out again only when the origin's
        # changes.
        found = self.origin.__dict__.get(_POLYMORPHS)
        rule = None if found is None else found.invariant
        if rule is None:
            return None
        if rule is not self.rule:
            specs = rule[0]
            self.checked = (
                specs,
                discriminants(self.cls, [spec.name for spec in specs]),
            )
            self.rule = rule
        return self.checked

    @property
    def dispatch(self) -> tx.Tuple:
        found = self.origin.__dict__.get(_POLYMORPHS)
        inherited = found.dispatch[0] if found is not None else ()
        if inherited is self.inherited:
            return self.view
        entries, left_out = [], []
        for entry in inherited:
            target = fill_in(entry.target, self.origin, self.arguments)
            if target is None:
                # It stands for other type arguments than these.
                left_out.append(entry)
                continue
            entries.append(
                entry if target is entry.target else entry.standing_for(target)
            )
        entries = tuple(entries)
        # Where each constrained field arrives is worked out against this
        # class, whose fields carry the filled-in types -- so a value is
        # converted the way the instance will really hold it.
        view = (
            entries,
            discriminants(self.cls, _constrained(entries)),
            tuple(left_out),
        )
        # The view is published before the entries it was made from, so
        # that a reader that finds them unchanged finds the view made.
        self.view = view
        self.inherited = inherited
        return view


def arm_parameterised(
    cls: type, origin: type, arguments: tx.Tuple
) -> None:
    """Have `cls` choose between the subclasses `origin` chooses between.

    `cls` is `origin` with its type parameters filled in with
    `arguments`. It is given a registry of its own, reading the
    origin's, rather than sharing it: where each constrained field
    arrives has to be worked out against the filled-in fields.
    """
    found = origin.__dict__.get(_POLYMORPHS)
    if found is None:
        strict, required = _setting(cls)
    else:
        # Not `cls`'s own reading of the setting: `Sub[int]` has to
        # stay as buildable as `Sub` is, and only `Sub` carries the
        # registration that says so.
        strict, required = found.strict, found.required
    setattr(
        cls, _POLYMORPHS,
        _Parameterised(cls, origin, arguments, strict, required),
    )


#: Either kind of registry: the one an ordinary polymorphic class
#: carries, and the one a class built by filling in type parameters
#: carries. They are read the same way.
_Registries = tx.Union[_Registry, _Parameterised]


def registry(cls: type) -> _Registries:
    """This class's own registry, made if it has none yet.

    Never an inherited one: a subclass answers for the subclasses
    registered with *it*.
    """
    found = cls.__dict__.get(_POLYMORPHS)
    if found is None:
        found = _Registry(*_setting(cls))
        setattr(cls, _POLYMORPHS, found)
    return found


def arm(cls: type, specs: tx.Optional[tx.Tuple[_Spec, ...]]) -> None:
    """Give a strict class the registry its own setting calls for.

    It needs one before any subclass has registered, or the setting
    would do nothing at all until the module holding the first subclass
    happened to be imported -- which is the very case it exists to
    report. When the class is itself registered somewhere, its own
    constraints are kept here too, so that building it directly with a
    value that contradicts them can be refused.
    """
    found = registry(cls)
    if specs is not None:
        found.invariant = (
            specs, discriminants(cls, [spec.name for spec in specs])
        )


def mark_registered(
    owner: type,
    target: type,
    specs: tx.Tuple[_Spec, ...],
    priority: int,
    ranked: tx.Tuple[_Spec, ...],
) -> None:
    """Record on `target` that it was registered by hand with `owner`.

    A class statement's `on=` leaves this record behind itself; a
    registration made afterwards has to write it. Two things read it: a
    later subclass of `target`, which then knows `target` is reached from
    above and registers with it rather than climbing past it; and a
    strict `target`, which stops refusing to be built on its own -- being
    built is the whole point of having been registered -- and refuses a
    direct call that contradicts what it was registered for instead.

    A class that already carries a record keeps it, and a class built by
    filling in type parameters is left alone: its origin is the one
    registered.
    """
    if _REGISTRATION in target.__dict__ or _GENERIC_ORIGIN in target.__dict__:
        return
    setattr(target, _REGISTRATION, ((owner,), specs, priority, ranked))
    found = target.__dict__.get(_POLYMORPHS)
    if found is not None and found.strict:
        found.required = False
        arm(target, specs)


def register(
    owner: type,
    target: type,
    specs: tx.Tuple[_Spec, ...],
    priority: int,
    ranked: tx.Optional[tx.Tuple[_Spec, ...]] = None,
) -> None:
    """Have `owner` build `target` for the arguments `specs` describe.

    `ranked` is everything `target` stands for, which is what its rank
    among the other candidates is measured on; `specs` when left out.
    """
    if not (isinstance(target, type) and issubclass(target, owner)):
        raise TypeError(
            f"{owner.__name__} can only build its own subclasses, and "
            f"{getattr(target, '__name__', target)!r} is not one."
        )
    if target is owner:
        raise TypeError(
            f"{owner.__name__} cannot be registered against itself: it is "
            f"already what a call to it builds when nothing else matches."
        )
    if target.__dict__.get(_GENERIC_ORIGIN) is owner:
        raise TypeError(
            f"{target.__name__} is {owner.__name__} with its type "
            f"parameters filled in, not one of the subclasses it chooses "
            f"between. {owner.__name__} already builds it for those type "
            f"arguments: register the subclass you want it to build "
            f"instead."
        )
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise TypeError(
            f"the priority of {target.__name__} is {priority!r}, and a "
            f"priority is a whole number: the subclass with the highest "
            f"one wins when two match equally well."
        )
    registry(owner).add(owner, target, specs, priority, ranked)


# ----------------------------------------------------------------------
# Choosing
# ----------------------------------------------------------------------


def as_written(cls: type) -> str:
    """The name of `cls` as the author of the class wrote it.

    A class built by filling in type parameters is named `Box[int]`,
    which says what was built but is not a name anything can be
    declared under -- so a message telling someone what to write names
    `Box`.
    """
    return cls.__dict__.get(_GENERIC_ORIGIN, cls).__name__


def _written(values: tx.Mapping[str, tx.Any]) -> str:
    """The arguments dispatch went on, said the way they were passed."""
    written = ", ".join(
        f"{name}={value!r}"
        for name, value in values.items()
        if value is not MISSING
    )
    return written or "nothing it was given"


def select(
    cls: type,
    found: _Registries,
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> tx.Optional["_Polymorph"]:
    """
    Which subclass of `cls` to build, or `None` to build `cls` itself.

    The whole registration is handed back, not just the class, so the
    caller can re-spell the delegated call the way the subclass needs.
    """
    entries, where, left_out = found.dispatch
    values = read(where, args, kwargs)
    candidates = [entry for entry in entries if entry.matches(values)]
    if not candidates:
        # An abstract class cannot stand in for the subclass that was
        # not found: falling through would raise Python's own "can't
        # instantiate", which says nothing about the choice that was
        # being made.
        abstract = getattr(cls, "__abstractmethods__", None)
        if found.strict or abstract:
            raise NoPolymorphError(
                _nothing_matched(cls, entries, left_out, values,
                                 bool(abstract))
            )
        return None
    best = max(candidates, key=lambda entry: entry.rank)
    tied = [
        entry for entry in candidates
        if entry is not best and entry.rank == best.rank
    ]
    if tied:
        names = ", ".join(
            sorted([best.target.__name__]
                   + [entry.target.__name__ for entry in tied])
        )
        raise AmbiguousPolymorphError(
            f"{cls.__name__}({_written(values)}) matches {names} equally "
            f"well, and there is nothing to choose between them. Say which "
            f"one wins by giving it a higher priority -- "
            f"`class {as_written(best.target)}({as_written(cls)}, "
            f"on={{...}}, priority=1)`."
        )
    return best


def delegate(
    cls: type,
    entry: "_Polymorph",
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> tx.Any:
    """Build `entry.target`, re-spelling the call when it takes less.

    The common case -- the subclass takes exactly what the owner takes
    -- hands the call straight on. When the subclass does not take one of
    its discriminants, that argument is taken back out and the positional
    arguments are re-spelled by name around the gap, so the leftover
    positional-only run stays positional and everything else is passed by
    name.
    """
    plan = entry.respell
    target = entry.target
    if plan is None:
        return target(*args, **kwargs)
    # More positional arguments than the owner takes never bind to a
    # name, so re-spelling them by name would drop them silently -- the
    # verbatim path raises, and so must this one.
    if len(args) > len(plan.positions):
        raise TypeError(
            f"{as_written(cls)}() takes {len(plan.positions)} positional "
            f"arguments but {len(args)} were given"
        )
    leading = args[: plan.positional_only]
    bound: tx.Dict[str, tx.Any] = {}
    for name, value in zip(
        plan.positions[plan.positional_only:], args[plan.positional_only:]
    ):
        bound[name] = value
    for name, value in kwargs.items():
        if name in bound:
            raise TypeError(
                f"{as_written(cls)}() got multiple values for argument "
                f"{name!r}"
            )
        bound[name] = value
    for name in plan.drops:
        bound.pop(name, None)
    return target(*leading, **bound)


def _nothing_matched(
    cls: type,
    entries: tx.Tuple[_Polymorph, ...],
    left_out: tx.Tuple[_Polymorph, ...],
    values: tx.Mapping[str, tx.Any],
    abstract: bool,
) -> str:
    why = (
        f"{cls.__name__} is abstract, so it can only be built as one of "
        f"the subclasses registered with it"
        if abstract else
        f"{cls.__name__} only builds one of the subclasses registered "
        f"with it"
    )
    # A subclass written for other type arguments than the ones asked
    # for is registered, and still cannot be built here -- so saying
    # nothing about it would send the reader looking for an import that
    # has already happened.
    standing_elsewhere = ", ".join(
        sorted(entry.target.__name__ for entry in left_out)
    )
    if not entries:
        if left_out:
            return (
                f"{why}, and the ones that have registered stand for "
                f"other type arguments than {cls.__name__} was asked "
                f"for: {standing_elsewhere}."
            )
        # Nothing has registered, so there are no constrained fields
        # and nothing to say about the arguments.
        return (
            f"{why}, and none has yet: the module holding the subclass "
            f"you expect has not been imported."
        )
    considered = "\n".join(f"  - {entry}" for entry in entries)
    aside = (
        f"\n{standing_elsewhere} stand for other type arguments than "
        f"{cls.__name__} was asked for, and were left out."
        if left_out else ""
    )
    return (
        f"{why}, and none of them matches {_written(values)}. It "
        f"considered:\n{considered}{aside}\nIf the one you expected is "
        f"not in that list, the module it is written in has not been "
        f"imported."
    )


def check(
    cls: type,
    found: _Registries,
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> None:
    """Refuse a call to `cls` that contradicts what it registered for."""
    specs, where = found.invariant
    values = read(where, args, kwargs)
    for spec in specs:
        value = values[spec.name]
        if value is MISSING or spec.matches(value):
            continue
        raise PolymorphError(
            f"{cls.__name__} is what {spec.name}={spec.text} builds, so "
            f"{spec.name}={value!r} contradicts it. Build the class that "
            f"value belongs to instead."
        )
