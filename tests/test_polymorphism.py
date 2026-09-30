"""Building one class and getting back one of its subclasses.

A `polymorphic` class chooses which of its subclasses to build from the
arguments it was given. What is worth testing is less the happy path
than the four places this kind of feature usually goes wrong: an answer
that depends on import order, an argument read out of the wrong slot,
a hierarchy more than two deep, and a copy that quietly rebuilds
something else.
"""

# stdlib
import copy
import pickle
import re
from abc import abstractmethod
from inspect import Parameter, Signature, signature
from typing import Any as TypingAny

# dependencies
import pytest
import typing_extensions as tx
from bagof.converters.exceptions import ConversionError
from bagof.validators import ValueValidationError

# locals
import bagof.magic._generics as g
import bagof.magic._polymorph as p
from bagof.magic import (
    AmbiguousPolymorphError,
    ClassVar,
    ConvertTo,
    Factory,
    KwOnly,
    Magic,
    MetaMagic,
    NoInit,
    NoPolymorphError,
    PolymorphError,
    PositionalOnly,
    asdict,
    field,
    magic,
    replace,
)
from bagof.magic._constants import (
    _FIELDS,
    _PINNED,
    _POLYMORPHS,
    _REGISTRATION,
    MISSING,
)


def _entry_for(base: type, target: type) -> object:
    """The registration `base` holds for `target`, for the tests that
    look at how a call to it is re-spelled."""
    entries = base.__dict__[_POLYMORPHS].dispatch[0]
    return next(entry for entry in entries if entry.target is target)

# ======================================================================
# Classes at module level, for the copies -- pickle can only find a
# class that lives somewhere it can be named.
# ======================================================================


class Chord(Magic, polymorphic=True):
    root: str
    mode: str = "major"


class MinorChord(Chord, on={"mode": "minor"}):
    pass


class HarmonicMinor(MinorChord, on={"root": "A"}):
    pass


_T = tx.TypeVar("_T")
_S = tx.TypeVar("_S")


class Signal(Magic, tx.Generic[_T], polymorphic=True, convert=True):
    kind: str
    value: _T


class Inverse(Signal[_T], on={"kind": "inverse"}):
    pass


# ======================================================================
# The basics
# ======================================================================


class TestDispatch:

    def test_a_matching_subclass_is_built(self) -> None:
        chord = Chord(root="C", mode="minor")
        assert type(chord) is MinorChord
        assert chord.mode == "minor" and chord.root == "C"

    def test_nothing_matching_builds_the_class_itself(self) -> None:
        assert type(Chord(root="C", mode="lydian")) is Chord

    def test_a_class_with_no_registrations_is_untouched(self) -> None:
        class Plain(Magic):
            x: int

        assert type(Plain(1)) is Plain

    def test_positional_and_keyword_agree(self) -> None:
        # The whole feature only half-exists if the two spellings of one
        # call build different classes.
        assert type(Chord("C", "minor")) is type(Chord(root="C", mode="minor"))

    def test_a_subclass_called_directly_does_not_dispatch_upward(
        self
    ) -> None:
        # Calling the subclass is the escape hatch, so it needs no flag.
        assert type(MinorChord(root="C")) is MinorChord

    def test_a_subclass_that_registers_nothing_is_no_candidate(self) -> None:
        class Ninth(MinorChord):
            pass

        assert type(Chord(root="C", mode="minor")) is not Ninth

    def test_the_signature_is_still_the_constructors(self) -> None:
        # Dispatch happens in the metaclass, which is where `inspect`
        # looks first; the answer must still be about the class.
        assert list(signature(Chord).parameters) == ["root", "mode"]


# ======================================================================
# What a constraint may be
# ======================================================================


class TestConstraints:

    @pytest.fixture
    def base(self) -> type:
        class Value(Magic, polymorphic=True):
            v: tx.Any = None
            w: int = 0

        return Value

    def test_an_exact_value(self, base: type) -> None:
        class One(base, on={"v": 1}):
            pass

        assert type(base(v=1)) is One
        assert type(base(v=2)) is base

    def test_a_set_of_values(self, base: type) -> None:
        class Vowel(base, on={"v": {"a", "e"}}):
            pass

        assert type(base(v="a")) is Vowel
        assert type(base(v="z")) is base

    def test_a_regular_expression(self, base: type) -> None:
        class Word(base, on={"v": re.compile(r"[a-z]+")}):
            pass

        assert type(base(v="abc")) is Word
        # `fullmatch`, so a prefix is not enough.
        assert type(base(v="abc1")) is base

    def test_a_type(self, base: type) -> None:
        class Whole(base, on={"v": int}):
            pass

        assert type(base(v=3)) is Whole
        assert type(base(v="3")) is base

    def test_a_typing_form(self, base: type) -> None:
        class Named(base, on={"v": tx.Literal["a", "b"]}):
            pass

        assert type(base(v="b")) is Named
        assert type(base(v="c")) is base

    def test_a_callable(self, base: type) -> None:
        class Big(base, on={"v": lambda v: v > 3}):
            pass

        assert type(base(v=4)) is Big
        assert type(base(v=2)) is base

    def test_presence(self, base: type) -> None:
        class Given(base, on={"v": ...}):
            pass

        # `v` defaults to None, so it is always there to be matched.
        assert type(base()) is Given

    def test_a_field_with_nothing_to_read_is_absent(self) -> None:
        class Maybe(Magic, polymorphic=True):
            a: int = 0
            b: NoInit[tx.Any]

        class Wanted(Maybe, on={"b": ...}):
            pass

        # `b` is no argument and has no default, so there is nothing to
        # read and nothing to match.
        assert type(Maybe()) is Maybe

    def test_every_constraint_must_match(self, base: type) -> None:
        class Both(base, on={"v": int, "w": 2}):
            pass

        assert type(base(v=1)) is base
        assert type(base(v=1, w=2)) is Both

    def test_a_name_that_is_no_field_is_refused_when_written(
        self, base: type
    ) -> None:
        with pytest.raises(TypeError, match="not a field of"):
            class Typo(base, on={"vv": 1}):
                pass

    def test_on_must_be_a_mapping(self, base: type) -> None:
        with pytest.raises(TypeError, match="takes a mapping"):
            class Wrong(base, on=["v"]):
                pass


# ======================================================================
# Choosing between candidates
# ======================================================================


class TestRanking:

    @pytest.fixture
    def base(self) -> type:
        class Tone(Magic, polymorphic=True):
            a: str = "a"
            b: str = "b"

        return Tone

    def test_more_constrained_fields_wins(self, base: type) -> None:
        class One(base, on={"a": "x"}):
            pass

        class Two(base, on={"a": "x", "b": "y"}):
            pass

        assert type(base(a="x", b="y")) is Two
        assert type(base(a="x", b="z")) is One

    def test_a_more_precise_constraint_wins(self, base: type) -> None:
        class Loose(base, on={"a": str}):
            pass

        class Tight(base, on={"a": "x"}):
            pass

        assert type(base(a="x")) is Tight
        assert type(base(a="q")) is Loose

    def test_more_fields_beats_more_precision(self, base: type) -> None:
        # Two constraints worth 3 between them beat one worth 4: how
        # many fields the claim covers is read before how narrow they
        # are, and the two must not be weighed together.
        class Broad(base, on={"a": {"x", "y"}, "b": ...}):
            pass

        class Sharp(base, on={"a": "x"}):
            pass

        assert type(base(a="x", b="b")) is Broad

    def test_a_deeper_subclass_wins(self, base: type) -> None:
        class Outer(base, on={"a": "x"}):
            pass

        class Inner(Outer):
            pass

        base.register_polymorph(Inner, a="x")
        assert type(base(a="x")) is Inner

    def test_priority_beats_everything(self, base: type) -> None:
        class Careful(base, on={"a": "x", "b": "y"}):
            pass

        class Insistent(base, on={"a": "x"}, priority=1):
            pass

        assert type(base(a="x", b="y")) is Insistent

    def test_an_unconstrained_registration_is_a_fallback(
        self, base: type
    ) -> None:
        class Special(base, on={"a": "x"}):
            pass

        class Anything(base, on={}, priority=-1):
            pass

        assert type(base(a="x")) is Special
        assert type(base(a="q")) is Anything

    def test_a_tie_is_refused_by_name(self, base: type) -> None:
        class Left(base, on={"a": "x"}):
            pass

        class Right(base, on={"a": "x"}):
            pass

        with pytest.raises(AmbiguousPolymorphError) as raised:
            base(a="x")
        message = str(raised.value)
        assert "Left" in message and "Right" in message
        assert "a='x'" in message

    def test_priority_settles_a_tie(self, base: type) -> None:
        class Left(base, on={"a": "x"}):
            pass

        class Right(base, on={"a": "x"}, priority=1):
            pass

        assert type(base(a="x")) is Right

    def test_a_priority_that_is_not_a_number_is_refused(
        self, base: type
    ) -> None:
        with pytest.raises(TypeError, match="a priority is a whole number"):
            class Wrong(base, on={"a": "x"}, priority="high"):
                pass

    def test_priority_without_on_is_refused(self, base: type) -> None:
        with pytest.raises(TypeError, match="priority= without on="):
            class Lost(base, priority=1):
                pass


# ======================================================================
# Where the value is read from
# ======================================================================


class TestReadingTheArguments:

    def test_a_default_counts_as_a_supplied_value(self) -> None:
        # Otherwise `Chord(root="A")` and `Chord(root="A",
        # mode="major")` would build different classes.
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Major(Tune, on={"mode": "major"}):
            pass

        assert type(Tune(root="A")) is Major
        assert type(Tune(root="A", mode="major")) is Major

    def test_a_factory_default_is_read_as_absent(self) -> None:
        # Building it here would build it twice, once to look at and
        # once to keep.
        class Bag(Magic, polymorphic=True):
            items: Factory[list]

        class Empty(Bag, on={"items": ...}):
            pass

        assert type(Bag()) is Bag
        assert type(Bag(items=[])) is Empty

    def test_a_keyword_only_field_is_never_read_out_of_args(self) -> None:
        class Mixed(Magic, polymorphic=True):
            first: str = ""
            second: KwOnly[str] = ""

        class Second(Mixed, on={"second": "x"}):
            pass

        # "x" arrives as `first`; reading `second` by position would
        # find it there and dispatch on a neighbour's value.
        assert type(Mixed("x")) is Mixed
        assert type(Mixed(second="x")) is Second

    def test_a_positional_only_field_is_never_read_out_of_kwargs(
        self
    ) -> None:
        class Fixed(Magic, polymorphic=True, positional_only=True):
            first: str = ""

        class First(Fixed, on={"first": "x"}):
            pass

        assert type(Fixed("x")) is First

    def test_a_positional_only_value_is_not_looked_for_by_name(
        self
    ) -> None:
        # `first` cannot be passed by name at all, so a keyword of that
        # name is not its value and must not be read as one.
        class Fixed(Magic, polymorphic="strict", positional_only=True):
            first: str = ""

        class First(Fixed, on={"first": "x"}):
            pass

        assert type(Fixed("x")) is First
        with pytest.raises(NoPolymorphError):
            Fixed(first="x")

    def test_a_value_that_cannot_be_compared_does_not_match(self) -> None:
        class Awkward:
            def __eq__(self, other: tx.Any) -> bool:
                raise RuntimeError("no")

            __hash__ = None

        class Held(Magic, polymorphic=True):
            v: tx.Any = None

        class One(Held, on={"v": 1}):
            pass

        class Some(Held, on={"v": {1, 2}}):
            pass

        # Neither constraint can look at it, and neither may let its
        # own failure out of the constructor.
        assert type(Held(v=Awkward())) is Held

    def test_a_hand_written_init_dispatches_by_keyword(self) -> None:
        class Free(Magic, polymorphic=True, init=False):
            kind: str = ""

            def __init__(self, *args: tx.Any, **kwargs: tx.Any) -> None:
                self.__magic_init__(*args, **kwargs)

        class Known(Free, on={"kind": "k"}):
            pass

        # Nothing can be read out of `args`: the order is whatever the
        # hand-written signature says.
        assert type(Free(kind="k")) is Known

    def test_the_converter_runs_before_matching(self) -> None:
        class Counted(Magic, polymorphic=True):
            n: ConvertTo[int] = 0

        class Three(Counted, on={"n": 3}):
            pass

        assert type(Counted(n="3")) is Three

    def test_a_value_the_converter_refuses_is_left_to_init(self) -> None:
        class Counted(Magic, polymorphic=True):
            n: ConvertTo[int] = 0

        class Three(Counted, on={"n": 3}):
            pass

        with pytest.raises(ConversionError, match="Counted.n"):
            Counted(n="three")

    def test_an_alias_is_read_under_the_name_the_caller_types(self) -> None:
        class Aliased(Magic, polymorphic=True):
            _mode: str = "major"

        class Minor(Aliased, on={"_mode": "minor"}):
            pass

        # `on=` names the field as the class declares it; the argument
        # arrives under the public name.
        assert type(Aliased(mode="minor")) is Minor


