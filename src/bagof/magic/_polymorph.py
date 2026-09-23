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

# dependencies
import typing_extensions as tx
from bagof.validators import Validator

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

    def standing_for(self, target: type) -> "_Polymorph":
        """This registration, with `target` answering for it instead.

        The rank is kept: `Sub[int]` stands for the same claim `Sub`
        registered, and sits at the same place in the hierarchy as far
        as the choice is concerned.
        """
        made = _Polymorph.__new__(_Polymorph)
        made.target = target
        made.specs = self.specs
        made.rank = self.rank
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
    ) -> None:
        """Have `owner` build `target` for the arguments `specs` describe."""
        entry = _Polymorph(
            target, specs, priority, target.__mro__.index(owner)
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

    __slots__ = ("cls", "origin", "arguments", "invariant", "strict",
                 "required", "inherited", "view")

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
        self.invariant = None
        self.strict = strict
        self.required = required
        #: The origin's entries this view was made from, and the view
        #: itself. The origin publishes its entries in a single
        #: assignment, so holding on to that tuple is enough to tell
        #: that nothing has registered since.
        self.inherited = None
        self.view = None

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
    made = _Parameterised(cls, origin, arguments, strict, required)
    if found is not None and found.invariant is not None:
        specs = found.invariant[0]
        made.invariant = (
            specs, discriminants(cls, [spec.name for spec in specs])
        )
    setattr(cls, _POLYMORPHS, made)


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
    registry(owner).add(owner, target, specs, priority)


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
) -> tx.Optional[type]:
    """
    Which subclass of `cls` to build, or `None` to build `cls` itself.
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
    return best.target


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
