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
"""

from __future__ import annotations

__all__ = [
    "PolymorphError",
    "NoPolymorphError",
    "AmbiguousPolymorphError",
]

# dependencies
import typing_extensions as tx
from bagof.validators import Validator

# internals
from ._constants import (
    _FIELDS,
    _GENERATED,
    _OPTIONS,
    _POLYMORPHS,
    _REGISTRATION,
    MISSING,
    MaybeMissing,
)

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

    __slots__ = ("name", "matches", "precision", "value", "text")

    def __init__(
        self,
        name: str,
        matches: tx.Callable[[tx.Any], bool],
        precision: int,
        value: MaybeMissing[tx.Any],
        text: str,
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
        return (lambda value: value in spec), _MEMBER, MISSING, repr(spec)
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


def _specification(name: str, spec: tx.Any) -> _Spec:
    """Read one value of an `on={...}` mapping."""
    matches, precision, value, text = _shape(spec)
    return _Spec(name, _guarded(matches), precision, value, text)


def specifications(
    owner: type, clsname: str, on: tx.Mapping[str, tx.Any]
) -> tx.Tuple[_Spec, ...]:
    """
    Read a whole `on={...}` mapping against the class registering with.

    Its keys name fields the way `owner` declares them, and a name that
    is no field of `owner` is refused here -- when the class is written,
    rather than the first time something is built.
    """
    if not isinstance(on, tx.Mapping):
        raise TypeError(
            f"on= takes a mapping of field names to the values "
            f"{clsname} stands for, such as on={{'mode': 'minor'}}, "
            f"and was given {on!r}."
        )
    table = getattr(owner, _FIELDS)
    specs = []
    for name, spec in on.items():
        if name not in table:
            raise TypeError(
                f"{clsname} registers on {name!r}, which is not a field of "
                f"{owner.__name__}. Its fields are: "
                f"{', '.join(repr(field) for field in table) or 'none'}."
            )
        specs.append(_specification(name, spec))
    return tuple(specs)


# ----------------------------------------------------------------------
# Where a value comes from
# ----------------------------------------------------------------------


class _Discriminant:
    """Where one constrained field's value arrives, on one class."""

    __slots__ = ("name", "public", "position", "keyword", "default",
                 "convert")

    def __init__(
        self,
        name: str,
        public: str,
        position: tx.Optional[int],
        keyword: bool,
        default: MaybeMissing[tx.Any],
        convert: tx.Optional[tx.Callable[[tx.Any], tx.Any]],
    ) -> None:
        self.name = name
        self.public = public
        self.position = position
        self.keyword = keyword
        self.default = default
        self.convert = convert


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

    found = []
    for name in names:
        field = table[name]
        default = field.default
        if field.factory:
            # A factory default is built once per instance, and building
            # it here to read it would build it twice. A field defaulted
            # that way is read as absent when it is not passed.
            default = MISSING
        found.append(_Discriminant(
            name,
            field.public_name,
            places.get(field.name) if by_position else None,
            bool(field.kw),
            default,
            field.converter or None,
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
        value = kwargs[discriminant.public]
    elif (
        discriminant.position is not None
        and discriminant.position < len(args)
    ):
        value = args[discriminant.position]
    else:
        # A default is as good as a value the caller wrote out: the two
        # spellings of one call must build the same class.
        value = discriminant.default
    if value is MISSING or discriminant.convert is None:
        return value
    try:
        return discriminant.convert(value)
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


class _Polymorph:
    """One subclass, and what it stands for."""

    __slots__ = ("target", "specs", "rank")

    def __init__(
        self,
        target: type,
        specs: tx.Tuple[_Spec, ...],
        priority: int,
        depth: int,
    ) -> None:
        self.target = target
        self.specs = specs
        #: How strong a claim this is, worked out once because none of
        #: it can change: an explicit priority first, then the number
        #: of fields the claim covers, then how precise those
        #: constraints are, then how far down the class hierarchy the
        #: subclass sits -- so refining an existing subclass does not
        #: need a narrower `on=`.
        self.rank = (
            priority,
            len(specs),
            sum(spec.precision for spec in specs),
            depth,
        )

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
        #: The registered subclasses, and where each constrained field
        #: arrives, as one value. Rebuilt whole and stored in a single
        #: assignment, so a construction on another thread reads either
        #: the state before a registration or the state after it, never
        #: entries whose fields the reader has no place to look up.
        self.dispatch = ((), ())
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


def registry(cls: type) -> _Registry:
    """This class's own registry, made if it has none yet.

    Never an inherited one: a subclass answers for the subclasses
    registered with *it*.
    """
    found = cls.__dict__.get(_POLYMORPHS)
    if found is None:
        strict = getattr(
            getattr(cls, _OPTIONS, None), "polymorphic", False
        ) == "strict"
        found = _Registry(strict, strict and _REGISTRATION not in cls.__dict__)
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


def register(
    owner: type,
    target: type,
    specs: tx.Tuple[_Spec, ...],
    priority: int,
) -> None:
    """Have `owner` build `target` for the arguments `specs` describe."""
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
    if not isinstance(priority, int) or isinstance(priority, bool):
        raise TypeError(
            f"the priority of {target.__name__} is {priority!r}, and a "
            f"priority is a whole number: the subclass with the highest "
            f"one wins when two match equally well."
        )
    entry = _Polymorph(
        target, specs, priority, target.__mro__.index(owner)
    )
    found = registry(owner)
    entries, _ = found.dispatch
    # A class registering a second time -- a reloaded module, a
    # decorator applied twice -- replaces its entry rather than adding
    # one that would then tie with itself. Same name in the same module
    # is the same registration, whether or not it is the same object.
    same = (target.__module__, target.__qualname__)
    entries = [
        kept for kept in entries
        if (kept.target.__module__, kept.target.__qualname__) != same
    ]
    entries.append(entry)
    names = []
    for kept in entries:
        for spec in kept.specs:
            if spec.name not in names:
                names.append(spec.name)
    found.dispatch = (tuple(entries), discriminants(owner, names))


# ----------------------------------------------------------------------
# Choosing
# ----------------------------------------------------------------------


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
    found: _Registry,
    args: tx.Tuple[tx.Any, ...],
    kwargs: tx.Dict[str, tx.Any],
) -> tx.Optional[type]:
    """
    Which subclass of `cls` to build, or `None` to build `cls` itself.
    """
    entries, where = found.dispatch
    values = read(where, args, kwargs)
    candidates = [entry for entry in entries if entry.matches(values)]
    if not candidates:
        # An abstract class cannot stand in for the subclass that was
        # not found: falling through would raise Python's own "can't
        # instantiate", which says nothing about the choice that was
        # being made.
        abstract = getattr(cls, "__abstractmethods__", None)
        if found.strict or abstract:
            raise NoPolymorphError(_nothing_matched(cls, entries, values,
                                                    bool(abstract)))
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
            f"`class {best.target.__name__}({cls.__name__}, on={{...}}, "
            f"priority=1)`."
        )
    return best.target


def _nothing_matched(
    cls: type,
    entries: tx.Tuple[_Polymorph, ...],
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
    if not entries:
        # Nothing has registered, so there are no constrained fields
        # and nothing to say about the arguments.
        return (
            f"{why}, and none has yet: the module holding the subclass "
            f"you expect has not been imported."
        )
    considered = "\n".join(f"  - {entry}" for entry in entries)
    return (
        f"{why}, and none of them matches {_written(values)}. It "
        f"considered:\n{considered}\nIf the one you expected is not in "
        f"that list, the module it is written in has not been imported."
    )


def check(
    cls: type,
    found: _Registry,
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