# ======================================================================
# More than one level
# ======================================================================


class TestNarrowing:

    def test_a_grandchild_is_reached_in_two_hops(self) -> None:
        assert type(Chord(root="A", mode="minor")) is HarmonicMinor

    def test_each_level_must_match_in_turn(self) -> None:
        # `HarmonicMinor` is unreachable without satisfying
        # `MinorChord` first, whatever its own constraint says.
        assert type(Chord(root="A")) is Chord

    def test_a_grandchild_called_directly_still_works(self) -> None:
        assert type(HarmonicMinor(root="A")) is HarmonicMinor


# ======================================================================
# strict
# ======================================================================


class TestStrict:

    @pytest.fixture
    def base(self) -> type:
        class Strict(Magic, polymorphic="strict"):
            kind: str = ""

        return Strict

    def test_nothing_matching_is_refused(self, base: type) -> None:
        class Known(base, on={"kind": "k"}):
            pass

        with pytest.raises(NoPolymorphError) as raised:
            base(kind="q")
        message = str(raised.value)
        assert "Known(kind='k')" in message
        assert "has not been imported" in message

    def test_a_leaf_with_no_registrations_still_builds(
        self, base: type
    ) -> None:
        # Options are inherited, so every subclass is strict too. If
        # that meant "never build me", the leaves would be unusable.
        class Known(base, on={"kind": "k"}):
            pass

        assert type(Known(kind="k")) is Known

    def test_a_root_with_nothing_registered_is_refused(self) -> None:
        # The case the setting exists for: the module holding the
        # subclass has not been imported. Building a plain one silently
        # would be exactly the failure it is meant to report.
        class Alone(Magic, polymorphic="strict"):
            kind: str = ""

        with pytest.raises(NoPolymorphError, match="has not been imported"):
            Alone(kind="k")

    def test_a_contradicting_value_is_refused(self, base: type) -> None:
        class Known(base, on={"kind": "k"}):
            pass

        with pytest.raises(PolymorphError, match="contradicts"):
            Known(kind="q")

    def test_a_contradiction_is_allowed_when_not_strict(self) -> None:
        class Loose(Magic, polymorphic=True):
            kind: str = ""

        class Known(Loose, on={"kind": "k"}):
            pass

        assert Known(kind="q").kind == "q"

    def test_an_unconstrained_field_is_not_contradicted(
        self, base: type
    ) -> None:
        class Ranged(base, on={"kind": {"k", "l"}}):
            pass

        assert Ranged(kind="l").kind == "l"


# ======================================================================
# An abstract base
# ======================================================================


class TestAbstractBase:

    @pytest.fixture
    def base(self) -> type:
        class Shape(Magic, polymorphic=True):
            kind: str = ""

            @abstractmethod
            def area(self) -> int:
                ...

        return Shape

    def test_it_builds_a_concrete_subclass(self, base: type) -> None:
        class Square(base, on={"kind": "square"}):
            def area(self) -> int:
                return 1

        assert base(kind="square").area() == 1

    def test_nothing_matching_says_so(self, base: type) -> None:
        class Square(base, on={"kind": "square"}):
            def area(self) -> int:
                return 1

        # The registration itself is sound -- "circle" is refused for
        # matching nothing, not because there was nothing to match.
        assert base(kind="square").area() == 1
        with pytest.raises(NoPolymorphError, match="is abstract"):
            base(kind="circle")


# ======================================================================
# Registering by hand
# ======================================================================


class TestRegisterPolymorph:

    @pytest.fixture
    def base(self) -> type:
        class Root(Magic, polymorphic=True):
            kind: str = ""

        return Root

    def test_a_class_can_be_registered_afterwards(self, base: type) -> None:
        class Later(base):
            pass

        assert base.register_polymorph(Later, kind="k") is Later
        assert type(base(kind="k")) is Later

    def test_it_is_a_decorator_when_the_class_is_left_out(
        self, base: type
    ) -> None:
        @base.register_polymorph(on={"kind": "k"})
        class Later(base):
            pass

        assert isinstance(Later, type)
        assert type(base(kind="k")) is Later

    def test_the_decorator_takes_keywords_and_priority(
        self, base: type
    ) -> None:
        @base.register_polymorph(kind="k", priority=5)
        class Later(base):
            pass

        assert type(base(kind="k")) is Later

    def test_the_bare_decorator_still_registers(self, base: type) -> None:
        # No call, no constraints: the class arrives as the target and
        # stands for anything, so it is the fallback.
        @base.register_polymorph
        class Fallback(base):
            pass

        assert isinstance(Fallback, type)
        assert type(base(kind="anything")) is Fallback

    def test_the_decorator_on_a_plain_class_refuses(self) -> None:
        class Plain(Magic):
            kind: str = ""

        with pytest.raises(TypeError, match="does not build its subclasses"):
            @Plain.register_polymorph(kind="k")
            class Sub(Plain):
                pass

    def test_on_and_keywords_say_the_same_thing(self, base: type) -> None:
        class Later(base):
            pass

        base.register_polymorph(Later, on={"kind": "k"}, priority=2)
        assert type(base(kind="k")) is Later

    def test_registering_again_replaces_rather_than_duplicates(
        self, base: type
    ) -> None:
        class Later(base):
            pass

        base.register_polymorph(Later, kind="k")
        base.register_polymorph(Later, kind="k")
        # A duplicate entry would tie with itself.
        assert type(base(kind="k")) is Later

    def test_a_class_cannot_register_against_itself(self, base: type) -> None:
        with pytest.raises(TypeError, match="against itself"):
            base.register_polymorph(base, kind="k")

    def test_only_a_subclass_can_be_registered(self, base: type) -> None:
        class Stranger(Magic):
            kind: str = ""

        with pytest.raises(TypeError, match="only build its own subclasses"):
            base.register_polymorph(Stranger, kind="k")

    def test_a_cycle_cannot_be_built(self, base: type) -> None:
        # Only strict subclasses can be registered, so delegation always
        # goes down the hierarchy and cannot come back around.
        class Middle(base, on={"kind": "k"}):
            pass

        class Leaf(Middle, on={"kind": "k"}):
            pass

        with pytest.raises(TypeError, match="only build its own subclasses"):
            Leaf.register_polymorph(base, kind="k")
        assert type(base(kind="k")) is Leaf

    def test_a_class_that_does_not_dispatch_refuses(self) -> None:
        class Plain(Magic):
            kind: str = ""

        class Sub(Plain):
            pass

        with pytest.raises(TypeError, match="does not build its subclasses"):
            Plain.register_polymorph(Sub, kind="k")

    def test_on_without_a_polymorphic_base_is_refused(self) -> None:
        class Plain(Magic):
            kind: str = ""

        with pytest.raises(TypeError, match="none of the classes"):
            class Sub(Plain, on={"kind": "k"}):
                pass


# ======================================================================
# The discriminant field on the subclass
# ======================================================================


