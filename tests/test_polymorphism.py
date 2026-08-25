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

# dependencies
import pytest
import typing_extensions as tx
from bagof.converters.exceptions import ConversionError

# locals
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
    asdict,
    magic,
    replace,
)

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

    def test_a_hand_written_classvar_discriminant_is_refused(
        self, base: type
    ) -> None:
        # The base passes `mode` straight through, so a subclass whose
        # constructor does not take it could only be reached by a call
        # that then fails inside the delegation.
        with pytest.raises(TypeError, match="pin_discriminant='classvar'"):
            class Minor(base, on={"mode": "minor"}):
                mode: ClassVar[str] = "minor"

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

    def test_two_hand_written_fields_are_still_refused(self) -> None:
        # Nothing here was pinned, so the class is refused as before.
        class First(Magic, polymorphic=True):
            a: int = 0

        with pytest.raises(SyntaxError, match="without a default"):
            class Second(First):
                b: int


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