class TestPinDiscriminant:

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        return Tune

    def test_pin_gives_the_field_the_matched_value(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            pass

        assert Minor(root="A").mode == "minor"
        assert asdict(Minor(root="A")) == {"root": "A", "mode": "minor"}

    def test_pin_leaves_a_field_the_subclass_writes_alone(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: str = "dorian"

        assert Minor(root="A").mode == "dorian"

    def test_pin_only_applies_to_a_single_exact_value(
        self, base: type
    ) -> None:
        class Modal(base, on={"mode": {"dorian", "lydian"}}):
            pass

        assert Modal(root="A").mode == "major"

    def test_classvar_stores_nothing_per_instance(self, base: type) -> None:
        class Sus(base, on={"mode": "sus"}, pin_discriminant="classvar"):
            pass

        assert Sus.mode == "sus"
        assert asdict(Sus(root="A")) == {"root": "A"}
        assert repr(Sus(root="A")) == "Sus(root='A')"

    def test_classvar_still_accepts_the_argument(self, base: type) -> None:
        class Sus(base, on={"mode": "sus"}, pin_discriminant="classvar"):
            pass

        # Both the delegated call and the direct one pass `mode`, so
        # neither may be refused.
        assert type(base(root="A", mode="sus")) is Sus
        assert Sus(root="A", mode="sus").mode == "sus"

    def test_keep_leaves_the_field_as_it_was(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}, pin_discriminant="keep"):
            pass

        assert Minor(root="A").mode == "major"

    def test_a_pin_can_be_taken_back_by_redeclaring_the_field(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}):
            pass

        class Stricter(Minor):
            mode: str

        with pytest.raises(TypeError, match="missing"):
            Stricter(root="A")

    def test_a_hand_written_classvar_that_holds_the_value_is_allowed(
        self, base: type
    ) -> None:
        # The subclass does not take `mode`, but it holds the value the
        # constraint calls for, so the base drops `mode` when it
        # delegates rather than passing on an argument the subclass
        # refuses.
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        assert Minor.mode == "minor"
        assert type(base(root="A", mode="minor")) is Minor
        assert asdict(base(root="A", mode="minor")) == {"root": "A"}
        # The subclass, called directly, never took `mode`.
        with pytest.raises(TypeError, match="unexpected keyword"):
            Minor(root="A", mode="minor")

    def test_a_hand_written_classvar_that_holds_a_wrong_value_is_refused(
        self, base: type
    ) -> None:
        with pytest.raises(TypeError, match="holds 'major', which is not"):
            class Minor(base, on={"mode": "minor"}):
                mode: ClassVar[str] = "major"

    def test_a_discriminant_that_is_neither_taken_nor_held_is_refused(
        self
    ) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        with pytest.raises(TypeError, match="holds no value of its own"):
            class Minor(Tune, on={"mode": "minor"}):
                mode: NoInit[str]

    def test_a_discriminant_the_base_does_not_take_either_is_fine(
        self
    ) -> None:
        # Nothing can pass it on, so nothing can fail on it.
        class Tune(Magic, polymorphic=True):
            root: str = ""
            mode: NoInit[str] = "major"

        class Minor(Tune, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        assert Minor.mode == "minor"

    def test_a_pinned_mutable_default_is_not_shared(self) -> None:
        class Tune(Magic, polymorphic=True):
            cfg: dict = None

        class Tagged(Tune, on={"cfg": {"a": 1}}):
            pass

        first, second = Tagged(), Tagged()
        assert first.cfg == {"a": 1} and first.cfg is not second.cfg
        first.cfg["b"] = 2
        assert Tagged().cfg == {"a": 1}

    def test_a_pinned_mutable_default_obeys_the_class_setting(self) -> None:
        class Tune(Magic, polymorphic=True, mutable_default="raise"):
            cfg: dict = None

        with pytest.raises(ValueError, match="shared by every instance"):
            class Tagged(Tune, on={"cfg": {"a": 1}}):
                pass


class TestPinnedSignature:
    """A pinned default can leave a required parameter behind it.

    Python cannot spell `f(mode="minor", root)`, so the parameters after
    a pinned one are given a sentinel and the body turns a sentinel that
    is still there back into the usual complaint.
    """

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            mode: str
            root: str

        return Tune

    def test_the_class_can_still_be_built(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            pass

        assert Minor(root="A").root == "A"
        assert Minor("minor", "A").root == "A"

    def test_the_missing_argument_is_named(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            pass

        with pytest.raises(
            TypeError, match="missing a required argument: 'root'"
        ):
            Minor()

    def test_a_pin_inherited_from_a_base_still_counts(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}):
            pass

        class Harmonic(Minor, on={"root": "A"}):
            pass

        assert type(base(mode="minor", root="A")) is Harmonic

    def test_two_hand_written_fields_get_the_same_treatment(self) -> None:
        # Nothing here was pinned: a required field after one written
        # with a default is given the same sentinel as one after a pin.
        class First(Magic, polymorphic=True):
            a: int = 0

        class Second(First):
            b: int

        assert Second(b=1) == Second(0, 1)
        with pytest.raises(
            TypeError, match="missing a required argument: 'b'"
        ):
            Second(1)


class TestDispatchAfterADefault:
    """A discriminant with no default may follow a field that has one."""

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            tag: int = 0
            mode: str

        class Minor(Tune, on={"mode": "minor"}):
            pass

        return Tune

    def test_the_discriminant_is_read_by_position(self, base: type) -> None:
        built = base(1, "minor")
        assert type(built).__name__ == "Minor"
        assert built.tag == 1

    def test_the_discriminant_is_read_by_name(self, base: type) -> None:
        assert type(base(mode="minor")).__name__ == "Minor"
        assert type(base(mode="major")) is base

    def test_a_missing_discriminant_is_named(self, base: type) -> None:
        with pytest.raises(
            TypeError, match=r"^Tune\(\) missing a required argument: 'mode'$"
        ):
            base(1)

    def test_delegating_to_a_class_that_holds_the_discriminant(self) -> None:
        # The subclass does not take `mode`, so the call is re-spelt by
        # name before it is handed on; a field still missing after that
        # is named against the class that was built.
        class Chord(Magic, polymorphic=True):
            tag: int = 0
            mode: str
            root: str
            extra: int = 1
            more: int

        class Major(Chord, on={"mode": "major"}):
            mode: tx.ClassVar[str] = "major"

        built = Chord(1, "major", "A", 2, 3)
        assert type(built) is Major
        assert (built.tag, built.root, built.extra, built.more) == (
            1, "A", 2, 3
        )
        with pytest.raises(
            TypeError, match=r"^Major\(\) missing a required argument: 'more'$"
        ):
            Chord(1, "major", "A")


# ======================================================================
# Pinning, beside a default that skips a step
# ======================================================================


class TestPinningAndSkippedDefaults:
    """Two reasons a parameter carries something else, in one class.

    A pinned discriminant can leave a parameter with no default behind
    one that has a default, which Python's syntax cannot write, so that
    parameter carries a sentinel. Separately, a class that does not
    convert or validate its defaults gives a defaulted parameter a
    marker, so the body can tell "not passed" from a caller who passed
    the same value. Both are put right in the signature people read --
    and the two must be put right together, since either done on its
    own would undo the other.
    """

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True, convert_defaults=False):
            mode: str                   # pinned by the subclass
            root: str                   # required, and behind the pin
            tag: ConvertTo[str] = 7     # a default that skips its step

        return Tune

    @pytest.fixture
    def minor(self, base: type) -> type:
        class Minor(base, on={"mode": "minor"}):
            pass

        return Minor

    def test_one_signature_says_all_three_things(self, minor: type) -> None:
        found = signature(minor)
        # The pin shows the value it pinned...
        assert found.parameters["mode"].default == "minor"
        # ...the parameter behind it reads as required...
        assert found.parameters["root"].default is Parameter.empty
        # ...and the skipped default shows the value, not the marker.
        assert found.parameters["tag"].default == 7

    def test_binding_agrees_with_all_three(self, minor: type) -> None:
        found = signature(minor)
        with pytest.raises(TypeError, match="missing a required argument"):
            found.bind()
        assert found.bind(root="A").arguments == {"root": "A"}

    def test_the_class_still_builds(self, minor: type) -> None:
        built = minor(root="A")
        assert (built.mode, built.root, built.tag) == ("minor", "A", 7)

    def test_the_skipped_default_is_still_skipped(self, minor: type) -> None:
        # The default is left alone; what a caller passes is converted.
        assert minor(root="A").tag == 7
        assert minor(root="A", tag=b"x").tag == "x"

    def test_a_missing_argument_is_named_before_a_default_is_built(
        self
    ) -> None:
        # Python reports too few arguments before the body runs at all,
        # so a factory that would fail must not get to speak first.
        def explode() -> int:
            raise RuntimeError("the factory ran")  # pragma: no cover

        class Tune(Magic, polymorphic=True):
            mode: str
            root: str
            built: Factory[int, explode] = None

        class Minor(Tune, on={"mode": "minor"}):
            pass

        with pytest.raises(
            TypeError, match="missing a required argument: 'root'"
        ):
            Minor()


class TestPinnedValuesAsDefaults:
    """A pinned value is a default the class author wrote.

    It is written on the class statement rather than beside the field,
    but it is the author's value either way -- so it follows the same
    settings a default written out in the body would.
    """

    def test_a_pinned_value_is_converted_by_default(self) -> None:
        class Tune(Magic, polymorphic=True):
            n: ConvertTo[int] = 0

        class One(Tune, on={"n": "1"}):
            pass

        assert One().n == 1

    def test_a_pinned_value_follows_convert_defaults(self) -> None:
        class Tune(Magic, polymorphic=True, convert_defaults=False):
            n: ConvertTo[int] = 0

        class One(Tune, on={"n": "1"}):
            pass

        assert One().n == "1"

    def test_a_pinned_value_replaces_a_factory_default(self) -> None:
        # The field had a default built from its type; the pin gives it
        # one value instead, and the factory has to stop applying or the
        # pinned value never reaches the instance.
        class Tune(Magic, polymorphic=True, factory=True):
            mode: str
            n: int = 0

        class Minor(Tune, on={"mode": "minor"}):
            pass

        assert Minor().mode == "minor"
        assert isinstance(Tune(mode="minor"), Minor)

    def test_a_pinned_mutable_value_is_still_not_shared(self) -> None:
        # Promoting it to a factory and skipping its conversion are two
        # different things happening to the same default.
        class Tune(Magic, polymorphic=True, convert_defaults=False):
            cfg: dict = None

        class Tagged(Tune, on={"cfg": {"a": 1}}):
            pass

        first, second = Tagged(), Tagged()
        assert first.cfg == {"a": 1} and first.cfg is not second.cfg

    @pytest.mark.parametrize("converts", [True, False])
    def test_dispatch_reads_a_default_the_way_the_class_stores_it(
        self, converts: bool
    ) -> None:
        # Choosing a subclass runs the converter, so that a registration
        # is matched against the value the instance will hold. A class
        # that does not convert its defaults holds the unconverted one,
        # and dispatch has to go on that.
        class Tune(Magic, polymorphic=True, convert_defaults=converts):
            n: ConvertTo[int] = "1"

        class Text(Tune, on={"n": "1"}, pin_discriminant="keep"):
            pass

        class Number(Tune, on={"n": 1}, pin_discriminant="keep"):
            pass

        built = Tune()
        assert type(built) is (Number if converts else Text)
        assert built.n == (1 if converts else "1")


# ======================================================================
# What the outside world sees
# ======================================================================


class TestIntrospection:

    def test_only_a_polymorphic_class_pays_for_dispatch(self) -> None:
        # Choosing a subclass has to happen in a metaclass `__call__`,
        # and having one costs every instantiation of every class that
        # metaclass builds. So a class that never asked for it keeps
        # the metaclass -- and the interpreter's own fast path -- that
        # it had before the feature existed.
        class Plain(Magic):
            x: int = 0

        class Root(Magic, polymorphic=True):
            x: int = 0

        class Leaf(Root):
            pass

        assert type(Plain) is MetaMagic
        assert type(Root) is not MetaMagic
        assert issubclass(type(Root), MetaMagic)
        # One metaclass for the whole hierarchy, not one per class.
        assert type(Leaf) is type(Root)

    def test_a_pinned_parameter_leaves_the_next_one_required(self) -> None:
        class Tune(Magic, polymorphic=True):
            mode: str
            root: str

        class Minor(Tune, on={"mode": "minor"}):
            pass

        found = signature(Minor)
        assert found.parameters["mode"].default == "minor"
        # It carries a sentinel so that the generated code can tell it
        # was not passed -- but nothing reading the signature should
        # ever see one, or `root` would look optional.
        assert found.parameters["root"].default is Parameter.empty
        with pytest.raises(TypeError, match="missing a required argument"):
            found.bind()
        assert found.bind(root="A").arguments == {"root": "A"}

    def test_a_signature_written_by_hand_still_wins(self) -> None:
        written = Signature(
            [Parameter("raw", Parameter.POSITIONAL_OR_KEYWORD)]
        )

        class Hand(Magic):
            x: int = 0
            __signature__ = written

        assert signature(Hand) is written

    def test_a_class_that_takes_its_arguments_in_new(self) -> None:
        class Built(Magic, init=False):
            def __new__(cls, a: int, b: int = 2) -> "Built":
                return super().__new__(cls)

        assert list(signature(Built).parameters) == ["a", "b"]
        assert isinstance(Built(1), Built)


# ======================================================================
# Copies
# ======================================================================


class TestCopies:
    """A copy rebuilds the class it already is, without dispatching."""

    @pytest.mark.parametrize(
        "duplicate",
        [
            lambda obj: pickle.loads(pickle.dumps(obj)),
            copy.copy,
            copy.deepcopy,
        ],
        ids=["pickle", "copy", "deepcopy"],
    )
    def test_a_dispatched_instance_survives(self, duplicate: object) -> None:
        chord = Chord(root="C", mode="minor")
        assert type(chord) is MinorChord
        again = duplicate(chord)
        assert type(again) is MinorChord
        assert again == chord

    def test_a_copy_does_not_re_dispatch(self) -> None:
        # Registering later only changes what is built later, and a
        # copy is not a construction.
        class Tune(Magic, polymorphic=True):
            mode: str = "major"

        plain = Tune(mode="lydian")
        assert type(plain) is Tune

        class Lydian(Tune, on={"mode": "lydian"}):
            pass

        assert type(copy.copy(plain)) is Tune
        assert type(copy.deepcopy(plain)) is Tune
        assert type(Tune(mode="lydian")) is Lydian


# ======================================================================
# The options themselves
# ======================================================================


class TestOptions:

    def test_polymorphic_takes_three_values(self) -> None:
        with pytest.raises(ValueError, match="polymorphic must be"):
            class Wrong(Magic, polymorphic="yes"):
                pass

    def test_pin_discriminant_takes_three_values(self) -> None:
        with pytest.raises(ValueError, match="pin_discriminant must be"):
            class Wrong(Magic, pin_discriminant="maybe"):
                pass

    def test_the_decorator_can_ask_for_it(self) -> None:
        @magic(polymorphic=True)
        class Root:
            kind: str = ""

        class Leaf(Root, on={"kind": "k"}):
            pass

        assert type(Root(kind="k")) is Leaf

    def test_the_decorator_cannot_register(self) -> None:
        # A class that inherits from a Magic class has already been
        # built, so `on=` belongs on the class statement.
        @magic(polymorphic=True)
        class Root:
            kind: str = ""

        with pytest.raises(TypeError, match="already a Magic class"):
            @magic(on={"kind": "k"})
            class Leaf(Root):
                pass

    def test_replace_rebuilds_through_the_class_it_has(self) -> None:
        # `replace` calls the class the instance already has, so a
        # change can narrow it further -- but an instance that is
        # already a subclass never goes back up to try a sibling.
        class Tune(Magic, polymorphic=True, frozen=True, slots=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}):
            pass

        class Modal(Tune, on={"mode": "dorian"}):
            pass

        assert type(replace(Tune(root="A"), mode="minor")) is Minor
        assert type(replace(Minor(root="A"), mode="dorian")) is Minor
        assert replace(Minor(root="A"), root="B").root == "B"

    def test_the_setting_is_inherited(self) -> None:
        class Root(Magic, polymorphic=True):
            kind: str = ""

        class Middle(Root, on={"kind": "k"}):
            pass

        class Leaf(Middle, on={"kind": "k"}):
            pass

        assert type(Root(kind="k")) is Leaf


# ======================================================================
# A generic class that chooses its subclass
# ======================================================================


class TestGenericPolymorphic:
    """`Signal[int](...)` chooses a subclass and fills its parameter in."""

    def test_it_builds_the_subclass_with_the_parameter_filled_in(
        self
    ) -> None:
        made = Signal[int](kind="inverse", value="7")
        assert type(made) is Inverse[int]
        assert made.value == 7

    def test_the_unparameterised_class_still_dispatches(self) -> None:
        made = Signal(kind="inverse", value="7")
        assert type(made) is Inverse
        # `T` stands for nothing in particular, so nothing converts.
        assert made.value == "7"

    def test_it_equals_the_unparameterised_spelling(self) -> None:
        assert Signal[int](kind="inverse", value="7") == Inverse(
            kind="inverse", value=7
        )

    def test_a_subclass_registered_afterwards_is_found(self) -> None:
        # The parameterisation reads what is registered when it is
        # called, not what was registered when it was built.
        built = Signal[int]

        class Late(Signal[_T], on={"kind": "late"}):
            pass

        assert type(built(kind="late", value="3")) is Late[int]

    def test_a_subclass_that_is_not_generic_is_built_as_it_is(self) -> None:
        class Plain(Signal, on={"kind": "plain"}):
            pass

        assert type(Signal[int](kind="plain", value="2")) is Plain

    def test_a_subclass_that_fills_the_parameter_in_itself(self) -> None:
        class Named(Signal[str], on={"kind": "named"}):
            pass

        assert type(Signal[str](kind="named", value="x")) is Named

    def test_it_is_not_a_candidate_for_another_parameterisation(self) -> None:
        # `Named` is a `Signal[str]`, so `Signal[int]` cannot build it:
        # it builds itself instead.
        class Named(Signal[str], on={"kind": "named"}):
            pass

        assert type(Signal[int](kind="named", value=1)) is Signal[int]

    def test_a_subclass_written_against_a_parameterisation(self) -> None:
        # It registers with `Signal`, and the parameters it was written
        # with are what say which parameterisations can build it.
        class OnlyInt(Signal[int], on={"kind": "only"}):
            pass

        assert type(Signal[int](kind="only", value="4")) is OnlyInt
        assert type(Signal(kind="only", value=4)) is OnlyInt
        assert type(Signal[str](kind="only", value="4")) is Signal[str]

    def test_the_two_spellings_build_the_same_class(self) -> None:
        class Either(Signal[int], on={"kind": "either"}):
            pass

        assert Signal(kind="either", value=1) == Signal[int](
            kind="either", value=1
        )

    def test_a_deeper_subclass_wins_where_both_match(self) -> None:
        class Refined(Inverse[_T], on={"value": 5}):
            pass

        assert type(Signal[int](kind="inverse", value="5")) is Refined[int]
        assert type(Signal[int](kind="inverse", value="6")) is Inverse[int]

    def test_register_polymorph_reaches_the_parameterisations(self) -> None:
        class Asked(Signal[_T]):
            pass

        Signal.register_polymorph(Asked, kind="asked")
        assert type(Signal[int](kind="asked", value="8")) is Asked[int]

    def test_one_of_two_parameters_filled_in_by_the_subclass(self) -> None:
        class Pair(Magic, tx.Generic[_T, _S], polymorphic=True, convert=True):
            kind: str
            left: _T
            right: _S

        class Half(Pair[_T, int], on={"kind": "half"}):
            pass

        made = Pair[str, int](kind="half", left="a", right="2")
        assert type(made) is Half[str]
        assert made.right == 2
        # `Half` says `right` is an `int`, so it cannot stand for this.
        assert type(Pair[str, bool](kind="half", left="a", right=0)) is (
            Pair[str, bool]
        )

    def test_the_value_is_read_through_the_filled_in_converter(self) -> None:
        # Dispatch goes on the value the instance will really hold, so
        # the constraint is matched against the converted one.
        class Level(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            grade: _T

        class Three(Level[_T], on={"grade": 3}):
            pass

        assert type(Level[int](grade="3")) is Three[int]
        # Without the parameter filled in there is nothing to convert
        # to, so the string is matched as it was passed.
        assert type(Level(grade="3")) is Level

    def test_an_abstract_generic_base(self) -> None:
        class Shape(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            size: _T

            @abstractmethod
            def area(self) -> tx.Any:
                ...

        class Square(Shape[_T], on={"kind": "square"}):
            def area(self) -> tx.Any:
                return self.size * self.size

        assert Shape[int](kind="square", size="3").area() == 9
        with pytest.raises(NoPolymorphError, match="is abstract"):
            Shape[int](kind="round", size=1)

    def test_an_instance_round_trips(self) -> None:
        made = Signal[int](kind="inverse", value=1)
        assert pickle.loads(pickle.dumps(made)) == made
        assert copy.deepcopy(made) == made

    def test_replace_keeps_the_parameterised_class(self) -> None:
        made = Signal[int](kind="inverse", value="1")
        assert type(replace(made, value="2")) is Inverse[int]

    def test_the_signature_is_the_constructors(self) -> None:
        assert list(signature(Signal[int]).parameters) == ["kind", "value"]

    def test_a_parameterisation_made_before_anything_registered(self) -> None:
        class Fresh(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            value: _T

        built = Fresh[int]
        assert type(built(kind="x", value="1")) is Fresh[int]

        class First(Fresh[_T], on={"kind": "first"}):
            pass

        assert type(built(kind="first", value="2")) is First[int]

    def test_it_works_with_slots_and_frozen(self) -> None:
        class Node(Magic, tx.Generic[_T], polymorphic=True, convert=True,
                   slots=True, frozen=True):
            kind: str
            value: _T

        class Leaf(Node[_T], on={"kind": "leaf"}):
            pass

        made = Node[int](kind="leaf", value="5")
        assert type(made) is Leaf[int]
        assert not hasattr(made, "__dict__")
        assert asdict(made) == {"kind": "leaf", "value": 5}

    def test_a_parameter_nested_in_a_hint(self) -> None:
        class Many(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            items: tx.List[_T]

        class Some(Many[_T], on={"kind": "some"}):
            pass

        made = Many[int](kind="some", items=["1", "2"])
        assert type(made) is Some[int]
        assert made.items == [1, 2]

    def test_an_alternate_input_name_still_reaches_the_choice(self) -> None:
        class Sorting(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str = field(alias="sort")
            value: _T

        class Sorted(Sorting[_T], on={"kind": "s"}):
            pass

        made = Sorting[int](sort="s", value="9")
        assert type(made) is Sorted[int]
        assert made.value == 9

    def test_two_that_match_equally_well_say_what_to_write(self) -> None:
        # The names in the advice are the ones a class statement can be
        # written with, not `One[int]`.
        class Amb(Magic, tx.Generic[_T], polymorphic=True):
            kind: str
            value: _T

        class One(Amb[_T], on={"kind": "k"}):
            pass

        class Two(Amb[_T], on={"kind": "k"}):
            pass

        with pytest.raises(AmbiguousPolymorphError) as raised:
            Amb[int](kind="k", value=1)
        assert "One[int], Two[int]" in str(raised.value)
        assert "class One(Amb, on={...}, priority=1)" in str(raised.value)

    def test_a_subclass_that_is_not_generic_keeps_its_own_types(self) -> None:
        # It is built as it was written, so `value` is still `_T` and
        # there is nothing to convert to.
        class Loose(Signal, on={"kind": "loose"}):
            pass

        made = Signal[int](kind="loose", value="1")
        assert type(made) is Loose
        assert made.value == "1"
        assert isinstance(made, Signal)
        assert not isinstance(made, Signal[int])

    def test_a_subclass_that_takes_a_parameter_of_its_own(self) -> None:
        # `_S` is a variable the subscription says nothing about, so
        # there is nothing to fill it in with.
        class Extra(Signal[_T], tx.Generic[_T, _S], on={"kind": "extra"}):
            pass

        assert type(Signal[int](kind="extra", value="1")) is Extra

    @pytest.mark.parametrize("any_", [tx.Any, TypingAny])
    def test_any_stands_for_every_filling_in(self, any_: tx.Any) -> None:
        # Both spellings mean the same thing, and before Python 3.11
        # they are not the same object.
        class Root(Magic, tx.Generic[_T], polymorphic=True):
            kind: str
            value: _T

        class Whatever(Root[any_], on={"kind": "whatever"}):
            pass

        assert type(Root[int](kind="whatever", value=1)) is Whatever
        assert type(Root[str](kind="whatever", value="1")) is Whatever

    def test_a_parameter_used_twice(self) -> None:
        class Pair(Magic, tx.Generic[_T, _S], polymorphic=True, convert=True):
            kind: str
            left: _T
            right: _S

        class Same(Pair[_T, _T], on={"kind": "same"}):
            pass

        assert type(Pair[int, int](kind="same", left="1", right="2")) is (
            Same[int]
        )
        assert type(Pair[int, str](kind="same", left=1, right="2")) is (
            Pair[int, str]
        )

    def test_a_parameter_nested_in_what_a_subclass_fills_in(self) -> None:
        class Nest(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            item: _T

        class Listed(Nest[tx.List[_T]], on={"kind": "listed"}):
            pass

        made = Nest[tx.List[int]](kind="listed", item=["1"])
        assert type(made) is Listed[int]
        assert made.item == [1]
        assert type(Nest[int](kind="listed", item=1)) is Nest[int]

    def test_a_callable_signature_mentioning_the_parameter(self) -> None:
        class Call(Magic, tx.Generic[_T], polymorphic=True):
            kind: str
            fn: tx.Callable[[_T], _T]

        class Caller(Call[_T], on={"kind": "call"}):
            pass

        assert type(Call[int](kind="call", fn=abs)) is Caller[int]

    def test_a_subclass_with_a_class_getitem_of_its_own(self) -> None:
        # It answers the subscription with something that is not a
        # class, so it is built as it was written.
        class Odd(Signal[_T], on={"kind": "odd"}):
            def __class_getitem__(cls, item: tx.Any) -> str:
                return "not a class"

        assert type(Signal[int](kind="odd", value="1")) is Odd

    def test_a_specialisation_beats_the_generic_subclass(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            item: _T

        class Any_(Root[_T], on={"kind": "r"}):
            pass

        class Ints(Root[int], on={"kind": "r"}):
            pass

        # `Ints` sits one step further down, so it wins where both fit.
        assert type(Root[int](kind="r", item="1")) is Ints
        assert type(Root[str](kind="r", item="1")) is Any_[str]

    def test_a_grandchild_through_a_parameterised_parent(self) -> None:
        class Leaf(Inverse[int], on={"value": 5}):
            pass

        assert type(Signal[int](kind="inverse", value="5")) is Leaf
        assert type(Signal[str](kind="inverse", value="5")) is Inverse[str]

    def test_nothing_eligible_builds_the_class_itself(self) -> None:
        # Without `polymorphic="strict"`, a class with no candidate
        # left builds itself, as it does when nothing matches.
        class Root(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            item: _T

        class OnlyStr(Root[str], on={"kind": "one"}):
            pass

        assert type(Root[int](kind="one", item=1)) is Root[int]

    def test_a_class_built_by_dispatch_pickles(self) -> None:
        made = Signal[int](kind="inverse", value="1")
        assert pickle.loads(pickle.dumps(made)) == made


class TestGenericPolymorphicRegistering:
    """`register_polymorph` where type parameters are in play."""

    def test_a_parameterisation_of_the_class_itself_is_refused(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic=True):
            kind: str
            item: _T

        with pytest.raises(TypeError, match="type parameters filled in"):
            Root.register_polymorph(Root[int], kind="loop")

    def test_a_parameterised_subclass_can_be_registered(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            item: _T

        class Sub(Root[_T]):
            pass

        Root.register_polymorph(Sub[int], kind="s")
        assert type(Root(kind="s", item=1)) is Sub[int]
        assert type(Root[int](kind="s", item="1")) is Sub[int]
        assert type(Root[str](kind="s", item="1")) is Root[str]

    def test_registering_on_a_parameterisation_reaches_the_origin(
        self
    ) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            kind: str
            item: _T

        class Sub(Root[_T]):
            pass

        Root[int].register_polymorph(Sub, kind="s")
        assert type(Root[int](kind="s", item="1")) is Sub[int]
        assert type(Root(kind="s", item=1)) is Sub


class TestGenericPolymorphicStrict:
    """`polymorphic="strict"`, with the type parameter filled in."""

    def test_nothing_matching_is_refused(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic="strict", convert=True):
            kind: str
            value: _T

        class One(Root[_T], on={"kind": "one"}):
            pass

        assert type(Root[int](kind="one", value="1")) is One[int]
        with pytest.raises(NoPolymorphError) as raised:
            Root[int](kind="two", value=1)
        # The subclasses it considered are named as it can build them.
        assert "One[int]" in str(raised.value)

    def test_a_registered_subclass_stays_buildable(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic="strict", convert=True):
            kind: str
            value: _T

        class One(Root[_T], on={"kind": "one"}):
            pass

        assert One[int](kind="one", value="1").value == 1

    def test_a_subclass_left_out_is_named_rather_than_blamed_on_imports(
        self
    ) -> None:
        # It is registered and imported; it just stands for other type
        # arguments. Saying "not imported" would send the reader the
        # wrong way.
        class Root(Magic, tx.Generic[_T], polymorphic="strict", convert=True):
            kind: str
            value: _T

        class OnlyStr(Root[str], on={"kind": "one"}):
            pass

        with pytest.raises(NoPolymorphError) as raised:
            Root[int](kind="one", value=1)
        assert "OnlyStr" in str(raised.value)
        assert "not been imported" not in str(raised.value)

    def test_it_refuses_a_value_it_does_not_stand_for(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic="strict", convert=True):
            kind: str
            value: _T

        class One(Root[_T], on={"kind": "one"}):
            pass

        with pytest.raises(PolymorphError, match="contradicts it"):
            One[int](kind="other", value=1)


# ======================================================================
# Reading what a subclass fills a generic base's parameters in with
# ======================================================================


class TestReadingATargetsTypeArguments:
    """`base_arguments` and `fill_in`, which decide the candidates.

    A `polymorphic` class reaches these through dispatch; they are
    exercised directly here for the answers that dispatch cannot reach
    on its own.
    """

    def test_a_class_that_does_not_inherit_from_the_base(self) -> None:
        class Box(Magic, tx.Generic[_T]):
            item: _T

        assert g.base_arguments(int, Box) is None
        assert g.fill_in(int, Box, (int,)) is None

    def test_a_base_that_is_not_the_generic_one_comes_first(self) -> None:
        class Mixin:
            pass

        class Box(Magic, tx.Generic[_T]):
            item: _T

        class Sub(Mixin, Box[_T]):
            pass

        assert g.base_arguments(Sub, Box) == (_T,)
        assert g.fill_in(Sub, Box, (int,)) is Sub[int]

    def test_a_base_registered_rather_than_inherited(self) -> None:
        # `Magic` classes are abstract base classes, so a class can be
        # made a subclass of one without inheriting from it. There is
        # no chain of bases to read type arguments off, and no way to
        # fill any in.
        class Box(Magic, tx.Generic[_T]):
            item: _T

        class Registered:
            pass

        Box.register(Registered)
        assert issubclass(Registered, Box)
        assert g.base_arguments(Registered, Box) is None
        assert g.fill_in(Registered, Box, (int,)) is None

        # And one of those sitting in front of the real base is
        # stepped over rather than answered for.
        class Sub(Registered, Box[_T]):
            pass

        assert g.fill_in(Sub, Box, (int,)) is Sub[int]

    def test_a_callable_signature_as_a_type_argument(self) -> None:
        # `get_args` hands a callable's parameters back as a list, not
        # as a typing form, so they are matched one by one.
        class Box(Magic, tx.Generic[_T]):
            item: _T

        class Takes(Box[tx.Callable[[_T], _T]]):
            pass

        assert g.fill_in(Takes, Box, (tx.Callable[[int], int],)) is (
            Takes[int]
        )
        # A different number of parameters, and a parameter that does
        # not match, are both refused.
        assert g.fill_in(Takes, Box, (tx.Callable[[int, int], int],)) is None
        assert g.fill_in(Takes, Box, (int,)) is None


# ======================================================================
# Narrowing a discriminant, and the seven pin_discriminant values
# ======================================================================


class TestPinDiscriminantValues:
    """All seven spellings, and how each reads as (storage, narrow)."""

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        return Tune

    @pytest.mark.parametrize(
        "action",
        [
            "pin", "classvar", "keep",
            "narrow", "pin+narrow", "classvar+narrow", "keep+narrow",
        ],
    )
    def test_every_value_is_accepted(self, base: type, action: str) -> None:
        class Minor(base, on={"mode": "minor"}, pin_discriminant=action):
            pass

        # Whatever the storage, the subclass is chosen for the value.
        assert type(base(root="A", mode="minor")) is Minor

    def test_an_unknown_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match="pin_discriminant must be"):
            class Bad(Magic, polymorphic=True, pin_discriminant="huge"):
                x: int

    def test_pin_and_bare_narrow_both_pin(self, base: type) -> None:
        class Pinned(base, on={"mode": "minor"}, pin_discriminant="narrow"):
            pass

        # "narrow" is "pin+narrow": the value is pinned as a default.
        assert Pinned(root="A").mode == "minor"
        assert asdict(Pinned(root="A")) == {"root": "A", "mode": "minor"}

    def test_keep_narrow_leaves_storage_but_still_checks(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "dorian"

        class Modal(
            Tune, on={"mode": {"dorian", "lydian"}},
            pin_discriminant="keep+narrow",
        ):
            pass

        # keep: the field is not pinned, so its own default stands (and
        # the default is one the constraint accepts)...
        assert Modal(root="A").mode == "dorian"
        # ...but the validator is still added.
        with pytest.raises(Exception, match="not a valid"):
            Modal(root="A", mode="ionian")


class TestNarrowTypes:
    """`narrow` narrows the annotation the field carries."""

    @pytest.fixture
    def base(self) -> type:
        class Value(Magic, polymorphic=True):
            v: TypingAny = None
            root: str = "r"

        return Value

    def _annotation(self, cls: type, name: str) -> object:
        return signature(cls).parameters[name].annotation

    def test_an_exact_value_becomes_a_literal(self, base: type) -> None:
        class One(base, on={"v": "a"}, pin_discriminant="narrow"):
            pass

        assert self._annotation(One, "v") == tx.Literal["a"]

    def test_a_set_becomes_a_literal_of_its_members(self, base: type) -> None:
        class Vowel(base, on={"v": {"a", "e"}}, pin_discriminant="narrow"):
            pass

        # Order within a set is not defined, so compare as a set.
        annotation = self._annotation(Vowel, "v")
        assert tx.get_origin(annotation) is tx.Literal
        assert set(tx.get_args(annotation)) == {"a", "e"}

    def test_a_type_is_used_as_it_is(self, base: type) -> None:
        class Whole(base, on={"v": int}, pin_discriminant="narrow"):
            pass

        assert self._annotation(Whole, "v") is int

    def test_a_non_literal_value_leaves_the_type_alone(
        self, base: type
    ) -> None:
        class Pair(base, on={"v": (1, 2)}, pin_discriminant="narrow"):
            pass

        # A tuple is not a value a `Literal` can hold, so the field keeps
        # what it was declared with.
        assert self._annotation(Pair, "v") is TypingAny

    def test_a_pattern_leaves_the_type_alone(self, base: type) -> None:
        class Word(
            base, on={"v": re.compile(r"[a-z]+")}, pin_discriminant="narrow"
        ):
            pass

        assert self._annotation(Word, "v") is TypingAny

    def test_a_callable_leaves_the_type_alone(self, base: type) -> None:
        class Big(base, on={"v": lambda x: True}, pin_discriminant="narrow"):
            pass

        assert self._annotation(Big, "v") is TypingAny

    def test_a_narrowed_literal_survives_generic_filling(self) -> None:
        # Narrowing to a `Literal` leaves nothing for a type variable to
        # stand in for, so filling the base's parameters in is a no-op on
        # the discriminant.
        class Box(Magic, tx.Generic[_T], polymorphic=True):
            kind: str
            item: _T

        class One(Box[_T], on={"kind": "one"}, pin_discriminant="narrow"):
            pass

        assert signature(One).parameters["kind"].annotation == tx.Literal[
            "one"
        ]
        assert type(Box[int](kind="one", item=1)) is One[int]
        assert One[int](item=2).kind == "one"


class TestNarrowValidation:
    """`narrow` rejects a value the constraint would not have matched."""

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        return Tune

    def test_an_off_value_is_rejected_naming_the_field(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}, pin_discriminant="narrow"):
            pass

        with pytest.raises(Exception, match="Minor.mode"):
            Minor(root="A", mode="major")

    def test_the_matching_value_is_accepted(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}, pin_discriminant="narrow"):
            pass

        assert Minor(root="A", mode="minor").mode == "minor"

    def test_a_set_constraint_is_enforced(self, base: type) -> None:
        class Modal(
            base, on={"mode": {"dorian", "lydian"}},
            pin_discriminant="keep+narrow",
        ):
            pass

        assert Modal(root="A", mode="dorian").mode == "dorian"
        with pytest.raises(Exception, match="not a valid"):
            Modal(root="A", mode="ionian")

    def test_a_base_validator_is_kept_and_chained(self) -> None:
        seen = []

        def even(value: int) -> int:
            seen.append(value)
            if value % 2:
                raise ValueError("odd")
            return value

        class Nums(Magic, polymorphic=True):
            kind: str
            n: tx.Annotated[int, field(validate=even)] = 0

        class Small(Nums, on={"n": {0, 2}}, pin_discriminant="keep+narrow"):
            pass

        # The base's validator still runs (it records what it saw)...
        assert Small(kind="s", n=2).n == 2
        assert seen == [2]
        # ...it runs first, so its own rejection is what surfaces...
        with pytest.raises(Exception, match="odd"):
            Small(kind="s", n=3)
        # ...and the added one turns down a value the base would accept.
        with pytest.raises(Exception, match="not a valid"):
            Small(kind="s", n=4)

    def test_a_base_converter_is_kept_under_narrow(self) -> None:
        class Srv(Magic, polymorphic=True, convert=True):
            kind: str
            port: int = 0

        class Http(Srv, on={"kind": "http"}, pin_discriminant="keep+narrow"):
            pass

        # The inherited converter still coerces the value...
        server = Http(kind="http", port="80")
        assert server.port == 80 and isinstance(server.port, int)
        # ...and the discriminant is still enforced.
        with pytest.raises(Exception, match="not a valid"):
            Http(kind="ftp", port="21")


class TestRedefinedDiscriminantSignature:
    """A discriminant redefined with a default no longer trips the
    trailing-required check."""

    def test_a_literal_redefinition_with_a_default_is_built(self) -> None:
        class Tune(Magic, polymorphic=True):
            mode: str
            root: str

        # `mode` is redeclared with a default, and `root` (required)
        # follows it -- which Python's syntax cannot spell, but a pinned
        # discriminant can leave behind.
        class Minor(Tune, on={"mode": "minor"}):
            mode: tx.Literal["minor"] = "minor"

        assert Minor(root="A").root == "A"
        assert list(signature(Minor).parameters) == ["mode", "root"]

    def test_a_doc_only_redefinition_with_a_default_is_built(self) -> None:
        from bagof.magic import Doc

        class Tune(Magic, polymorphic=True):
            mode: str
            root: str

        class Minor(Tune, on={"mode": "minor"}):
            mode: Doc[str, "the mode"] = "minor"  # noqa: F722

        assert Minor(root="A").root == "A"

    def test_two_hand_written_fields_without_on_are_built(self) -> None:
        # No registration, so nothing is pinned; the required field
        # after a defaulted one is built all the same.
        class First(Magic, polymorphic=True):
            a: int = 0

        class Second(First):
            b: int

        assert list(signature(Second).parameters) == ["a", "b"]
        assert signature(Second).parameters["b"].default is Parameter.empty
        assert Second(b=2).a == 0


class TestCaseBDelegation:
    """The base drops a discriminant the subclass does not take."""

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        return Tune

    def test_a_dropped_discriminant_by_keyword(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        assert type(base(root="A", mode="minor")) is Minor
        assert Minor.mode == "minor"

    def test_a_dropped_discriminant_by_position(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        # `root` is first, `mode` second: a positional call still lands
        # on `Minor` and drops `mode`.
        assert type(base("A", "minor")) is Minor

    def test_positional_and_keyword_agree_when_dropped(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        assert type(base("A", "minor")) is type(base(root="A", mode="minor"))

    def test_the_direct_call_refuses_the_dropped_argument(
        self, base: type
    ) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        with pytest.raises(TypeError, match="unexpected keyword"):
            Minor(root="A", mode="minor")

    def test_a_non_init_default_is_held(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}):
            mode: NoInit[str] = "minor"

        assert type(Tune(root="A", mode="minor")) is Minor
        assert Minor(root="A").mode == "minor"

    def test_naming_twice_in_a_dropped_call_is_refused(self) -> None:
        # `root` is positional and by keyword: giving it both ways at
        # once is refused, naming the base.
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        with pytest.raises(TypeError, match="multiple values"):
            Tune("A", root="B", mode="minor")

    def test_a_verbatim_class_keeps_the_fast_path(self, base: type) -> None:
        # A subclass that still takes its discriminant is handed the call
        # verbatim, so the ordinary spellings all keep working.
        class Minor(base, on={"mode": "minor"}):
            pass

        # Nothing to re-spell: the registration carries no plan, so the
        # call is handed straight on.
        assert _entry_for(base, Minor).respell is None
        assert type(base(root="A", mode="minor")) is Minor
        assert type(base("A", "minor")) is Minor
        assert Minor(root="A").mode == "minor"

    def test_a_dropping_class_carries_a_plan(self, base: type) -> None:
        class Minor(base, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        plan = _entry_for(base, Minor).respell
        assert plan is not None and "mode" in plan.drops

    def test_a_grandchild_redispatches_through_a_dropped_parent(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"
            style: str = "plain"

        class Minor(Tune, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        class Fancy(Minor, on={"style": "fancy"}):
            pass

        built = Tune(root="A", mode="minor", style="fancy")
        assert type(built) is Fancy
        assert built.style == "fancy" and built.root == "A"


# ======================================================================
# Regressions the review turned up
# ======================================================================


class TestNarrowSurvivesResolution:
    """A narrow validator must survive override and generic filling."""

    def test_override_keeps_the_narrow_validator(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}, pin_discriminant="narrow"):
            pass

        # `override` resolves every inherited field again; the constraint
        # is the field's own preference now, so it is kept, not thrown
        # away while the type still says `Literal["minor"]`.
        class Fancy(Minor, override=True):
            pass

        assert Minor(root="A", mode="minor").mode == "minor"
        with pytest.raises(Exception, match="not a valid"):
            Minor(root="A", mode="major")
        with pytest.raises(Exception, match="not a valid"):
            Fancy(root="A", mode="major")

    def test_generic_filling_keeps_a_non_literal_narrow_validator(
        self
    ) -> None:
        # A pattern narrows no type, so the field keeps the type variable
        # and is filled in -- but the validator is the field's own now
        # and is not regenerated from the substituted type.
        class Box(Magic, tx.Generic[_T], polymorphic=True, validate=True):
            kind: _T
            item: int = 0

        class Re(Box[_T], on={"kind": re.compile("a+")},
                 pin_discriminant="narrow"):
            pass

        with pytest.raises(Exception, match="not a valid"):
            Re(kind="bbb")
        with pytest.raises(Exception, match="not a valid"):
            Re[str](kind="bbb")
        # The matching value still builds, both ways.
        assert Re(kind="aaa").kind == "aaa"
        assert Re[str](kind="aaa").kind == "aaa"

    def test_classvar_narrow_validates_the_discarded_value(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Sus(Tune, on={"mode": "sus"},
                  pin_discriminant="classvar+narrow"):
            pass

        assert Sus.mode == "sus"
        # The value is accepted and discarded, but still validated on the
        # way through.
        assert Sus(root="A", mode="sus").mode == "sus"
        with pytest.raises(Exception, match="not a valid"):
            Sus(root="A", mode="lydian")


class TestSurplusPositionals:
    """A re-spelled call rejects surplus positionals, like the verbatim
    one does."""

    @pytest.fixture
    def base(self) -> type:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}):
            mode: ClassVar[str] = "minor"

        class Major(Tune, on={"mode": "major"}):
            pass

        return Tune

    def test_verbatim_rejects_surplus(self, base: type) -> None:
        with pytest.raises(TypeError):
            base("A", "major", "extra")

    def test_respell_rejects_surplus_naming_the_base(self, base: type) -> None:
        # Would have bound `root` and dropped `mode`, silently losing the
        # third argument, before the guard.
        with pytest.raises(TypeError, match="Tune.*positional"):
            base("A", "minor", "extra")


class TestRegisterPolymorphChecks:
    """register_polymorph goes through the same three-case rule."""

    def test_a_non_matching_held_value_is_refused(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Wrong(Tune):
            mode: ClassVar[str] = "major"

        with pytest.raises(TypeError, match="holds 'major', which is not"):
            Tune.register_polymorph(Wrong, mode="minor")

    def test_a_matching_held_value_is_allowed(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Right(Tune):
            mode: ClassVar[str] = "minor"

        Tune.register_polymorph(Right, mode="minor")
        assert type(Tune(root="A", mode="minor")) is Right

    def test_a_positional_only_discriminant_is_refused(self) -> None:
        class Tune(Magic, polymorphic=True):
            mode: PositionalOnly[str]
            root: str = "r"

        class Wrong(Tune):
            mode: ClassVar[str] = "minor"

        with pytest.raises(TypeError, match="positional-only"):
            Tune.register_polymorph(Wrong, mode="minor")


class TestRedefinedOnlyPinning:
    """A required field after a discriminant, pinned by the subclass or
    inherited with a default, is built either way."""

    def test_an_inherited_discriminant_leaves_a_later_field_required(
        self
    ) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        # `mode` is inherited with a default and not redeclared, so it
        # is not pinned; the required field written after it is built
        # as it is without a registration.
        class Child(Tune, on={"mode": "minor"}, pin_discriminant="keep"):
            extra: int

        assert signature(Child).parameters["extra"].default is (
            Parameter.empty
        )
        built = Child(root="A", extra=1)
        assert (built.mode, built.extra) == ("major", 1)
        assert type(Tune(root="A", mode="minor", extra=1)) is Child
        with pytest.raises(
            TypeError, match="missing a required argument: 'extra'"
        ):
            Child(root="A")

    def test_a_redeclared_discriminant_does_pin(self) -> None:
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        # Redeclared here with a default, so the required `extra` behind
        # it gets the sentinel and the class builds.
        class Child(Tune, on={"mode": "minor"}):
            mode: str = "minor"
            extra: int

        assert Child(root="A", extra=1).extra == 1


class TestNarrowAndCheckSkips:
    """The skip branches in the narrow and check machinery."""

    def test_a_factory_held_discriminant_is_taken_on_trust(self) -> None:
        # A discriminant the subclass holds with a factory is accepted
        # unchecked -- building the factory to check it would build it
        # twice, so the three-case rule skips it.
        class Tune(Magic, polymorphic=True):
            root: str = "r"
            tag: TypingAny = None

        class Tagged(Tune, on={"tag": ...}):
            tag: list = field(factory=list, init=False)

        # Defining it did not raise, and each instance gets its own.
        assert Tagged().tag == []
        assert Tagged().tag is not Tagged().tag

    def test_narrow_leaves_a_redeclared_field_alone(self) -> None:
        # A field the subclass writes out itself keeps its own type and
        # is not narrowed.
        class Tune(Magic, polymorphic=True):
            root: str
            mode: str = "major"

        class Minor(Tune, on={"mode": "minor"}, pin_discriminant="narrow"):
            mode: str = "minor"

        assert signature(Minor).parameters["mode"].annotation is str
        assert Minor(root="A").mode == "minor"

    def test_narrow_adds_no_validator_for_presence(self) -> None:
        # A bare `...` constrains no value, so narrow adds no validator
        # and narrows no type: the field is only required to be there.
        class Tune(Magic, polymorphic=True):
            root: str
            flag: TypingAny = None

        class Present(Tune, on={"flag": ...}, pin_discriminant="narrow"):
            pass

        assert signature(Present).parameters["flag"].annotation is TypingAny
        # Any value at all is accepted, since nothing was added to check.
        assert Present(root="A", flag=object()).root == "A"

    def test_narrow_leaves_a_non_literal_set_type_alone(self) -> None:
        # Floats are not values a `Literal` can hold, so the field keeps
        # its declared type while the membership check is still added.
        class Value(Magic, polymorphic=True):
            x: TypingAny = None
            root: str = "r"

        class Halves(Value, on={"x": {1.5, 2.5}}, pin_discriminant="narrow"):
            pass

        assert signature(Halves).parameters["x"].annotation is TypingAny
        assert Halves(x=1.5).x == 1.5
        with pytest.raises(Exception, match="not a valid"):
            Halves(x=3.5)


# ======================================================================
# Plain intermediates and diamonds
# ======================================================================


class TestIntermediateAndDiamond:
    """Which classes a subclass registers with, when the hierarchy is
    not a simple chain of registered classes."""

    # -- a plain intermediate (problem A) --------------------------------

    @pytest.fixture
    def chain(self) -> tx.Tuple[type, type, type]:
        class Foo(Magic, polymorphic=True):
            kind: str = ""

        class Bar(Foo):
            pass

        class FooBar(Bar, on={"kind": "foobar"}):
            pass

        return Foo, Bar, FooBar

    def test_the_root_reaches_a_subclass_through_a_plain_intermediate(
        self, chain: tx.Tuple[type, type, type]
    ) -> None:
        Foo, Bar, FooBar = chain
        assert type(Foo(kind="foobar")) is FooBar

    def test_the_plain_intermediate_still_reaches_it(
        self, chain: tx.Tuple[type, type, type]
    ) -> None:
        Foo, Bar, FooBar = chain
        assert type(Bar(kind="foobar")) is FooBar
        assert type(Bar(kind="other")) is Bar
        assert type(Foo(kind="other")) is Foo

    def test_a_registered_level_above_a_plain_one_is_where_it_stops(
        self
    ) -> None:
        # R -> S (registered) -> P (plain) -> X: X registers with P and
        # S, and R reaches it through S in two hops, as before.
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""

        class S(R, on={"a": "x"}):
            pass

        class P(S):
            pass

        class X(P, on={"b": "y"}):
            pass

        assert _entry_for(P, X) and _entry_for(S, X)
        assert X not in [entry.target for entry in R.__dict__[
            _POLYMORPHS].dispatch[0]]
        assert type(R(a="x", b="y")) is X
        assert type(R(b="y")) is R
        assert type(P(b="y")) is X

    def test_a_linear_subclass_with_nothing_to_say_registers_nowhere(
        self, chain: tx.Tuple[type, type, type]
    ) -> None:
        Foo, Bar, FooBar = chain

        class Quiet(FooBar):
            pass

        assert _REGISTRATION not in Quiet.__dict__
        assert type(Foo(kind="foobar")) is FooBar

    def test_a_level_without_the_field_is_skipped(self) -> None:
        # Foo has no `extra` to read, so FooBar is reached through Bar,
        # which does.
        class Foo(Magic, polymorphic=True):
            kind: str = ""

        class Bar(Foo):
            extra: str = ""

        class FooBar(Bar, on={"extra": "e"}):
            pass

        assert FooBar.__dict__[_REGISTRATION][0] == (Bar,)
        assert type(Bar(extra="e")) is FooBar
        assert type(Foo(kind="e")) is Foo
        assert _POLYMORPHS not in Foo.__dict__ or not Foo.__dict__[
            _POLYMORPHS].dispatch[0]

    def test_a_misspelled_field_is_still_refused(self) -> None:
        class Foo(Magic, polymorphic=True):
            kind: str = ""

        class Bar(Foo):
            extra: str = ""

        with pytest.raises(TypeError, match="'extar', which is not a field "
                                           "of Bar"):
            class FooBar(Bar, on={"extar": "e"}):
                pass

    def test_a_strict_root_reaches_through_a_plain_intermediate(
        self
    ) -> None:
        # The root used to answer "none has yet: the module has not been
        # imported", which sent the reader looking for an import that
        # had happened.
        class Foo(Magic, polymorphic="strict"):
            kind: str = ""

        class Bar(Foo):
            pass

        class FooBar(Bar, on={"kind": "foobar"}):
            pass

        assert type(Foo(kind="foobar")) is FooBar
        assert type(Bar(kind="foobar")) is FooBar
        assert type(FooBar()) is FooBar
        with pytest.raises(NoPolymorphError, match="FooBar"):
            Bar(kind="other")

    def test_a_plain_branch_beside_a_registered_one(self) -> None:
        # P is plain, SB is registered: X registers with P, which nothing
        # else reaches, and with SB, which R reaches already.
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""

        class P(R):
            pass

        class SB(R, on={"b": "y"}):
            pass

        class X(P, SB, on={"a": "x"}):
            pass

        assert X.__dict__[_REGISTRATION][0] == (P, SB)
        assert type(P(a="x", b="y")) is X
        assert type(R(a="x", b="y")) is X

    def test_turning_polymorphic_off_is_a_boundary(self) -> None:
        class Rb(Magic, polymorphic=True):
            kind: str = ""

        class Mb(Rb, polymorphic=False):
            pass

        class Sb(Mb, polymorphic=True):
            pass

        class Xb(Sb, on={"kind": "x"}):
            pass

        assert Xb.__dict__[_REGISTRATION][0] == (Sb,)
        assert type(Rb(kind="x")) is Rb
        assert type(Sb(kind="x")) is Xb

    def test_a_plain_mixin_in_front_is_no_boundary(self) -> None:
        class Mixin(Magic):
            pass

        class R(Magic, polymorphic=True):
            kind: str = ""

        class X(Mixin, R, on={"kind": "x"}):
            pass

        assert X.__dict__[_REGISTRATION][0] == (R,)
        assert type(R(kind="x")) is X

    # -- a diamond with nothing to say (problem B) -----------------------

    @pytest.fixture
    def axes(self) -> tx.Dict[str, type]:
        class Axis(Magic, polymorphic=True):
            name: str = ""
            type: tx.Optional[str] = None
            orientation: tx.Optional[str] = None

        class SpatialAxis(Axis, on={"type": "space"}):
            type: tx.Literal["space"] = "space"

        class OrientedAxis(
            Axis, on={"orientation": lambda v: v is not None}
        ):
            pass

        class OrientedSpatialAxis(SpatialAxis, OrientedAxis):
            pass

        class AnatomicalAxis(
            OrientedSpatialAxis,
            on={"orientation": lambda v: v in {"LR", "RL"}},
        ):
            pass

        return {
            cls.__name__: cls
            for cls in (Axis, SpatialAxis, OrientedAxis,
                        OrientedSpatialAxis, AnatomicalAxis)
        }

    def test_a_diamond_is_reached_from_the_root(
        self, axes: tx.Dict[str, type]
    ) -> None:
        Axis = axes["Axis"]
        assert type(Axis(type="space", orientation="AP")) is axes[
            "OrientedSpatialAxis"]
        assert type(Axis(type="space", orientation="LR")) is axes[
            "AnatomicalAxis"]

    def test_a_diamond_is_reached_from_either_parent(
        self, axes: tx.Dict[str, type]
    ) -> None:
        anatomical = axes["AnatomicalAxis"]
        assert type(axes["SpatialAxis"](orientation="LR")) is anatomical
        assert type(
            axes["OrientedAxis"](type="space", orientation="LR")
        ) is anatomical
        assert type(axes["SpatialAxis"](orientation="AP")) is axes[
            "OrientedSpatialAxis"]

    def test_a_diamond_stands_for_what_both_parents_do(
        self, axes: tx.Dict[str, type]
    ) -> None:
        # It is not reached on one parent's constraint alone.
        assert type(axes["SpatialAxis"]("x")) is axes["SpatialAxis"]
        assert type(axes["SpatialAxis"]()) is axes["SpatialAxis"]
        assert type(axes["Axis"](type="space")) is axes["SpatialAxis"]
        assert type(axes["OrientedAxis"](orientation="LR")) is axes[
            "OrientedAxis"]

    def test_a_missing_field_is_never_guessed(
        self, axes: tx.Dict[str, type]
    ) -> None:
        # `type` is not given, so nothing says this is a spatial axis:
        # the choice goes on what was passed, not on what would fit.
        assert type(axes["Axis"]("x", orientation="LR")) is axes[
            "OrientedAxis"]

    def test_the_combined_constraint_is_registered_once_per_owner(
        self, axes: tx.Dict[str, type]
    ) -> None:
        both = axes["OrientedSpatialAxis"]
        owners, specs, priority, claim = both.__dict__[_REGISTRATION]
        assert owners == (
            axes["SpatialAxis"], axes["OrientedAxis"], axes["Axis"]
        )
        assert [spec.name for spec in specs] == ["type", "orientation"]
        assert priority == 0
        assert claim is specs
        # The leaf below it is in a chain again, and registers with it
        # alone, standing for its own constraint.
        leaf = axes["AnatomicalAxis"].__dict__[_REGISTRATION]
        assert leaf[0] == (both,)
        assert [spec.name for spec in leaf[1]] == ["orientation"]

    def test_an_empty_on_in_a_diamond_is_the_same_combination(
        self, axes: tx.Dict[str, type]
    ) -> None:
        class Again(axes["SpatialAxis"], axes["OrientedAxis"], on={}):
            pass

        specs = Again.__dict__[_REGISTRATION][1]
        assert [spec.name for spec in specs] == ["type", "orientation"]
        assert type(axes["SpatialAxis"]()) is axes["SpatialAxis"]

    def test_a_diamond_that_turns_polymorphic_off_is_left_alone(
        self, axes: tx.Dict[str, type]
    ) -> None:
        class Off(axes["SpatialAxis"], axes["OrientedAxis"],
                  polymorphic=False):
            pass

        assert _REGISTRATION not in Off.__dict__

    def test_on_none_leaves_a_diamond_out(
        self, axes: tx.Dict[str, type]
    ) -> None:
        class Aside(axes["SpatialAxis"], axes["OrientedAxis"], on=None):
            pass

        assert _REGISTRATION not in Aside.__dict__
        assert type(Aside(orientation="AP")) is Aside
        assert all(
            entry.target is not Aside
            for entry in axes["Axis"].__dict__[_POLYMORPHS].dispatch[0]
        )

    # -- a diamond that says something (problems C and D) ----------------

    def test_a_diamond_with_priority_on_one_branch(self) -> None:
        def is_2d(axes: tx.Any) -> bool:
            return len(axes) == 2

        def is_spatial(axes: tx.Any) -> bool:
            return all(axis == "space" for axis in axes)

        def is_spatial_2d(axes: tx.Any) -> bool:
            return is_2d(axes) and is_spatial(axes)

        class CoordinateSystem(Magic, polymorphic=True):
            axes: tx.Tuple[str, ...] = ()

        class CoordinateSystem2D(CoordinateSystem, on={"axes": is_2d}):
            pass

        class SpatialCoordinateSystem(
            CoordinateSystem, on={"axes": is_spatial}, priority=1
        ):
            pass

        class SpatialCoordinateSystem2D(
            CoordinateSystem2D, SpatialCoordinateSystem,
            on={"axes": is_spatial_2d},
        ):
            pass

        plane = ("space", "space")
        assert type(SpatialCoordinateSystem(axes=plane)) is (
            SpatialCoordinateSystem2D)
        assert type(CoordinateSystem(axes=plane)) is (
            SpatialCoordinateSystem2D)
        assert type(CoordinateSystem2D(axes=plane)) is (
            SpatialCoordinateSystem2D)
        assert type(CoordinateSystem(axes=("time", "space"))) is (
            CoordinateSystem2D)
        assert type(CoordinateSystem(axes=("space",) * 3)) is (
            SpatialCoordinateSystem)

    @pytest.fixture
    def tones(self) -> tx.Tuple[type, type, type]:
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""

        class SA(R, on={"a": "x"}):
            pass

        class SB(R, on={"b": "y"}):
            pass

        return R, SA, SB

    def test_tied_siblings_are_settled_by_the_class_below_both(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SAB(SA, SB, on={"a": "x", "b": "y"}):
            pass

        assert type(R(a="x", b="y")) is SAB
        assert type(SA(b="y")) is SAB
        assert type(SB(a="x")) is SAB
        assert type(R(a="x")) is SA

    def test_tied_siblings_are_settled_with_nothing_said(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SAB(SA, SB):
            pass

        assert type(R(a="x", b="y")) is SAB

    def test_what_a_diamond_says_can_only_narrow(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SAB(SA, SB, on={"a": {"x", "z"}}):
            pass

        specs = SAB.__dict__[_REGISTRATION][1]
        assert [spec.name for spec in specs] == ["a", "b"]
        # Its own "or z" cannot widen what SA stands for.
        assert type(R(a="z", b="y")) is SB
        assert type(R(a="x", b="y")) is SAB

    def test_contradicting_parents_are_refused_by_field(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SX(R, on={"a": "q"}):
            pass

        with pytest.raises(TypeError) as raised:
            class Both(SA, SX):
                pass

        message = str(raised.value)
        assert "Nothing can build Both" in message
        assert "a='x'" in message and "a='q'" in message
        assert "through SA" in message and "through SX" in message
        assert "on=None" in message

    def test_contradicting_parents_build_with_on_none(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SX(R, on={"a": "q"}):
            pass

        class Both(SA, SX, on=None):
            pass

        assert _REGISTRATION not in Both.__dict__
        assert type(R(a="x")) is SA

    def test_contradicting_its_own_parent_is_refused(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones
        with pytest.raises(TypeError, match="through its own on="):
            class Both(SA, SB, on={"b": "n"}):
                pass

    def test_a_subclass_of_an_opted_out_diamond(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        # on=None makes the class a plain intermediate, which a subclass
        # saying something registers through.
        R, SA, SB = tones

        class Aside(SA, SB, on=None):
            pass

        class Below(Aside, on={"a": "x"}):
            pass

        owners = Below.__dict__[_REGISTRATION][0]
        assert owners == (Aside, SA, SB, R)
        assert type(R(a="x", b="y")) is Below

    def test_priority_with_on_none_is_refused(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones
        with pytest.raises(TypeError, match="priority= without on="):
            class Both(SA, SB, on=None, priority=1):
                pass

    def test_on_none_in_a_chain_changes_nothing(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class Quiet(SA, on=None):
            pass

        assert _REGISTRATION not in Quiet.__dict__
        assert type(R(a="x")) is SA

    def test_owners_without_the_field_are_skipped_in_a_diamond(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class Wide(SA):
            extra: str = ""

        class Both(Wide, SB, on={"extra": "e"}):
            pass

        assert Both.__dict__[_REGISTRATION][0] == (Wide,)
        assert type(Wide(a="x", b="y", extra="e")) is Both
        assert type(Wide(a="x", b="n", extra="e")) is Wide

    def test_a_combination_no_owner_can_read_is_left_out(self) -> None:
        class R1(Magic, polymorphic=True):
            a: str = ""

        class R2(Magic, polymorphic=True):
            b: str = ""

        class SA1(R1, on={"a": "x"}):
            pass

        class SB2(R2, on={"b": "y"}):
            pass

        class Both(SA1, SB2):
            pass

        assert _REGISTRATION not in Both.__dict__
        assert type(Both(a="x", b="y")) is Both

    def test_a_diamond_of_diamonds_counts_each_constraint_once(
        self, tones: tx.Tuple[type, type, type]
    ) -> None:
        R, SA, SB = tones

        class SAB(SA, SB):
            pass

        class SC(R, on={"a": {"x", "w"}}):
            pass

        class All(SAB, SC):
            pass

        (a, b) = All.__dict__[_REGISTRATION][1]
        # SA's and SB's constraints reach it through SAB and again from
        # SA and SB themselves, and are counted once.
        assert a.text == "'x' and {'w', 'x'}"
        assert b.text == "'y'"
        assert a.value == "x"
        assert type(R(a="x", b="y")) is All

    def test_a_strict_diamond_keeps_the_combined_invariant(self) -> None:
        class R(Magic, polymorphic="strict"):
            a: str = ""
            b: str = ""

        class SA(R, on={"a": "x"}):
            pass

        class SB(R, on={"b": "y"}):
            pass

        class SAB(SA, SB):
            pass

        assert type(SAB(a="x", b="y")) is SAB
        with pytest.raises(PolymorphError, match="contradicts"):
            SAB(a="x", b="n")
        assert type(R(a="x", b="y")) is SAB

    def test_a_diamond_over_a_generic_root(self) -> None:
        class GRoot(Magic, tx.Generic[_T], polymorphic=True, convert=True):
            value: _T
            kind: str = ""
            shade: str = ""

        class GA(GRoot[_T], on={"kind": "a"}):
            pass

        class GB(GRoot[_T], on={"shade": "b"}):
            pass

        class GAB(GA[_T], GB[_T]):
            pass

        built = GRoot[int](value="1", kind="a", shade="b")
        assert type(built) is GAB[int]
        assert built.value == 1
        assert type(GRoot(value="1", kind="a", shade="b")) is GAB
        assert type(GA[int](value="1", shade="b")) is GAB[int]
        # A parameterisation is not a class anyone wrote, so it is never
        # registered in its own right.
        assert _REGISTRATION not in GAB[int].__dict__

    def test_a_parameterisation_of_an_opted_out_diamond_stays_out(
        self
    ) -> None:
        class GRoot(Magic, tx.Generic[_T], polymorphic=True):
            value: _T
            kind: str = ""
            shade: str = ""

        class GA(GRoot[_T], on={"kind": "a"}):
            pass

        class GB(GRoot[_T], on={"shade": "b"}):
            pass

        class GAB(GA[_T], GB[_T], on=None):
            pass

        assert _REGISTRATION not in GAB[int].__dict__

    def test_narrowed_parents_are_not_narrowed_again(self) -> None:
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""

        class SA(R, on={"a": "x"}, pin_discriminant="narrow"):
            pass

        class SB(R, on={"b": "y"}, pin_discriminant="narrow"):
            pass

        class SAB(SA, SB):
            pass

        # The field is SA's, with SA's validator on it, and nothing was
        # chained on top of it a second time.
        mine = getattr(SAB, _FIELDS)["a"]
        theirs = getattr(SA, _FIELDS)["a"]
        assert mine.validator is theirs.validator
        assert mine.type == theirs.type == tx.Literal["x"]
        assert type(R(a="x", b="y")) is SAB
        with pytest.raises(Exception, match="expected a value that is 'x'"):
            SAB(a="q", b="y")
        # `b` came from SA as R left it, so SB's narrowing is applied to
        # it here -- once.
        b = getattr(SAB, _FIELDS)["b"]
        assert b.type == tx.Literal["y"]
        assert b._narrowed_by == getattr(SB, _FIELDS)["b"]._narrowed_by
        assert SAB().b == "y"
        with pytest.raises(Exception, match="expected a value that is 'y'"):
            SAB(a="x", b="z")

    # -- what the second parent did to a field ---------------------------

    @staticmethod
    def _diamond(**options: tx.Any) -> tx.Tuple[type, type, type, type]:
        class R(Magic, **options):
            a: str = ""
            b: str = ""

        class SA(R, on={"a": "x"}):
            pass

        class SB(R, on={"b": "y"}):
            pass

        class SAB(SA, SB):
            pass

        return R, SA, SB, SAB

    def test_the_second_parents_pin_reaches_the_diamond(self) -> None:
        R, SA, SB, SAB = self._diamond(polymorphic=True)
        assert SB(a="x") == SAB(a="x", b="y")
        assert type(SB(a="x")) is SAB
        assert SAB() == SAB(a="x", b="y")
        assert "b" in SAB.__dict__[_PINNED]

    def test_a_strict_diamond_builds_from_its_pins(self) -> None:
        R, SA, SB, SAB = self._diamond(polymorphic="strict")
        assert type(SAB()) is SAB
        assert type(SB(a="x")) is SAB
        assert type(SA(b="y")) is SAB

    def test_the_diamond_stores_the_way_its_own_option_says(self) -> None:
        R, SA, SB, SAB = self._diamond(
            polymorphic=True, pin_discriminant="classvar"
        )
        assert SAB.b == "y"
        assert "b" not in asdict(SAB())

    def test_a_default_that_already_fits_is_left_alone(self) -> None:
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = "y"

        class SA(R, on={"a": "x"}):
            pass

        class SB(R, on={"b": "y"}, pin_discriminant="classvar"):
            pass

        class SAB(SA, SB, pin_discriminant="classvar"):
            pass

        # `b` already holds "y" as SA inherited it, so it is not made a
        # class attribute a second way.
        assert "b" in asdict(SAB())
        assert SAB().b == "y"

    def test_swapped_parents_pin_the_same(self) -> None:
        class Axis(Magic, polymorphic=True):
            name: str = ""
            type: tx.Optional[str] = None
            orientation: tx.Optional[str] = None

        class SpatialAxis(Axis, on={"type": "space"}):
            pass

        class OrientedAxis(
            Axis, on={"orientation": lambda v: v is not None}
        ):
            pass

        class OrientedSpatialAxis(OrientedAxis, SpatialAxis):
            pass

        # `type` came from OrientedAxis as Axis left it; the diamond
        # still pins it to what SpatialAxis stands for.
        assert getattr(OrientedAxis, _FIELDS)["type"].default is None
        assert OrientedSpatialAxis(orientation="AP").type == "space"
        built = OrientedAxis(orientation="AP", type="space")
        assert type(built) is OrientedSpatialAxis
        assert built == OrientedSpatialAxis(orientation="AP")

    def test_a_diamond_of_diamonds_chains_each_part_once(self) -> None:
        asked = []

        def counted(value: tx.Any) -> bool:
            asked.append(value)
            return value in ("x", "w")

        class R(Magic, polymorphic=True, pin_discriminant="narrow"):
            a: str = ""
            b: str = ""

        class SA(R, on={"a": "x"}):
            pass

        class SB(R, on={"b": "y"}):
            pass

        class SC(R, on={"a": counted}):
            pass

        class SAB(SA, SB):
            pass

        class All(SAB, SC):
            pass

        a = getattr(All, _FIELDS)["a"]
        assert len(a._narrowed_by) == len(
            {id(part) for part in a._narrowed_by}) == 2
        assert len(getattr(All, _FIELDS)["b"]._narrowed_by) == 1
        del asked[:]
        All(a="x", b="y")
        assert asked == ["x"]


class TestRankingTheWholeClaim:
    """A subclass is ranked on everything it stands for."""

    def test_a_chain_child_is_not_outranked_by_a_diamond(self) -> None:
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""
            c: str = ""

        class SAr(R, on={"a": "x"}):
            pass

        class SBr(R, on={"b": "y"}):
            pass

        class SABr(SAr, SBr):
            pass

        class SAXr(SAr, on={"b": "y", "c": "z"}):
            pass

        assert type(SAr(b="y", c="z")) is SAXr
        assert type(SAr(b="y")) is SABr
        assert [spec.name for spec in SAXr.__dict__[_REGISTRATION][3]] == [
            "b", "c", "a"]

    def test_a_child_standing_for_another_value_is_still_registered(
        self
    ) -> None:
        class R(Magic, polymorphic=True):
            a: str = ""

        class S(R, on={"a": "x"}):
            pass

        class T(S, on={"a": "q"}):
            pass

        owners, specs, priority, claim = T.__dict__[_REGISTRATION]
        assert owners == (S,)
        assert claim is specs
        assert type(S(a="q")) is T
        assert type(R(a="q")) is R

    def test_a_class_registered_by_hand_is_ranked_the_same_way(
        self
    ) -> None:
        class R(Magic, polymorphic=True):
            a: str = ""
            b: str = ""

        class S(R, on={"a": "x"}):
            pass

        class Mid(S):
            pass

        S.register_polymorph(Mid, b="y")
        claim = Mid.__dict__[_REGISTRATION][3]
        assert [spec.name for spec in claim] == ["b", "a"]


class TestConjoin:
    """Combining the constraints several classes put on one field."""

    @staticmethod
    def _one(*written: tx.Any) -> tx.Any:
        # Each constraint as if written by a separate registered class.
        specs = [p._specification("f", spec) for spec in written]
        inherited = [
            (type(f"C{index}", (), {}), (spec,))
            for index, spec in enumerate(specs[1:])
        ]
        (merged,) = p.conjoin("Both", (specs[0],), inherited)
        return merged

    def test_presence_adds_nothing_either_way(self) -> None:
        assert self._one(..., "x").text == "'x'"
        assert self._one("x", ...).text == "'x'"
        assert self._one(..., ...).text == "anything"

    def test_two_sets_meet_in_their_common_values(self) -> None:
        merged = self._one({"x", "y", "z"}, {"y", "z", "w"})
        assert merged.members == ("y", "z")
        assert merged.value is MISSING
        assert merged.narrowed == tx.Literal["y", "z"]
        assert merged.matches("y") and not merged.matches("x")
        assert not merged.matches([])  # unhashable reads as no match

    def test_two_sets_with_nothing_in_common_are_refused(self) -> None:
        with pytest.raises(TypeError, match="no value of 'f' is both"):
            self._one({"x"}, {"y"})

    def test_an_exact_value_outside_a_set_is_refused(self) -> None:
        with pytest.raises(TypeError, match="Nothing can build Both"):
            self._one({"x", "y"}, "z")

    def test_an_exact_value_inside_a_set_is_kept(self) -> None:
        merged = self._one({"x", "y"}, "x")
        assert merged.value == "x"
        assert merged.members is None
        assert merged.narrowed == tx.Literal["x"]
        assert merged.precision == 4

    def test_a_question_is_not_asked_when_the_class_is_written(
        self
    ) -> None:
        asked = []

        def question(value: tx.Any) -> bool:
            asked.append(value)
            return value > 1

        merged = self._one(question, {1, 2, 3})
        assert asked == []
        # The set is kept whole: the question is asked at run time.
        assert merged.members == (1, 2, 3)
        assert merged.narrowed == tx.Literal[1, 2, 3]
        assert merged.matches(2) and not merged.matches(1)

    def test_a_question_is_never_used_to_refuse(self) -> None:
        merged = self._one({1, 2}, lambda v: v > 5)
        assert not merged.matches(1) and not merged.matches(2)

    def test_a_set_is_still_put_to_the_rest_of_a_combination(self) -> None:
        # Merged with a question first, then with a set: the second set
        # is judged by the first, and the question is still not asked.
        R = type("R", (), {})
        specs = [p._specification("f", spec)
                 for spec in ({1, 2}, lambda v: 1 / 0, {2, 3}, {4})]
        (merged,) = p.conjoin("Both", (specs[0],), [(R, (specs[1],))])
        (again,) = p.conjoin("Both", (merged,), [(R, (specs[2],))])
        assert again.members == (2,)
        with pytest.raises(TypeError, match="no value of 'f' is both"):
            p.conjoin("Both", (merged,), [(R, (specs[3],))])

    def test_two_equal_values_read_as_one(self) -> None:
        merged = self._one("x", "x")
        assert merged.text == "'x'"
        assert merged.value == "x"

    def test_an_exact_value_failing_a_type_is_refused(self) -> None:
        with pytest.raises(TypeError, match="no value of 'f' is both"):
            self._one("x", int)

    def test_an_exact_value_failing_a_pattern_is_refused(self) -> None:
        with pytest.raises(TypeError, match="no value of 'f' is both"):
            self._one(re.compile("[a-z]+"), "X1")

    def test_a_value_no_literal_can_hold_takes_the_type(self) -> None:
        assert self._one(1.5, float).narrowed is float
        assert self._one({1.5, 2.5}, float).narrowed is float

    def test_two_open_constraints_are_left_to_run_time(self) -> None:
        merged = self._one(re.compile("[a-z]+"), lambda v: len(v) > 2)
        assert merged.narrowed is MISSING
        assert merged.members is None
        assert merged.matches("abc") and not merged.matches("ab")
        assert not merged.matches("AB1")

    def test_the_combined_check_asks_both(self) -> None:
        merged = self._one({"x", "y"}, lambda v: v != "y")
        assert merged.validate("x") == "x"
        with pytest.raises(ValueValidationError, match="expected"):
            merged.validate("y")


class TestRegisterPolymorphRecord:
    """What registering by hand leaves behind on the class registered."""

    @pytest.fixture
    def base(self) -> type:
        class Root(Magic, polymorphic=True):
            kind: str = ""
            flavour: str = ""

        return Root

    def test_a_strict_leaf_registered_by_hand_can_be_built(self) -> None:
        class Strict(Magic, polymorphic="strict"):
            kind: str = ""

        class Dim(Strict):
            pass

        Strict.register_polymorph(Dim, kind="dim")
        assert type(Strict(kind="dim")) is Dim
        assert type(Dim(kind="dim")) is Dim
        with pytest.raises(PolymorphError, match="contradicts"):
            Dim(kind="other")

    def test_a_later_subclass_registers_with_the_class_by_hand(
        self, base: type
    ) -> None:
        class Inner(base):
            pass

        base.register_polymorph(Inner, kind="k")

        class Deeper(Inner, on={"flavour": "f"}):
            pass

        # Inner is reached from the root, so Deeper need not climb past it.
        assert Deeper.__dict__[_REGISTRATION][0] == (Inner,)
        assert type(base(kind="k", flavour="f")) is Deeper
        assert type(base(flavour="f")) is base

    def test_it_only_registers_where_it_is_called(self, base: type) -> None:
        class Middle(base, on={"kind": "k"}):
            pass

        class Leaf(Middle):
            pass

        Middle.register_polymorph(Leaf, flavour="f")
        assert Leaf.__dict__[_REGISTRATION][0] == (Middle,)
        assert all(
            entry.target is not Leaf
            for entry in base.__dict__[_POLYMORPHS].dispatch[0]
        )
        assert type(base(kind="k", flavour="f")) is Leaf

    def test_a_class_statement_registration_is_kept(self, base: type) -> None:
        class Middle(base, on={"kind": "k"}):
            pass

        class Leaf(Middle, on={"flavour": "f"}):
            pass

        base.register_polymorph(Leaf, kind="k", flavour="f")
        assert Leaf.__dict__[_REGISTRATION][0] == (Middle,)

    def test_a_parameterisation_made_before_registering_by_hand(
        self
    ) -> None:
        class Strict(Magic, tx.Generic[_T], polymorphic="strict"):
            kind: str = ""

        class Dim(Strict[_T]):
            pass

        early = Dim[int]
        Strict.register_polymorph(Dim, kind="dim")
        assert type(Strict[int](kind="dim")) is early
        assert type(early(kind="dim")) is early
        with pytest.raises(PolymorphError, match="contradicts"):
            early(kind="other")

    def test_a_parameterisation_of_an_unarmed_origin(self) -> None:
        # Nothing has registered with Loose, so it has no registry for
        # its parameterisation to read, and nothing is required of it.
        class Loose(Magic, tx.Generic[_T], polymorphic=True):
            kind: str = ""

        found = Loose[int].__dict__[_POLYMORPHS]
        assert found.required is False
        assert found.invariant is None
        assert type(Loose[int](kind="k")) is Loose[int]

    def test_a_parameterisation_carries_no_record(self) -> None:
        class Root(Magic, tx.Generic[_T], polymorphic=True):
            kind: str = ""

        class Sub(Root[_T]):
            pass

        Root.register_polymorph(Sub[int], kind="s")
        assert _REGISTRATION not in Sub[int].__dict__
        assert _REGISTRATION not in Sub.__dict__
