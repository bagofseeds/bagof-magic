"""Unit tests for the bagof.magic module."""
import copy
import inspect
import operator
import pickle
import re
from inspect import Parameter, signature
from typing import ClassVar as TypingClassVar
from typing import Optional, Union

import pytest
import typing_extensions as tx
from bagof.converters.exceptions import (
    ConversionError,
    ValueConversionError,
)
from bagof.validators.exceptions import ValidationError
from typing_extensions import Annotated

import bagof.magic._api as _api
import bagof.magic._fields as _fields
import bagof.magic._magic as m
from bagof.magic import (
    HIDE_IF_NONE,
    Arguments,
    ClassVar,
    ConvertTo,
    Default,
    Doc,
    Factory,
    Field,
    Frozen,
    Init,
    InitVar,
    Key,
    Kw,
    KwOnly,
    Magic,
    NoCompare,
    NoEq,
    NoHash,
    NoInit,
    NoOrder,
    NoRepr,
    NotFrozen,
    NotKey,
    NotKw,
    NotKwOnly,
    NotPositional,
    NotPositionalOnly,
    Positional,
    PositionalOnly,
    Validate,
    magic,
)
from bagof.magic._constants import (
    _FIELDS,
    _GENERATED,
    _OPTIONS,
    MISSING,
    REQUIRED,
    SHOW_ATTR,
)
from bagof.magic._constants import (
    HIDE_IF_NONE as HideIfNoneCls,
)
from bagof.magic._options import Options
from bagof.magic._utils import (
    _update_func_cell_for__class__,
    rebuild_cls,
    slots,
)

# ======================================================================
# Constants
# ======================================================================


class TestMissing:

    def test_singleton(self) -> None:
        assert MISSING is MISSING
        from bagof.magic._constants import _MissingType
        assert _MissingType() is MISSING

    def test_bool_is_false(self) -> None:
        assert not MISSING

    def test_repr(self) -> None:
        assert repr(MISSING) == "<MISSING>"


# ======================================================================
# Options
# ======================================================================


class TestOptions:

    def test_make_default(self) -> None:
        opts = Options.make_default()
        assert opts.init is True
        assert opts.repr is True
        assert opts.eq is True
        assert opts.order is False
        assert opts.unsafe_hash is False
        assert opts.frozen is False
        assert opts.match_args is False
        assert opts.kw_only is False
        assert opts.slots is False
        assert opts.weakref_slot is False
        assert opts.factory is False
        assert opts.mutable_default == "factory"
        assert opts.convert is False
        assert opts.validate is False

    def test_update(self) -> None:
        opts = Options.make_default()
        override = Options(frozen=True, kw_only=True)
        opts.update(override)
        assert opts.frozen is True
        assert opts.kw_only is True
        # unchanged
        assert opts.init is True

    def test_setdefault(self) -> None:
        opts = Options(frozen=MISSING, kw_only=True)
        defaults = Options.make_default()
        opts.setdefault(defaults)
        assert opts.frozen is False  # was MISSING -> filled
        assert opts.kw_only is True  # was set -> kept

    def test_repr(self) -> None:
        opts = Options(frozen=True)
        r = repr(opts)
        assert "frozen=True" in r


# ======================================================================
# Basic Magic (inheritance API)
# ======================================================================


class TestBasicStruct:

    def test_simple_class(self) -> None:
        class Point(Magic):
            x: int
            y: int

        p = Point(1, 2)
        assert p.x == 1
        assert p.y == 2

    def test_repr(self) -> None:
        class Point(Magic):
            x: int
            y: int

        p = Point(1, 2)
        assert repr(p) == "Point(x=1, y=2)"

    def test_eq(self) -> None:
        class Point(Magic):
            x: int
            y: int

        assert Point(1, 2) == Point(1, 2)
        assert Point(1, 2) != Point(1, 3)

    def test_eq_different_class(self) -> None:
        class A(Magic):
            x: int

        class B(Magic):
            x: int

        assert A(1) != B(1)
        assert A(1).__eq__(B(1)) is NotImplemented

    def test_keyword_args(self) -> None:
        class Point(Magic):
            x: int
            y: int

        p = Point(x=10, y=20)
        assert p.x == 10
        assert p.y == 20

    def test_mixed_args(self) -> None:
        class Point(Magic):
            x: int
            y: int

        p = Point(10, y=20)
        assert p.x == 10
        assert p.y == 20

    def test_missing_required_arg(self) -> None:
        class Point(Magic):
            x: int
            y: int

        with pytest.raises(
            TypeError, match="missing 1 required positional argument"
        ):
            Point(1)

    def test_too_many_positional_args(self) -> None:
        class Point(Magic):
            x: int

        with pytest.raises(
            TypeError,
            match="takes 2 positional arguments but 3 were given",
        ):
            Point(1, 2)

    def test_unexpected_kwarg(self) -> None:
        class Point(Magic):
            x: int

        with pytest.raises(
            TypeError, match="got an unexpected keyword argument"
        ):
            Point(x=1, z=2)


# ======================================================================
# Magic via decorator
# ======================================================================


class TestStructDecorator:

    def test_decorator_no_args(self) -> None:
        @magic
        class Point:
            x: int
            y: int

        p = Point(1, 2)
        assert p.x == 1
        assert p.y == 2

    def test_decorator_with_options(self) -> None:
        @magic(frozen=True, eq=True)
        class Point:
            x: int
            y: int

        p = Point(3, 4)
        assert p.x == 3
        with pytest.raises(AttributeError):
            p.x = 10


# ======================================================================
# Default values
# ======================================================================


class TestDefaults:

    def test_default_via_class_attribute(self) -> None:
        class Point(Magic):
            x: int
            y: int = 0

        p = Point(1)
        assert p.x == 1
        assert p.y == 0

    def test_default_annotation(self) -> None:
        class Point(Magic):
            x: int
            y: Default[int, 0]

        p = Point(1)
        assert p.y == 0

    def test_default_factory_annotation(self) -> None:
        class Container(Magic):
            items: Factory[list]

        c = Container()
        assert c.items == []

    def test_default_factory_custom(self) -> None:
        class Container(Magic):
            items: Factory[list, lambda: [1, 2]]

        c = Container()
        assert c.items == [1, 2]

    def test_default_factory_independent_instances(self) -> None:
        class Container(Magic):
            items: Factory[list]

        a = Container()
        b = Container()
        a.items.append(1)
        assert b.items == []


# ======================================================================
# Frozen
# ======================================================================


class TestFrozen:

    def test_frozen_class(self) -> None:
        class Point(Magic, frozen=True):
            x: int
            y: int

        p = Point(1, 2)
        with pytest.raises(AttributeError, match="Cannot set frozen field"):
            p.x = 10

    def test_frozen_delete(self) -> None:
        class Point(Magic, frozen=True):
            x: int
            y: int

        p = Point(1, 2)
        with pytest.raises(AttributeError, match="Cannot delete frozen field"):
            del p.x

    def test_frozen_field_annotation(self) -> None:
        class Point(Magic):
            x: Frozen[int]
            y: int

        p = Point(1, 2)
        with pytest.raises(AttributeError, match="Cannot set frozen field"):
            p.x = 10
        # y is not frozen
        p.y = 20
        assert p.y == 20

    def test_not_frozen_field_annotation(self) -> None:
        class Point(Magic, frozen=True):
            x: NotFrozen[int]
            y: int

        p = Point(1, 2)
        # y is frozen (class-level)
        with pytest.raises(AttributeError):
            p.y = 10
        # x is explicitly not frozen
        p.x = 10
        assert p.x == 10


# ======================================================================
# KwOnly
# ======================================================================


class TestKwOnly:

    def test_kw_only_class(self) -> None:
        class Point(Magic, kw_only=True):
            x: int
            y: int

        p = Point(x=1, y=2)
        assert p.x == 1
        with pytest.raises(
            TypeError,
            match="takes 1 positional argument but 3 were given",
        ):
            Point(1, 2)

    def test_kw_only_field_annotation(self) -> None:
        class Point(Magic):
            x: int
            y: KwOnly[int]

        p = Point(1, y=2)
        assert p.y == 2


# ======================================================================
# Init / NoInit
# ======================================================================


class TestInit:

    def test_no_init_field(self) -> None:
        class Point(Magic):
            x: int
            y: NoInit[int] = 0

        p = Point(1)
        assert p.x == 1
        assert p.y == 0

    def test_no_init_field_rejects_positional(self) -> None:
        class Point(Magic):
            x: int
            y: NoInit[int] = 0

        with pytest.raises(
            TypeError,
            match="takes 2 positional arguments but 3 were given",
        ):
            Point(1, 2)

    def test_no_init_field_rejects_keyword(self) -> None:
        class Point(Magic):
            x: int
            y: NoInit[int] = 0

        with pytest.raises(
            TypeError, match="got an unexpected keyword argument 'y'"
        ):
            Point(x=1, y=2)

    def test_no_init_class(self) -> None:
        class Point(Magic, init=False):
            x: int = 0
            y: int = 0

        p = Point()
        assert p.x == 0
        assert p.y == 0


# ======================================================================
# The parameter annotations
# ======================================================================


def _parameter_kind(annotation: tx.Any, **options: tx.Any) -> tx.Any:
    """How the constructor of a one-field class takes that field.

    `None` when it does not take it at all.
    """

    class One(Magic, **options):
        x: annotation[int] = 0

    parameter = signature(One).parameters.get("x")
    return None if parameter is None else parameter.kind


class TestParameterAnnotations:
    """What each annotation makes of the field it is written on.

    An annotation sets the halves of the pair its own name mentions --
    may this field be passed by name, may it be passed by position --
    and what it sets beats the class setting. Whatever it says nothing
    about follows the class.
    """

    BOTH = Parameter.POSITIONAL_OR_KEYWORD
    BY_NAME = Parameter.KEYWORD_ONLY
    BY_POSITION = Parameter.POSITIONAL_ONLY
    NEITHER = None

    # (annotation, on a plain class, on kw_only=True, on
    #  positional_only=True)
    CASES = [
        (Init, BOTH, BY_NAME, BY_POSITION),
        (NoInit, NEITHER, NEITHER, NEITHER),
        (Kw, BOTH, BY_NAME, BOTH),
        (NotKw, BY_POSITION, NEITHER, BY_POSITION),
        (Positional, BOTH, BOTH, BY_POSITION),
        (NotPositional, BY_NAME, BY_NAME, NEITHER),
        (KwOnly, BY_NAME, BY_NAME, BY_NAME),
        (PositionalOnly, BY_POSITION, BY_POSITION, BY_POSITION),
        (NotKwOnly, BOTH, BOTH, BY_POSITION),
        (NotPositionalOnly, BOTH, BY_NAME, BOTH),
    ]

    @pytest.mark.parametrize(
        "annotation,plain,kw_only,positional_only",
        CASES,
        ids=[case[0].__name__ for case in CASES],
    )
    def test_signature(
        self,
        annotation: tx.Any,
        plain: tx.Any,
        kw_only: tx.Any,
        positional_only: tx.Any,
    ) -> None:
        assert _parameter_kind(annotation) is plain
        assert _parameter_kind(annotation, kw_only=True) is kw_only
        assert (
            _parameter_kind(annotation, positional_only=True)
            is positional_only
        )

    @pytest.mark.parametrize(
        "options",
        [{}, {"kw_only": True}, {"positional_only": True}],
        ids=["plain", "kw_only", "positional_only"],
    )
    def test_init_leaves_the_signature_alone(
        self, options: tx.Dict[str, bool]
    ) -> None:
        # `Init` only says a field is an argument, which it already
        # was, so the signature must come out as if it were not there.
        class Bare(Magic, **options):
            a: int
            b: int = 0

        class Spelled(Magic, **options):
            a: Init[int]
            b: Init[int] = 0

        assert str(signature(Spelled)) == str(signature(Bare))

    def test_init_does_not_move_a_field_up_the_signature(self) -> None:
        # A field that can be passed by position is bound before the
        # keyword-only ones whatever order it was declared in, so an
        # annotation that only means "yes, an argument" must not make
        # one passable by position.
        class E(Magic, kw_only=True):
            a: int
            x: Init[int]

        assert list(signature(E).parameters) == ["a", "x"]
        assert E(a=2, x=1) == E(x=1, a=2)
        with pytest.raises(TypeError):
            E(1, a=2)

    def test_the_two_inverses_differ(self) -> None:
        # Each is the negation of its own name: not keyword-only leaves
        # the field passable by position, not positional-only leaves it
        # passable by name.
        class ByPositionToo(Magic, kw_only=True):
            x: NotKwOnly[int]

        class ByNameOnly(Magic, kw_only=True):
            x: NotPositionalOnly[int]

        assert ByPositionToo(1).x == 1
        with pytest.raises(TypeError):
            ByNameOnly(1)

    def test_a_field_that_is_neither_is_no_parameter(self) -> None:
        # The fourth state of the pair: on a class that asks for
        # keywords only, forbidding keywords leaves no way in at all,
        # and the field takes its default like a `NoInit` one.
        class C(Magic, kw_only=True):
            x: NotKw[int] = 7

        assert C().x == 7
        with pytest.raises(TypeError):
            C(7)
        with pytest.raises(TypeError):
            C(x=7)

    def test_no_init_still_takes_its_default(self) -> None:
        class C(Magic):
            x: int = 1
            y: NoInit[int] = 2

        assert (C().x, C().y) == (1, 2)
        with pytest.raises(TypeError):
            C(1, 2)


class TestFieldInit:
    """`init` is what the pair adds up to, and a way to write it."""

    def test_setting_init_reaches_the_signature(self) -> None:
        # The slots are the mechanism; the signature is what a user
        # sees, so the setter is worth checking through one.
        kept, dropped = Field(), Field()
        kept.init = True
        dropped.init = False

        class C(Magic, kw_only=True):
            a: Annotated[int, kept] = 1
            b: Annotated[int, dropped] = 2

        parameters = signature(C.__init__).parameters
        assert list(parameters) == ["self", "a"]
        # `kept` said both ways, which beats the class's kw_only.
        assert parameters["a"].kind is Parameter.POSITIONAL_OR_KEYWORD
        assert C().b == 2

    # (kw, positional, is it a parameter)
    CASES = [
        (True, True, True),
        (True, False, True),
        (False, True, True),
        (False, False, False),
    ]

    @pytest.mark.parametrize("kw,positional,expected", CASES)
    def test_init_reads_the_pair(
        self, kw: bool, positional: bool, expected: bool
    ) -> None:
        assert Field(kw=kw, positional=positional).init is expected

    @pytest.mark.parametrize("value", [True, False])
    @pytest.mark.parametrize(
        "kw,positional", [case[:2] for case in CASES]
    )
    def test_init_writes_the_pair(
        self, kw: bool, positional: bool, value: bool
    ) -> None:
        field = Field(kw=kw, positional=positional)
        field.init = value
        assert (field.kw, field.positional, field.init) == (
            value, value, value
        )

    def test_assignment_replaces_a_half_that_was_spelled_out(self) -> None:
        # Assignment is not a default: whatever the pair held, saying
        # `init` afterwards decides both halves.
        field = Field(kw=False, positional=True)
        field.init = True
        assert (field.kw, field.positional) == (True, True)

    def test_init_false_forbids_both(self) -> None:
        field = Field(init=False)
        assert (field.kw, field.positional, field.init) == (
            False, False, False
        )

    def test_init_true_says_nothing(self) -> None:
        # The pair is left for the class options to resolve, exactly as
        # if `init` had not been given.
        field = Field(init=True)
        assert (field.kw, field.positional) == (MISSING, MISSING)

    def test_a_half_given_on_its_own_wins(self) -> None:
        # In the constructor the two are declarations resolved
        # together, so the half that was spelled out stands. Which of
        # them is written first makes no difference.
        for field in (
            Field(init=False, kw=True), Field(kw=True, init=False)
        ):
            assert (field.kw, field.positional, field.init) == (
                True, False, True
            )

    def test_init_false_keeps_the_field_out_of_the_constructor(self) -> None:
        class C(Magic):
            x: Annotated[int, Field(init=False)] = 3

        assert C().x == 3
        with pytest.raises(TypeError):
            C(3)


# ======================================================================
# Repr / NoRepr
# ======================================================================


class TestRepr:

    def test_no_repr_field(self) -> None:
        class Point(Magic):
            x: int
            y: NoRepr[int]

        p = Point(1, 2)
        assert repr(p) == "Point(x=1)"

    def test_no_repr_class(self) -> None:
        class Point(Magic, repr=False):
            x: int
            y: int

        p = Point(1, 2)
        assert "Point" not in repr(p) or "x=" not in repr(p)

    # -- a field is shown only while it is holding a value -------------

    def test_repr_leaves_out_a_field_with_no_value(self) -> None:
        class Note(Magic):
            text: str
            pinned: NoInit[bool]

        assert repr(Note("hello")) == "Note(text='hello')"

    def test_a_repr_of_nothing_but_unset_fields_still_reads(self) -> None:
        class Blank(Magic):
            here: NoInit[int]
            there: NoInit[int]

        assert repr(Blank()) == "Blank()"

    def test_a_field_given_a_value_joins_the_repr(self) -> None:
        class Note(Magic):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        note.pinned = True
        assert repr(note) == "Note(text='hello', pinned=True)"

    def test_a_field_filled_in_by_post_init_is_shown(self) -> None:
        class Draft(Magic):
            title: str
            slug: NoInit[str]

            def __post_init__(self, arguments: Arguments) -> None:
                self.slug = self.title.lower()

        assert repr(Draft("Ada")) == "Draft(title='Ada', slug='ada')"

    def test_hidden_while_none_and_holding_nothing_are_both_left_out(
        self
    ) -> None:
        class C(Magic):
            x: Annotated[Optional[int], Field(repr=HIDE_IF_NONE)]
            y: NoInit[int]

        c = C(None)
        assert repr(c) == "C()"
        c.x, c.y = 1, 2
        assert repr(c) == "C(x=1, y=2)"

    def test_a_class_whose_fields_all_have_values_is_unchanged(self) -> None:
        class Point(Magic):
            x: int
            y: int = 1

        assert repr(Point(1)) == "Point(x=1, y=1)"


# ======================================================================
# Eq / Order
# ======================================================================


class TestEqOrder:

    def test_no_eq_field(self) -> None:
        class Point(Magic):
            x: int
            y: NoEq[int]

        # y is excluded from eq
        assert Point(1, 2) == Point(1, 99)

    def test_order(self) -> None:
        class Point(Magic, order=True):
            x: int
            y: int

        assert Point(1, 2) < Point(1, 3)
        assert not Point(1, 3) < Point(1, 2)

    def test_order_gives_all_four_comparisons(self) -> None:
        class Point(Magic, order=True):
            x: int
            y: int

        assert Point(1, 2) < Point(1, 3)
        assert Point(1, 2) <= Point(1, 3)
        assert Point(1, 2) <= Point(1, 2)
        assert Point(1, 3) > Point(1, 2)
        assert Point(1, 3) >= Point(1, 2)
        assert Point(1, 3) >= Point(1, 3)
        assert not Point(1, 2) >= Point(1, 3)
        assert not Point(1, 3) <= Point(1, 2)

    def test_order_sorts(self) -> None:
        class Point(Magic, order=True):
            x: int
            y: int

        points = [Point(2, 0), Point(1, 5), Point(1, 2)]
        assert sorted(points) == [Point(1, 2), Point(1, 5), Point(2, 0)]
        assert max(points) == Point(2, 0)

    def test_order_different_class(self) -> None:
        class A(Magic, order=True):
            x: int

        class B(Magic, order=True):
            x: int

        assert A(1).__lt__(B(2)) is NotImplemented
        assert A(1).__le__(B(2)) is NotImplemented
        assert A(1).__gt__(B(2)) is NotImplemented
        assert A(1).__ge__(B(2)) is NotImplemented
        # With both sides answering `NotImplemented`, Python falls back
        # to identity for `==` and refuses the ordering operators.
        assert A(1) != B(1)
        with pytest.raises(TypeError, match="not supported between"):
            operator.le(A(1), B(1))

    def test_no_order_field(self) -> None:
        class Point(Magic, order=True):
            x: int
            y: NoOrder[int]

        # y excluded from ordering
        assert not Point(1, 2) < Point(1, 1)
        assert not Point(1, 1) < Point(1, 2)
        assert Point(1, 2) <= Point(1, 1)
        assert Point(1, 2) >= Point(1, 1)
        assert not Point(1, 2) > Point(1, 1)

    def test_a_renamed_order_binds_no_operator(self) -> None:
        class R(Magic, order="__before__"):
            x: int

        assert R(1).__before__(R(2)) is True
        assert R(2).__before__(R(1)) is False
        assert R.__before__ is R.__magic_lt__
        for compare in (operator.lt, operator.le, operator.gt, operator.ge):
            with pytest.raises(TypeError, match="not supported between"):
                compare(R(1), R(2))

    def test_a_renamed_order_still_writes_the_private_methods(self) -> None:
        class R(Magic, order="__before__"):
            x: int

        assert R(1).__magic_le__(R(1)) is True
        assert R(1).__magic_gt__(R(2)) is False
        assert R(2).__magic_ge__(R(1)) is True

    def test_a_hand_written_lt_stands_alone(self) -> None:
        # A comparison in the class body wins, so the other three are
        # not generated around it: they would compare the fields and
        # disagree with it.
        class P(Magic, order=True):
            x: int

            def __lt__(self, other: tx.Any) -> bool:
                return self.x > other.x

        assert (P(1) < P(2)) is False
        assert (P(2) < P(1)) is True
        for compare in (operator.le, operator.ge):
            with pytest.raises(TypeError, match="not supported between"):
                compare(P(1), P(2))
        assert [name for name in ("__le__", "__gt__", "__ge__")
                if name in P.__dict__] == []
        # `>` is answered by Python itself, by turning it round and
        # asking the hand-written `<`.
        assert (P(1) > P(2)) is True
        # All four are still there to call.
        assert P(1).__magic_lt__(P(2)) is True
        assert P(1).__magic_le__(P(2)) is True
        assert P(1).__magic_gt__(P(2)) is False
        assert P(1).__magic_ge__(P(2)) is False

    def test_a_hand_written_ge_stands_alone(self) -> None:
        class P(Magic, order=True):
            x: int

            def __ge__(self, other: tx.Any) -> bool:
                return "mine"

        assert (P(1) >= P(2)) == "mine"
        for compare in (operator.lt, operator.gt):
            with pytest.raises(TypeError, match="not supported between"):
                compare(P(1), P(2))
        assert [name for name in ("__lt__", "__le__", "__gt__")
                if name in P.__dict__] == []

    def test_a_hand_written_lt_silences_an_ordered_base(self) -> None:
        class Base(Magic, order=True):
            x: int

        class Child(Base):
            y: int

            def __lt__(self, other: tx.Any) -> bool:
                return self.x > other.x

        assert (Child(1, 0) < Child(2, 0)) is False
        for compare in (operator.le, operator.ge):
            with pytest.raises(TypeError, match="not supported between"):
                compare(Child(1, 0), Child(2, 0))

    # -- a field with no value is counted, not skipped -----------------

    def test_two_objects_with_the_same_field_unset_are_equal(self) -> None:
        class Note(Magic):
            text: str
            pinned: NoInit[bool]

        assert Note("hello") == Note("hello")
        assert Note("hello") != Note("goodbye")

    def test_a_field_with_a_value_differs_from_one_without(self) -> None:
        class Note(Magic):
            text: str
            pinned: NoInit[bool]

        filled, empty = Note("hello"), Note("hello")
        filled.pinned = True
        assert filled != empty
        assert empty != filled
        # Both holding the same value, they are equal again.
        empty.pinned = True
        assert filled == empty

    def test_a_field_holding_none_is_not_a_field_holding_nothing(
        self
    ) -> None:
        class Note(Magic):
            pinned: NoInit[Optional[bool]]

        holding_none = Note()
        holding_none.pinned = None
        assert holding_none != Note()

    def test_a_field_left_out_of_eq_need_not_have_a_value(self) -> None:
        class Note(Magic):
            text: str
            pinned: Annotated[bool, NoInit(), NoEq()]

        filled, empty = Note("hello"), Note("hello")
        filled.pinned = True
        assert filled == empty

    def test_ordering_says_which_field_has_no_value(self) -> None:
        class Note(Magic, order=True):
            text: str
            weight: NoInit[int]

        with pytest.raises(AttributeError, match="Note.weight has never"):
            operator.lt(Note("a"), Note("b"))

    def test_every_comparison_refuses_a_field_with_no_value(self) -> None:
        class Note(Magic, order=True):
            weight: NoInit[int]

        for compare in (operator.lt, operator.le, operator.gt, operator.ge):
            with pytest.raises(AttributeError, match="cannot be ordered"):
                compare(Note(), Note())

    def test_ordering_reads_the_other_object_as_well(self) -> None:
        class Note(Magic, order=True):
            weight: NoInit[int]

        filled = Note()
        filled.weight = 1
        with pytest.raises(AttributeError, match="Note.weight has never"):
            operator.lt(filled, Note())

    def test_a_field_out_of_the_ordering_need_not_have_a_value(self) -> None:
        class Note(Magic, order=True):
            text: str
            pinned: Annotated[bool, NoInit(), NoOrder()]

        assert Note("a") < Note("b")
        assert not Note("b") < Note("a")

    def test_order_requires_eq(self) -> None:
        with pytest.raises(ValueError, match="eq must be true"):
            class Bad(Magic):
                x: Annotated[int, Field(order=True, eq=False)]


# ======================================================================
# Hash
# ======================================================================


class TestHash:

    def test_frozen_eq_hashing(self) -> None:
        class Point(Magic, frozen=True, eq=True):
            x: int
            y: int

        p = Point(1, 2)
        assert hash(p) == hash(Point(1, 2))
        assert hash(p) != hash(Point(1, 3))

    def test_unsafe_hash(self) -> None:
        class Point(Magic, unsafe_hash=True):
            x: int
            y: int

        p = Point(1, 2)
        assert hash(p) == hash(Point(1, 2))

    def test_no_hash_field(self) -> None:
        class Point(Magic, frozen=True, eq=True):
            x: int
            y: NoHash[int]

        # NoHash removes field from hash but not from eq
        # hash should be same regardless of y
        # (NoHash sets hash=False; the hash_add function checks f.hash)
        assert hash(Point(1, 2)) == hash(Point(1, 99))

    def test_frozen_in_set(self) -> None:
        class Point(Magic, frozen=True, eq=True):
            x: int
            y: int

        s = {Point(1, 2), Point(1, 2), Point(3, 4)}
        assert len(s) == 2

    # -- a field with no value hashes as one --------------------------

    def test_hash_agrees_with_eq_about_a_field_with_no_value(self) -> None:
        class Note(Magic, frozen=True, eq=True):
            text: str
            pinned: NoInit[bool]

        assert Note("a") == Note("a")
        assert hash(Note("a")) == hash(Note("a"))
        assert len({Note("a"), Note("a")}) == 1

    def test_hash_tells_a_field_with_a_value_from_one_without(self) -> None:
        # Mutable, so that one of the two can be given a value: on a
        # frozen class the field could never be set in the first place.
        class Note(Magic, unsafe_hash=True):
            text: str
            pinned: NoInit[bool]

        empty, filled = Note("a"), Note("a")
        filled.pinned = True
        assert filled != empty
        assert hash(filled) != hash(empty)
        assert len({empty, filled}) == 2


# ======================================================================
# Slots
# ======================================================================


class _SlotsPoint(Magic, frozen=True, slots=True):
    """A frozen, slotted class with a defaulted field of each kind."""

    x: int = 3
    origin: NoInit[int] = 0


class TestSlots:

    def test_slots(self) -> None:
        class Point(Magic, slots=True):
            x: int
            y: int

        p = Point(1, 2)
        assert p.x == 1
        assert not hasattr(p, "__dict__")

    def test_slots_no_arbitrary_attrs(self) -> None:
        class Point(Magic, slots=True):
            x: int
            y: int

        p = Point(1, 2)
        with pytest.raises(AttributeError):
            p.z = 3

    def test_weakref_slot_requires_slots(self) -> None:
        with pytest.raises(
            TypeError, match="weakref_slot is True but slots is False"
        ):
            class Bad(Magic, weakref_slot=True, slots=False):
                x: int

    def test_weakref_slot(self) -> None:
        import weakref

        class Point(Magic, slots=True, weakref_slot=True):
            x: int

        p = Point(1)
        ref = weakref.ref(p)
        assert ref() is p

    def test_slots_already_defined_error(self) -> None:
        with pytest.raises(TypeError, match="already specifies __slots__"):
            class Bad(Magic, slots=True):
                __slots__ = ('x',)
                x: int

    def test_slots_with_default(self) -> None:
        class Point(Magic, slots=True):
            x: int = 3
            y: int = 4

        assert Point.__slots__ == ("x", "y")
        assert (Point().x, Point().y) == (3, 4)
        assert (Point(1).x, Point(1, 2).y) == (1, 2)
        assert not hasattr(Point(), "__dict__")

    def test_slots_with_factory_default(self) -> None:
        class Bag(Magic, slots=True):
            items: Factory[list]

        first, second = Bag(), Bag()
        first.items.append(1)
        assert (first.items, second.items) == ([1], [])
        assert Bag([2]).items == [2]

    def test_slots_with_field_default(self) -> None:
        class Point(Magic, slots=True):
            x: Annotated[int, Field(default=3)]

        assert Point.__slots__ == ("x",)
        assert Point().x == 3
        assert Point(1).x == 1
        assert not hasattr(Point(), "__dict__")

    def test_slots_with_class_var(self) -> None:
        class Point(Magic, slots=True):
            kind: ClassVar[str] = "point"
            x: int = 3

        assert Point.__slots__ == ("x",)
        assert Point.kind == "point"
        assert Point().kind == "point"
        # A class variable is shared: every instance sees a new value.
        Point.kind = "dot"
        assert Point().kind == "dot"

    def test_slots_with_init_var(self) -> None:
        class Point(Magic, slots=True):
            x: int = 3
            scale: InitVar[int] = 10

            def __post_init__(self, arguments: Arguments) -> None:
                self.x = self.x * arguments.scale

        assert Point.__slots__ == ("x",)
        assert Point().x == 30
        assert Point(2, 3).x == 6
        assert not hasattr(Point(), "__dict__")

    def test_slots_no_init_field_is_a_slot(self) -> None:
        class Point(Magic, slots=True):
            x: int = 3
            doubled: NoInit[int] = 0

            def __post_init__(self) -> None:
                self.doubled = self.x * 2

        assert Point.__slots__ == ("x", "doubled")
        assert Point(4).doubled == 8
        assert Point().doubled == 6
        assert not hasattr(Point(), "__dict__")

    def test_slots_frozen_default_survives_pickle_and_copy(self) -> None:
        point = _SlotsPoint(1)
        assert (point.x, point.origin) == (1, 0)
        assert pickle.loads(pickle.dumps(point)) == point
        assert copy.copy(point) == point
        assert copy.deepcopy(point) == point

    def test_slots_without_init_reaches_the_default_by_hand(self) -> None:
        # Without an `__init__` of its own, nothing assigns the default,
        # and under `slots` it is no longer a class attribute either.
        class Point(Magic, slots=True, init=False):
            x: int = 3

        point = Point()
        assert not hasattr(point, "x")
        point.__magic_init__()
        assert point.x == 3

    def test_slots_subclass_with_defaults(self) -> None:
        class Base(Magic, slots=True):
            x: int = 1

        class Derived(Base, slots=True):
            x: int = 2
            y: int = 3

        assert Base.__slots__ == ("x",)
        assert Derived.__slots__ == ("y",)
        derived = Derived()
        assert (derived.x, derived.y) == (2, 3)
        assert not hasattr(derived, "__dict__")
        derived.x = 5
        assert derived.x == 5

    def test_slots_frozen_with_default(self) -> None:
        class Point(Magic, frozen=True, slots=True):
            x: int = 3

        point = Point()
        assert point.x == 3
        assert point == Point(3)
        assert not hasattr(point, "__dict__")
        with pytest.raises(AttributeError):
            point.x = 4

    def test_slots_weakref_with_default(self) -> None:
        import weakref

        class Point(Magic, slots=True, weakref_slot=True):
            x: int = 3

        assert Point.__slots__ == ("x", "__weakref__")
        point = Point()
        assert point.x == 3
        assert weakref.ref(point)() is point


# ======================================================================
# Inheritance
# ======================================================================


class TestInheritance:

    def test_inherit_fields(self) -> None:
        class Base(Magic):
            x: int

        class Derived(Base):
            y: int

        d = Derived(1, 2)
        assert d.x == 1
        assert d.y == 2

    def test_inherit_options(self) -> None:
        class Base(Magic, frozen=True):
            x: int

        class Derived(Base):
            y: int

        d = Derived(1, 2)
        with pytest.raises(AttributeError):
            d.x = 10
        with pytest.raises(AttributeError):
            d.y = 10

    def test_override_field(self) -> None:
        class Base(Magic):
            x: int
            y: int

        class Derived(Base):
            y: str

        d = Derived(1, "hello")
        assert d.y == "hello"

    def test_fields_stored(self) -> None:
        class Point(Magic):
            x: int
            y: int

        fields = getattr(Point, _FIELDS)
        assert "x" in fields
        assert "y" in fields

    def test_options_stored(self) -> None:
        class Point(Magic, frozen=True):
            x: int

        opts = getattr(Point, _OPTIONS)
        assert opts.frozen is True


# ======================================================================
# ConvertTo
# ======================================================================


class TestConvertTo:

    def test_convert_annotation(self) -> None:
        class Point(Magic):
            x: ConvertTo[int]

        p = Point("42")
        assert p.x == 42
        assert isinstance(p.x, int)

    def test_convert_custom_function(self) -> None:
        class Upper(Magic):
            name: ConvertTo[str, str.upper]

        u = Upper("hello")
        assert u.name == "HELLO"

    def test_convert_class_option(self) -> None:
        class Point(Magic, convert=True):
            x: int
            y: float

        p = Point("1", "2.5")
        assert p.x == 1
        assert p.y == 2.5


# ======================================================================
# Validate
# ======================================================================


class TestValidate:

    def test_validate_annotation(self) -> None:
        class Point(Magic):
            x: Validate[int]

        p = Point(42)
        assert p.x == 42

    def test_validate_annotation_fail(self) -> None:
        class Point(Magic):
            x: Validate[int]

        with pytest.raises(ValidationError):
            Point("not int")

    def test_validate_class_option(self) -> None:
        class Point(Magic, validate=True):
            x: int
            y: float

        Point(1, 2.5)
        with pytest.raises(ValidationError):
            Point("a", 2.5)


# ======================================================================
# convert_defaults / validate_defaults
# ======================================================================


def _double(value: int) -> int:
    return value * 2


def _positive(value: int) -> int:
    if value <= 0:
        raise ValueError("must be positive")
    return value


class TestDefaultsAreConvertedAndValidated:
    """Whether a value that came from a default goes through the field's
    converter and validator, or is taken as it was written."""

    def test_a_default_is_converted(self) -> None:
        class Config(Magic, convert=True):
            port: int = "8080"

        assert Config().port == 8080

    def test_a_default_is_validated(self) -> None:
        class Config(Magic, validate=True):
            port: int = "8080"

        with pytest.raises(ValidationError):
            Config()

    def test_a_class_that_says_nothing_carries_its_default_plainly(
        self
    ) -> None:
        # Nothing is wrapped and no signature is stood in for unless a
        # class asks for one of the two settings.
        class Config(Magic, convert=True):
            port: int = "8080"

        assert Config.__init__.__defaults__ == ("8080",)
        assert not hasattr(Config.__init__, "__signature__")

    def test_convert_defaults_false_leaves_a_plain_default(self) -> None:
        class Config(Magic, convert=True, convert_defaults=False):
            port: int = "8080"

        assert Config().port == "8080"
        assert Config("9000").port == 9000

    def test_convert_defaults_false_leaves_a_factory_default(self) -> None:
        class Config(Magic, convert=True, convert_defaults=False):
            port: Annotated[int, Field(factory=lambda: "8080")]

        assert Config().port == "8080"
        assert Config("9000").port == 9000

    def test_validate_defaults_false_leaves_a_plain_default(self) -> None:
        class Config(Magic, validate=True, validate_defaults=False):
            port: int = "8080"

        assert Config().port == "8080"
        assert Config(9000).port == 9000
        with pytest.raises(ValidationError):
            Config("9000")

    def test_validate_defaults_false_leaves_a_factory_default(self) -> None:
        class Config(Magic, validate=True, validate_defaults=False):
            port: Annotated[int, Field(factory=lambda: "8080")]

        assert Config().port == "8080"
        with pytest.raises(ValidationError):
            Config("9000")

    def test_the_same_value_is_taken_two_ways(self) -> None:
        # The one case a guess about the value could not get right: what
        # the class defaults to is exactly what the caller passes.
        class Reading(Magic, validate_defaults=False):
            level: Annotated[int, Field(validator=_positive)] = -1

        assert Reading().level == -1
        with pytest.raises(ValueError):
            Reading(-1)

    def test_only_the_skipped_step_is_skipped(self) -> None:
        class Reading(Magic, validate_defaults=False):
            level: Annotated[
                int, Field(converter=_double, validator=_positive)
            ] = -1

        # Converted, as the class did not turn that off, and then not
        # handed to the validator that would have refused it.
        assert Reading().level == -2
        assert Reading(3).level == 6

    @pytest.mark.parametrize("convert_defaults", [True, False])
    @pytest.mark.parametrize("validate_defaults", [True, False])
    def test_a_passed_value_always_goes_through_both(
        self, convert_defaults: bool, validate_defaults: bool
    ) -> None:
        class Reading(
            Magic,
            convert_defaults=convert_defaults,
            validate_defaults=validate_defaults,
        ):
            level: Annotated[
                int, Field(converter=_double, validator=_positive)
            ] = 1

        assert Reading(3).level == 6
        with pytest.raises(ValueError):
            Reading(-1)
        assert Reading().level == (2 if convert_defaults else 1)

    def test_assignment_afterwards_is_always_converted_and_validated(
        self
    ) -> None:
        class Reading(
            Magic, convert_defaults=False, validate_defaults=False
        ):
            level: Annotated[
                int, Field(converter=_double, validator=_positive)
            ] = -1

        reading = Reading()
        assert reading.level == -1
        reading.level = 3
        assert reading.level == 6
        with pytest.raises(ValueError):
            reading.level = -1

    def test_a_field_with_no_parameter_follows_the_setting(self) -> None:
        class Lenient(Magic, convert_defaults=False):
            origin: NoInit[Annotated[int, Field(converter=_double)]] = 3

        class Strict(Magic):
            origin: NoInit[Annotated[int, Field(converter=_double)]] = 3

        assert (Lenient().origin, Strict().origin) == (3, 6)

    def test_a_field_with_no_parameter_and_a_factory(self) -> None:
        class Lenient(Magic, convert_defaults=False):
            origin: NoInit[
                Annotated[int, Field(converter=_double, factory=lambda: 3)]
            ]

        class Strict(Magic):
            origin: NoInit[
                Annotated[int, Field(converter=_double, factory=lambda: 3)]
            ]

        assert (Lenient().origin, Strict().origin) == (3, 6)

    def test_an_init_var_default_follows_the_setting(self) -> None:
        class Scaled(Magic, convert_defaults=False):
            x: int = 0
            scale: InitVar[Annotated[int, Field(converter=_double)]] = 3

            def __post_init__(self, arguments: Arguments) -> None:
                self.x = arguments.scale

        assert (Scaled().x, Scaled(0, 5).x) == (3, 10)

    def test_a_hook_is_handed_the_default_itself(self) -> None:
        seen = []

        class Reading(Magic, convert_defaults=False):
            level: Annotated[int, Field(converter=_double)] = 3

            def __pre_init__(self, arguments: Arguments) -> None:
                seen.append(arguments.level)

        Reading()
        Reading(5)
        assert seen == [3, 5]

    def test_a_class_that_refers_to_itself(self) -> None:
        # `parent: Optional[Node]` needs nothing turned off; this is for
        # the class whose defaults are already what its author meant.
        class Node(Magic, convert=True, convert_defaults=False):
            name: str
            parent: "Node" = None

        root = Node("root")
        assert root.parent is None
        assert Node("leaf", root).parent is root

    def test_both_settings_are_inherited(self) -> None:
        class Base(
            Magic,
            convert=True,
            convert_defaults=False,
            validate_defaults=False,
        ):
            port: int = "8080"

        class Child(Base):
            host: str = 1234

        # The setting reaches the field the subclass declares itself as
        # well as the one it inherits, and neither stops a caller's
        # value being converted.
        child = Child()
        assert (child.port, child.host) == ("8080", 1234)
        assert Child("9000", "here").port == 9000

    def test_a_subclass_can_ask_for_its_defaults_back(self) -> None:
        class Base(Magic, convert=True, convert_defaults=False):
            port: int = "8080"

        class Strict(Base, convert_defaults=True):
            pass

        assert (Base().port, Strict().port) == ("8080", 8080)

    def test_the_signature_shows_the_default_it_was_written_with(
        self
    ) -> None:
        class Strict(Magic, convert=True):
            port: int = "8080"
            name: KwOnly[str] = 1234

        class Lenient(Magic, convert=True, convert_defaults=False):
            port: int = "8080"
            name: KwOnly[str] = 1234

        assert str(signature(Lenient)) == str(signature(Strict))
        parameters = signature(Lenient).parameters
        assert parameters["port"].default == "8080"
        assert parameters["name"].default == 1234

    def test_a_marked_default_reads_as_the_value(self) -> None:
        class Config(Magic, convert=True, convert_defaults=False):
            port: int = "8080"

        assert repr(Config.__init__.__defaults__) == "('8080',)"

    def test_they_are_not_settings_a_field_takes(self) -> None:
        # A field resolves nothing from them: they decide what the
        # generated `__init__` does with a default, not which converter
        # or validator the field ends up with. So `override=` has
        # nothing to resolve again.
        assert "convert_defaults" not in _fields._OVERRIDABLE
        assert "validate_defaults" not in _fields._OVERRIDABLE


# ======================================================================
# Var / InitVar / ClassVar
# ======================================================================


class TestVarFields:

    def test_init_var(self) -> None:

        class WithInitVar(Magic):
            x: int
            scale: InitVar[int]

            def __post_init__(self, arguments: Arguments) -> None:
                self.x = self.x * arguments.scale

        w = WithInitVar(5, 10)
        assert w.x == 50
        assert not hasattr(w, "scale") or getattr(w, "scale", None) is None

    def test_no_init_field_gets_its_default(self) -> None:
        class Point(Magic):
            x: int = 3
            origin: NoInit[int] = 0

        point = Point()
        assert point.origin == 0
        # The default is stored on the instance, so it can be replaced
        # on one instance without touching the others.
        point.origin = 5
        assert (point.origin, Point().origin) == (5, 0)

    def test_no_init_factory_is_called_per_instance(self) -> None:
        class Bag(Magic):
            items: NoInit[Factory[list]]

        first, second = Bag(), Bag()
        first.items.append(1)
        assert (first.items, second.items) == ([1], [])

    def test_no_init_field_is_converted_and_validated(self) -> None:
        class Point(Magic, convert=True, validate=True):
            x: int = 1
            origin: NoInit[int] = "0"

        assert Point().origin == 0


# ======================================================================
# match_args
# ======================================================================


class TestMatchArgs:

    def test_match_args(self) -> None:
        class Point(Magic, match_args=True):
            x: int
            y: int

        assert Point.__match_args__ == ("x", "y")

    def test_match_args_excludes_kw_only(self) -> None:
        class Point(Magic, match_args=True):
            x: int
            y: KwOnly[int]

        assert Point.__match_args__ == ("x",)

    def test_turning_it_off_does_not_leave_the_base_tuple(self) -> None:
        class Base(Magic, match_args=True):
            a: int

        class Child(Base, match_args=False):
            b: int

        # Without this, `case Child(x)` would bind `x` to `a` -- the
        # base's field list, answering for a class that asked for no
        # pattern matching at all.
        assert Child.__match_args__ == ()

    def test_a_subclass_that_keeps_it_lists_its_own_fields(self) -> None:
        class Base(Magic, match_args=True):
            a: int

        class Child(Base):
            b: int

        assert Child.__match_args__ == ("a", "b")

    def test_the_tuple_is_always_available_privately(self) -> None:
        class Child(Magic, match_args=False):
            a: int

        assert Child.__magic_match_args__ == ("a",)

    def test_a_hand_written_tuple_is_left_alone(self) -> None:
        class Base(Magic, match_args=True):
            a: int

        class Child(Base, match_args=False):
            b: int
            __match_args__ = ("b",)

        assert Child.__match_args__ == ("b",)

    def test_writing_the_private_name_is_refused(self) -> None:
        with pytest.raises(TypeError) as caught:
            class Point(Magic, match_args=True):
                x: int
                __magic_match_args__ = ("x",)

        message = str(caught.value)
        assert "__magic_match_args__" in message
        assert "__match_args__" in message
        # A tuple is not something the reader can call.
        assert "call" not in message


# ======================================================================
# Field (direct)
# ======================================================================


class TestField:

    def test_field_from_hint_simple(self) -> None:
        f = Field.from_hint("x", int)
        assert f.name == "x"
        assert f.type is int

    def test_field_from_hint_with_default(self) -> None:
        f = Field.from_hint("x", int, 42)
        assert f.default == 42

    def test_field_from_hint_annotated(self) -> None:
        f = Field.from_hint("x", Annotated[int, Field(frozen=True)])
        assert f.frozen is True

    def test_field_repr(self) -> None:
        f = Field(kw=True, repr=False)
        r = repr(f)
        assert "kw=True" in r
        assert "repr=False" in r

    def test_field_compare_alias(self) -> None:
        f = Field(compare=True)
        assert f.eq is True
        assert f.order is True

    def test_field_no_annotation_error(self) -> None:
        with pytest.raises(
            TypeError, match="is a field but has no type annotation"
        ):
            class Bad(Magic):
                x = Field()


# ======================================================================
# Mapping
# ======================================================================


class TestMapping:

    def test_mapping_getitem(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        assert p["x"] == 1
        assert p["y"] == 2

    def test_mapping_getitem_keyerror(self) -> None:
        class Point(Magic, mapping=True):
            x: int

        p = Point(1)
        with pytest.raises(KeyError):
            p["z"]

    def test_mapping_setitem(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        p["x"] = 10
        assert p.x == 10
        assert p["x"] == 10

    def test_mapping_setitem_keyerror(self) -> None:
        class Point(Magic, mapping=True):
            x: int

        p = Point(1)
        with pytest.raises(KeyError):
            p["z"] = 99

    def test_mapping_delitem(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        del p["x"]
        assert not hasattr(p, "x")

    def test_mapping_delitem_keyerror(self) -> None:
        class Point(Magic, mapping=True):
            x: int

        p = Point(1)
        with pytest.raises(KeyError):
            del p["z"]

    def test_mapping_iter(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        assert list(p) == ["x", "y"]

    def test_mapping_len(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        assert len(p) == 2

    def test_mapping_is_mutable_mapping(self) -> None:
        from collections.abc import MutableMapping

        class Point(Magic, mapping=True):
            x: int

        p = Point(1)
        assert isinstance(p, MutableMapping)

    def test_frozen_mapping_is_immutable_mapping(self) -> None:
        from collections.abc import Mapping, MutableMapping

        class Point(Magic, mapping=True, frozen=True):
            x: int
            y: int

        p = Point(1, 2)
        assert isinstance(p, Mapping)
        assert not isinstance(p, MutableMapping)

    def test_mapping_dict_conversion(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: int

        p = Point(1, 2)
        assert dict(p) == {"x": 1, "y": 2}

    def test_a_subclass_cannot_stop_being_dict_like(self) -> None:
        class Base(Magic, mapping=True):
            a: int

        with pytest.raises(TypeError, match="does not take them away"):
            class Child(Base, mapping=False):
                b: int

    def test_the_ban_names_the_class_that_asked_for_it(self) -> None:
        class Base(Magic, mapping=True):
            a: int

        class Middle(Base):
            b: int

        with pytest.raises(TypeError) as caught:
            class Child(Middle, mapping=False):
                c: int

        # `Middle` is dict-like only because it inherited the option,
        # so pointing at it would send the reader somewhere that raises
        # this same error again.
        assert "Base" in str(caught.value)
        assert "Middle" not in str(caught.value)

    def test_the_ban_does_not_quote_a_value_back(self) -> None:
        class Base(Magic, mapping=True):
            a: int

        with pytest.raises(TypeError) as caught:
            class Child(Base, mapping=None):
                b: int

        # Any falsy value turns the option off, so the message must not
        # name one the reader did not write.
        assert "mapping=False" not in str(caught.value)

    def test_a_subclass_that_keeps_it_reports_its_own_fields(self) -> None:
        class Base(Magic, mapping=True):
            a: int

        class Child(Base):
            b: int

        assert dict(Child(1, 2)) == {"a": 1, "b": 2}

    def test_mapping_false_is_fine_under_a_real_mapping_base(self) -> None:
        # The ban is about the dict-like methods a Magic base generates,
        # not about what the class is: a class that inherits a real
        # Mapping and asks for no dict-like methods of its own is fine,
        # and is a Mapping all the same.
        from collections.abc import Mapping

        class RealMap(Mapping):
            pass

        class Child(Magic, RealMap, mapping=False):
            b: int

        assert issubclass(Child, Mapping)

    def test_mapping_false_is_fine_without_a_dict_like_base(self) -> None:
        class Base(Magic):
            a: int

        class Child(Base, mapping=False):
            b: int

        from collections.abc import Mapping

        assert not isinstance(Child(1, 2), Mapping)

    def test_mapping_not_key_field(self) -> None:
        class Point(Magic, mapping=True):
            x: int
            y: NotKey[int]

        p = Point(1, 2)
        assert list(p) == ["x"]
        assert p["x"] == 1
        with pytest.raises(KeyError):
            p["y"]

    def test_mapping_key_field_override(self) -> None:
        class Point(Magic):
            x: Key[int]
            y: int

        # mapping=False by default, but Key annotation sets field.key=True
        # The mapping interface is only generated if the class option is set,
        # so Key on its own doesn't add mapping methods.
        # Let's test with mapping=True and Key/NotKey mix.
        class Point2(Magic, mapping=True):
            x: Key[int]
            y: NotKey[int]

        p = Point2(1, 2)
        assert dict(p) == {"x": 1}

    def test_mapping_inherited(self) -> None:
        class Base(Magic, mapping=True):
            x: int

        class Derived(Base):
            y: int

        d = Derived(1, 2)
        assert dict(d) == {"x": 1, "y": 2}

    def test_mapping_skips_pseudo_fields(self) -> None:
        class Row(Magic, mapping=True):
            name: str
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0

        row = Row("ada")
        assert dict(row) == {"name": "ada"}
        assert list(row) == ["name"]
        assert len(row) == 1
        # Still a perfectly ordinary class attribute, just not a key.
        assert row.unit == "m"
        for key in ("unit", "by"):
            with pytest.raises(KeyError):
                row[key]
            with pytest.raises(KeyError):
                row[key] = 1
            with pytest.raises(KeyError):
                del row[key]

    def test_mapping_skips_an_init_var_with_no_default(self) -> None:
        class Shift(Magic, mapping=True):
            x: int
            by: InitVar[int]

        shift = Shift(1, 2)
        assert dict(shift) == {"x": 1}
        assert list(shift) == ["x"]
        assert len(shift) == 1

    def test_mapping_of_nothing_but_pseudo_fields(self) -> None:
        class Meta(Magic, mapping=True):
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0

        meta = Meta()
        assert dict(meta) == {}
        assert list(meta) == []
        assert len(meta) == 0
        with pytest.raises(KeyError):
            meta["unit"]

    # -- a key is there only while its field has a value ---------------

    def test_mapping_skips_a_field_with_no_value(self) -> None:
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert dict(note) == {"text": "hello"}
        assert list(note) == ["text"]
        assert len(note) == 1

    def test_a_field_filled_in_by_post_init_is_there_from_the_start(
        self
    ) -> None:
        class Draft(Magic, mapping=True):
            title: str
            slug: NoInit[str]

            def __post_init__(self, arguments: Arguments) -> None:
                self.slug = self.title.lower()

        draft = Draft("Ada")
        assert dict(draft) == {"title": "Ada", "slug": "ada"}
        assert len(draft) == 2

    def test_a_key_arrives_when_its_field_is_given_a_value(self) -> None:
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert "pinned" not in note
        assert len(note) == 1

        note["pinned"] = True

        assert "pinned" in note
        assert note["pinned"] is True
        assert len(note) == 2
        assert dict(note) == {"text": "hello", "pinned": True}
        assert list(note) == ["text", "pinned"]

    def test_two_instances_of_one_class_can_be_of_different_lengths(
        self
    ) -> None:
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        filled = Note("a")
        filled["pinned"] = False
        assert len(filled) == 2
        assert len(Note("b")) == 1

    def test_a_mapping_of_nothing_but_unset_fields_is_empty(self) -> None:
        class Blank(Magic, mapping=True):
            here: NoInit[int]
            there: NoInit[int]

        blank = Blank()
        assert dict(blank) == {}
        assert list(blank) == []
        assert len(blank) == 0
        assert not blank

    def test_getitem_says_which_field_has_no_value(self) -> None:
        class Note(Magic, mapping=True):
            pinned: NoInit[bool]

        with pytest.raises(KeyError, match="Note.pinned has no value"):
            Note()["pinned"]

    def test_the_dict_like_helpers_agree_about_a_field_with_no_value(
        self
    ) -> None:
        # `in`, `get`, `keys`, `values` and `items` come from
        # `Mapping`, and each is built on `__getitem__` and `__iter__`.
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert "pinned" not in note
        assert note.get("pinned") is None
        assert note.get("pinned", "no") == "no"
        assert list(note.keys()) == ["text"]
        assert list(note.values()) == ["hello"]
        assert list(note.items()) == [("text", "hello")]

        note["pinned"] = True

        assert "pinned" in note
        assert note.get("pinned") is True
        assert list(note.keys()) == ["text", "pinned"]
        assert list(note.values()) == ["hello", True]
        assert list(note.items()) == [("text", "hello"), ("pinned", True)]

    def test_the_mutable_helpers_work_over_a_field_with_no_value(
        self
    ) -> None:
        # `pop`, `setdefault` and `clear` come from `MutableMapping`,
        # and each of them expects a key that is not there to answer
        # with a `KeyError`.
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert note.pop("pinned", "none") == "none"
        assert note.setdefault("pinned", True) is True
        assert note.pop("pinned") is True
        assert dict(note) == {"text": "hello"}

        note.clear()
        assert dict(note) == {}

    def test_delitem_takes_the_key_away_with_the_value(self) -> None:
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        note["pinned"] = True

        del note["pinned"]

        assert "pinned" not in note
        assert len(note) == 1
        assert list(note) == ["text"]
        assert dict(note) == {"text": "hello"}

        note["pinned"] = False
        assert dict(note) == {"text": "hello", "pinned": False}

    def test_delitem_of_a_field_with_no_value_says_so(self) -> None:
        class Note(Magic, mapping=True):
            pinned: NoInit[bool]

        with pytest.raises(KeyError, match="Note.pinned has no value"):
            del Note()["pinned"]

    def test_delitem_is_refused_when_a_default_stands_behind_the_key(
        self
    ) -> None:
        class Note(Magic, mapping=True):
            pinned: bool = False

        note = Note(True)
        with pytest.raises(TypeError, match="Note.pinned has a default"):
            del note["pinned"]
        # Refused, so nothing moved.
        assert dict(note) == {"pinned": True}
        assert len(note) == 1

    def test_delitem_empties_a_defaulted_field_under_slots(self) -> None:
        # With `slots` the default is written into the instance rather
        # than left on the class, so there is nothing behind it.
        class Note(Magic, mapping=True, slots=True):
            pinned: bool = False

        note = Note(True)
        del note["pinned"]
        assert dict(note) == {}
        assert len(note) == 0

    def test_a_frozen_mapping_refuses_to_fill_a_field_in(self) -> None:
        class Note(Magic, mapping=True, frozen=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert dict(note) == {"text": "hello"}
        with pytest.raises(AttributeError, match="frozen field 'pinned'"):
            note["pinned"] = True
        with pytest.raises(AttributeError, match="frozen field 'text'"):
            del note["text"]
        assert dict(note) == {"text": "hello"}

    def test_a_dict_is_what_compares_equal_to_a_dict(self) -> None:
        # An instance compares as an instance of its class, whether or
        # not it is dict-like, so the plain dict to compare with a
        # plain dict is the one `dict()` builds.
        class Note(Magic, mapping=True):
            text: str
            pinned: NoInit[bool]

        note = Note("hello")
        assert dict(note) == {"text": "hello"}
        assert note != {"text": "hello"}

        note["pinned"] = True
        same = Note("hello")
        same["pinned"] = True
        assert note == same

    def test_mapping_default_off(self) -> None:
        class Point(Magic):
            x: int
            y: int

        p = Point(1, 2)
        # No mapping interface by default
        assert not hasattr(p, "__getitem__")


# ======================================================================
# Integration: combined features
# ======================================================================


class TestIntegration:

    def test_frozen_eq_hashable_as_dict_key(self) -> None:
        class Point(Magic, frozen=True, eq=True):
            x: int
            y: int

        d = {Point(1, 2): "a", Point(3, 4): "b"}
        assert d[Point(1, 2)] == "a"

    def test_convert_and_validate(self) -> None:
        class Config(Magic):
            x: Annotated[int, ConvertTo(), Validate()]

        c = Config("42")
        assert c.x == 42

    def test_inheritance_with_defaults(self) -> None:
        class Base(Magic):
            x: int

        class Derived(Base):
            x: int = 10
            y: int = 20

        d = Derived()
        assert d.x == 10
        assert d.y == 20

    def test_default_factory_class_option(self) -> None:
        class Container(Magic, factory=True):
            items: list

        c = Container()
        assert c.items == []

    def test_deeply_nested_struct(self) -> None:
        class A(Magic):
            a: int

        class B(A):
            b: int

        class C(B):
            c: int

        obj = C(1, 2, 3)
        assert obj.a == 1
        assert obj.b == 2
        assert obj.c == 3

    def test_eq_identity_shortcircuit(self) -> None:
        class Point(Magic):
            x: int

        p = Point(1)
        assert p == p  # same object -> True immediately


# ======================================================================
# Pickling
# ======================================================================


# Pickle needs classes resolvable at module scope, so these live here
# rather than inside the test methods.
class PicklePoint(Magic):
    x: int
    y: int


class PickleFrozen(Magic, frozen=True):
    a: int


class PickleThawed(PickleFrozen, frozen=False):
    b: int


class PickleFrozenChild(PickleFrozen, frozen=True):
    b: int


class PicklePlainChild(PicklePoint):
    z: int


class PickleGrandchild(PickleThawed):
    c: int


class PickleOwnState(PickleFrozen, frozen=False):
    b: int

    def __getstate__(self) -> dict:
        return {"a": self.a, "b": self.b, "by_hand": True}

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)


class PickleOnlyGet(PickleFrozen, frozen=False):
    b: int

    def __getstate__(self) -> dict:
        return {"a": self.a, "b": self.b}


class PickleOnlySet(PickleFrozen, frozen=False):
    b: int

    def __setstate__(self, state: dict) -> None:
        self.__dict__.update(state)


class PickleSlots(Magic, frozen=True, slots=True):
    a: int


class PickleSlotsChild(PickleSlots, frozen=False, slots=True):
    b: int


class PickleDictAndSlots(PickleFrozen, frozen=False, slots=True):
    b: int


class PicklePseudoField(Magic, frozen=True):
    a: int
    b: InitVar[int]

    def __post_init__(self, arguments: Arguments) -> None:
        object.__setattr__(self, "b", arguments.b * 2)


def _round_trips(obj: tx.Any) -> tx.List[tx.Any]:
    """The object back from each of the three ways of copying it."""
    return [
        pickle.loads(pickle.dumps(obj)),
        copy.copy(obj),
        copy.deepcopy(obj),
    ]


class _PickleUnsetSlot(Magic, frozen=True, slots=True, init=False):
    """A slotted class that assigns nothing, so its slot starts empty."""

    x: int = 3


class TestPickle:

    def test_pickle_round_trip(self) -> None:
        restored = pickle.loads(pickle.dumps(PicklePoint(1, 2)))
        assert restored == PicklePoint(1, 2)
        assert restored.x == 1 and restored.y == 2

    def test_pickle_frozen(self) -> None:
        restored = pickle.loads(pickle.dumps(PickleFrozen(5)))
        assert restored == PickleFrozen(5)

    def test_pickle_unfrozen_subclass(self) -> None:
        restored = pickle.loads(pickle.dumps(PickleThawed(1, 2)))
        assert (restored.a, restored.b) == (1, 2)

    def test_copy_unfrozen_subclass(self) -> None:
        copied = copy.copy(PickleThawed(1, 2))
        assert (copied.a, copied.b) == (1, 2)

    def test_deepcopy_unfrozen_subclass(self) -> None:
        original = PickleThawed(1, [2])
        copied = copy.deepcopy(original)
        assert (copied.a, copied.b) == (1, [2])
        assert copied.b is not original.b

    def test_pickle_frozen_subclass(self) -> None:
        restored = pickle.loads(pickle.dumps(PickleFrozenChild(1, 2)))
        assert (restored.a, restored.b) == (1, 2)

    def test_pickle_grandchild(self) -> None:
        # Two steps below the frozen class the pair started with.
        restored = pickle.loads(pickle.dumps(PickleGrandchild(1, 2, 3)))
        assert (restored.a, restored.b, restored.c) == (1, 2, 3)

    def test_plain_subclass_keeps_default_pickling(self) -> None:
        # Nothing frozen anywhere, so there is nothing to write.
        assert "__getstate__" not in PicklePlainChild.__dict__
        assert "__setstate__" not in PicklePlainChild.__dict__
        restored = pickle.loads(pickle.dumps(PicklePlainChild(1, 2, 3)))
        assert restored == PicklePlainChild(1, 2, 3)

    def test_own_state_methods_are_kept(self) -> None:
        restored = pickle.loads(pickle.dumps(PickleOwnState(1, 2)))
        assert (restored.a, restored.b) == (1, 2)
        assert restored.by_hand is True
        assert "__getstate__" not in PickleOwnState.__dict__[_GENERATED]
        assert "__setstate__" not in PickleOwnState.__dict__[_GENERATED]

    def test_only_getstate_written_leaves_both_alone(self) -> None:
        # The two have to agree, so half a pair of your own means the
        # whole pair is yours.
        assert PickleOnlyGet(1, 2).__getstate__() == {"a": 1, "b": 2}
        assert "__setstate__" not in PickleOnlyGet.__dict__
        assert "__getstate__" not in PickleOnlyGet.__dict__[_GENERATED]
        assert "__setstate__" not in PickleOnlyGet.__dict__[_GENERATED]

    def test_only_setstate_written_leaves_both_alone(self) -> None:
        obj = PickleOnlySet(1, 2)
        obj.__setstate__({"a": 3, "b": 4})
        assert (obj.a, obj.b) == (3, 4)
        assert "__getstate__" not in PickleOnlySet.__dict__
        assert "__getstate__" not in PickleOnlySet.__dict__[_GENERATED]
        assert "__setstate__" not in PickleOnlySet.__dict__[_GENERATED]

    def test_extra_attribute_survives_plain(self) -> None:
        obj = PicklePoint(1, 2)
        obj.extra = 99
        for restored in _round_trips(obj):
            assert restored.extra == 99

    def test_extra_attribute_survives_frozen(self) -> None:
        obj = PickleFrozen(1)
        object.__setattr__(obj, "extra", 99)
        for restored in _round_trips(obj):
            assert (restored.a, restored.extra) == (1, 99)

    def test_extra_attribute_survives_unfrozen_subclass(self) -> None:
        obj = PickleThawed(1, 2)
        obj.extra = 99
        for restored in _round_trips(obj):
            assert (restored.a, restored.b, restored.extra) == (1, 2, 99)

    def test_slots_survive(self) -> None:
        # A slotted class has no attribute dictionary, so everything it
        # holds is in its slots.
        for restored in _round_trips(PickleSlots(1)):
            assert restored.a == 1

    def test_slots_survive_subclass(self) -> None:
        for restored in _round_trips(PickleSlotsChild(1, 2)):
            assert (restored.a, restored.b) == (1, 2)

    def test_dict_and_slots_both_survive(self) -> None:
        # This one has both: `a` comes from a base with an attribute
        # dictionary, `b` is a slot.
        obj = PickleDictAndSlots(1, 2)
        obj.extra = 99
        for restored in _round_trips(obj):
            assert (restored.a, restored.b, restored.extra) == (1, 2, 99)

    def test_stored_pseudo_field_survives(self) -> None:
        # `b` is not a field of its own, but it is on the object.
        for restored in _round_trips(PicklePseudoField(1, 2)):
            assert (restored.a, restored.b) == (1, 4)

    def test_an_empty_slot_stays_empty(self) -> None:
        # With no `__init__` of its own, nothing assigns `x`, so the
        # slot holds no value at all -- and the copy must not invent
        # one.
        obj = copy.deepcopy(_PickleUnsetSlot())
        assert not hasattr(obj, "x")
        obj.__magic_init__()
        assert copy.deepcopy(obj).x == 3


# ======================================================================
# Constants: REQUIRED / SHOW_ATTR / HIDE_IF_NONE
# ======================================================================


class TestConstants:

    def test_required_repr(self) -> None:
        assert repr(REQUIRED) == "<REQUIRED>"

    def test_required_bool(self) -> None:
        assert bool(REQUIRED) is True

    def test_required_singleton(self) -> None:
        from bagof.magic._constants import _RequiredType
        assert _RequiredType() is REQUIRED

    def test_show_attr_call_false(self) -> None:
        assert SHOW_ATTR(False)("anything") is False

    def test_show_attr_call_hide_if_none(self) -> None:
        show = SHOW_ATTR("k", hide_if_none=True)
        assert show(None) is False
        assert show(1) is True

    def test_show_attr_str(self) -> None:
        assert str(SHOW_ATTR("k")) == "k"

    def test_show_attr_repr_false(self) -> None:
        assert repr(SHOW_ATTR(False)) == "False"

    def test_show_attr_repr_true_hide(self) -> None:
        assert repr(SHOW_ATTR(True, hide_if_none=True)) == "<if not None>"

    def test_show_attr_repr_key_hide(self) -> None:
        assert repr(SHOW_ATTR("k", hide_if_none=True)) == "'k' <if not None>"

    def test_show_attr_repr_key(self) -> None:
        assert repr(SHOW_ATTR("k")) == "'k'"

    def test_hide_if_none_init(self) -> None:
        h = HideIfNoneCls("k")
        assert h.hide_if_none is True
        assert h.key == "k"


# ======================================================================
# utils: SlotsBase / rebuild_cls / slots
# ======================================================================


class TestUtils:

    def test_update_cell_none(self) -> None:
        assert _update_func_cell_for__class__(None, int, str) is False

    def test_update_cell_not_oldcls(self) -> None:
        class A:
            def method(self) -> type:
                return __class__  # noqa: F821

        assert A().method() is A
        # Cell points at A, but we claim oldcls is B -> no update.
        assert _update_func_cell_for__class__(A.method, str, int) is False

    def test_rebuild_cls_with_property(self) -> None:
        class Src:
            @property
            def prop(self) -> type:
                return __class__  # noqa: F821

        new = rebuild_cls(Src)
        # The property closure is rebound to the new class (covers `break`).
        assert new().prop is new

    def test_slots_with_kwslots(self) -> None:
        @slots("x", y=None)
        class C:
            pass

        assert set(C.__slots__) == {"x", "y"}

    def test_slotsbase_getattr_unknown(self) -> None:
        f = Field()
        with pytest.raises(AttributeError):
            _ = f.totally_unknown_attribute

    def test_slotsbase_getattr_unset_slot(self) -> None:
        # An unset (deleted) but declared slot resolves to MISSING via
        # __getattr__ rather than raising.
        f = Field(name="x")
        del f.name
        assert f.name is MISSING

    def test_slotsbase_copy(self) -> None:
        f = Field(name="x", doc="hi")
        c = f.copy()
        assert c is not f
        assert c.name == "x"
        assert c.doc == "hi"

    def test_slotsbase_deepcopy(self) -> None:
        f = Field(name="x", metadata={"a": [1]})
        c = f.deepcopy()
        assert c is not f
        assert c.metadata == {"a": [1]}
        assert c.metadata is not f.metadata


# ======================================================================
# _fields.py: Field internals
# ======================================================================


class TestFieldInternals:

    def test_field_positional_bool_arg(self) -> None:
        assert Field(True).var is False
        assert Field(False).var is True

    def test_field_class_getitem(self) -> None:
        ann = Field[int]
        t, f = tx.get_args(ann)
        assert t is int
        assert isinstance(f, Field)
        assert f.var is False

    def test_public_name_alias_false(self) -> None:
        assert Field(name="_x", alias=False).public_name == "_x"

    def test_public_name_alias_set(self) -> None:
        assert Field(name="_x", alias="renamed").public_name == "renamed"

    def test_public_name_strip_underscore(self) -> None:
        assert Field(name="_x").public_name == "x"

    def test_public_key_none(self) -> None:
        assert Field(name="x", key=False).public_key is None

    def test_public_key_show_attr_str(self) -> None:
        f = Field(name="x", key=SHOW_ATTR("thekey"))
        assert f.public_key == "thekey"

    def test_public_key_str(self) -> None:
        assert Field(name="x", key="strkey").public_key == "strkey"

    def test_from_hint_typing_classvar(self) -> None:
        class C(Magic):
            x: int
            c: TypingClassVar[int] = 9

        assert C(1).x == 1
        assert C.c == 9
        assert getattr(C, _FIELDS)["c"].var is True

    def test_from_hint_annotated_typing_classvar(self) -> None:
        class C(Magic):
            x: int
            c: Annotated[TypingClassVar[int], "meta"] = 3

        assert C(1).x == 1
        assert C.c == 3
        assert getattr(C, _FIELDS)["c"].var is True

    def test_from_hint_doc_annotation(self) -> None:
        f = Field.from_hint("x", Annotated[int, tx.Doc("the docs")])
        assert f.doc == "the docs"

    def test_kw_only_and_positional_only_error(self) -> None:
        with pytest.raises(ValueError, match="Cannot set both"):
            class Bad(Magic, kw_only=True, positional_only=True):
                x: int

    def test_factory_true_optional(self) -> None:
        # factory=True resolves through bagof-factories, which defaults an
        # Optional to None (rather than the wrapped type's empty value).
        class A(Magic, factory=True):
            x: Optional[list]

        assert A().x is None

    def test_factory_true_resolves_from_bagof_factories(self) -> None:
        class A(Magic, factory=True):
            items: list
            mapping: dict
            count: int

        a = A()
        assert a.items == [] and a.mapping == {} and a.count == 0
        # each instance gets a fresh default
        a.items.append(1)
        assert A().items == []

    def test_annotated_field_missing_required_call(self) -> None:
        with pytest.raises(TypeError, match="Missing required argument"):
            Default()

    def test_annotated_field_missing_required_getitem(self) -> None:
        with pytest.raises(TypeError, match="Missing required argument"):
            Default[int, REQUIRED]

    def test_doc_annotation_init(self) -> None:
        d = Doc("hello docs")
        assert d.doc == "hello docs"
        assert d.documentation == "hello docs"


# ======================================================================
# _add_fields (inheritance ordering helper)
# ======================================================================


class TestAddFields:

    def test_replace_no_reverse_inherit_missing(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a")  # overrides 'a', doc MISSING
        assert new.doc is MISSING
        m._add_fields(fields, [new], replace=True, reverse=False)
        # the new field wins, but takes the doc it does not set itself
        assert fields["a"].doc == "olddoc"
        # ... on a copy: `new` still belongs to whoever passed it in
        assert fields["a"] is not new
        assert new.doc is MISSING

    def test_replace_no_reverse_inherit_none(self) -> None:
        # a doc that was never given a value has already been filled in
        # with None by the time fields are merged: still unset.
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a", doc=None)
        m._add_fields(fields, [new], replace=True, reverse=False)
        assert fields["a"].doc == "olddoc"

    def test_replace_no_reverse_keeps_own_doc(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a", doc="newdoc")
        m._add_fields(fields, [new], replace=True, reverse=False)
        assert fields["a"].doc == "newdoc"

    def test_replace_no_inherit(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a", doc="newdoc")
        m._add_fields(fields, [new], replace=True, inherit=())
        assert fields["a"] is not new
        assert fields["a"].doc == "newdoc"

    def test_replace_reverse(self) -> None:
        fields = {
            "a": Field(name="a", doc="da"),
            "b": Field(name="b", doc="db"),
        }
        new = Field(name="a")  # overrides 'a', doc MISSING
        assert new.doc is MISSING
        m._add_fields(fields, [new], replace=True, reverse=True)
        # new fields go first; the overriding 'a' inherits the old doc
        assert list(fields) == ["a", "b"]
        assert fields["a"] is not new
        assert fields["a"].doc == "da"

    def test_replace_reverse_keeps_own_doc(self) -> None:
        fields = {"a": Field(name="a", doc="da")}
        new = Field(name="a", doc="newdoc")
        m._add_fields(fields, [new], replace=True, reverse=True)
        assert fields["a"].doc == "newdoc"

    def test_not_replace_no_reverse(self) -> None:
        fields = {"a": Field(name="a")}  # doc MISSING
        new_a = Field(name="a", doc="fromnew")
        new_b = Field(name="b", doc="db")
        m._add_fields(fields, [new_a, new_b], replace=False, reverse=False)
        # existing 'a' preserved, 'b' appended; 'a' inherits new doc
        assert list(fields) == ["a", "b"]
        assert fields["a"].doc == "fromnew"
        assert fields["b"] is not new_b

    def test_not_replace_no_reverse_keeps_own_doc(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new_a = Field(name="a", doc="fromnew")
        m._add_fields(fields, [new_a], replace=False, reverse=False)
        assert fields["a"].doc == "olddoc"

    def test_not_replace_reverse(self) -> None:
        fields = {"a": Field(name="a")}  # doc MISSING
        new_a = Field(name="a", doc="fromnew")
        new_b = Field(name="b", doc="db")
        m._add_fields(fields, [new_a, new_b], replace=False, reverse=True)
        assert list(fields) == ["a", "b"]
        assert fields["a"].doc == "fromnew"
        assert fields["b"] is not new_b

    def test_not_replace_reverse_keeps_own_doc(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new_a = Field(name="a", doc="fromnew")
        new_b = Field(name="b", doc="db")
        m._add_fields(fields, [new_a, new_b], replace=False, reverse=True)
        # new names go first, but a name already there keeps its field
        assert list(fields) == ["a", "b"]
        assert fields["a"].doc == "olddoc"

    def test_reverse_option_inheritance(self) -> None:
        class Base(Magic, reverse=True):
            x: int

        class Derived(Base):
            y: int

        # reverse=True places derived fields before base fields.
        assert list(getattr(Derived, _FIELDS)) == ["y", "x"]


# ======================================================================
# Fields across a hierarchy
# ======================================================================


class TestFieldInheritance:

    def test_subclass_does_not_share_fields_with_base(self) -> None:
        class Base(Magic):
            x: int = 1

        class Derived(Base):
            y: int = 2

        assert _api.fields(Base)[0] is not _api.fields(Derived)[0]

    def test_diamond_leaves_bases_alone(self) -> None:
        class A(Magic):
            x: Annotated[int, Doc("A doc")] = 1

        class B(Magic):
            x: Annotated[int, Doc("B doc")] = 2

        class C(A, B):
            pass

        # Defining C must not rewrite A or B.
        assert _api.fields(A)[0].doc == "A doc"
        assert _api.fields(B)[0].doc == "B doc"
        # C follows its MRO: A comes first, so A's doc wins.
        assert _api.fields(C)[0].doc == "A doc"

    def test_child_keeps_its_own_doc(self) -> None:
        class Base(Magic):
            x: Annotated[int, Doc("base doc")] = 1

        class Derived(Base):
            x: Annotated[int, Doc("child doc")] = 2

        assert _api.fields(Derived)[0].doc == "child doc"
        assert _api.fields(Base)[0].doc == "base doc"

    def test_child_inherits_the_base_doc(self) -> None:
        class Base(Magic):
            x: Annotated[int, Doc("base doc")] = 1

        class Derived(Base):
            x: int = 2

        assert _api.fields(Derived)[0].doc == "base doc"

    def test_subclass_does_not_share_fields_with_base_reverse(self) -> None:
        class Base(Magic, reverse=True):
            x: int = 1

        class Derived(Base):
            y: int = 2

        assert _api.fields(Base)[0] is not _api.fields(Derived)[-1]

    def test_diamond_leaves_bases_alone_reverse(self) -> None:
        class A(Magic, reverse=True):
            x: Annotated[int, Doc("A doc")] = 1

        class B(Magic, reverse=True):
            x: Annotated[int, Doc("B doc")] = 2

        class C(A, B):
            pass

        assert _api.fields(A)[0].doc == "A doc"
        assert _api.fields(B)[0].doc == "B doc"
        assert _api.fields(C)[0].doc == "A doc"

    def test_child_keeps_its_own_doc_reverse(self) -> None:
        class Base(Magic, reverse=True):
            x: Annotated[int, Doc("base doc")] = 1

        class Derived(Base):
            x: Annotated[int, Doc("child doc")] = 2

        assert _api.fields(Derived)[0].doc == "child doc"
        assert _api.fields(Base)[0].doc == "base doc"

    def test_child_inherits_the_base_doc_reverse(self) -> None:
        class Base(Magic, reverse=True):
            x: Annotated[int, Doc("base doc")] = 1

        class Derived(Base):
            x: int = 2

        assert _api.fields(Derived)[0].doc == "base doc"


# ======================================================================
# override
# ======================================================================


class TestOverride:
    """A subclass deciding an inherited field's settings again."""

    def test_the_worked_example(self) -> None:
        class Record(Magic, frozen=True):
            x: int
            y: Frozen[int]

        class Draft(Record, frozen=False, override=True):
            z: int

        d = Draft(1, 2, 3)
        # x never asked to be frozen, so Draft's answer applies.
        d.x = 9
        assert d.x == 9
        # y asked for it in writing, so it keeps it.
        with pytest.raises(AttributeError, match="Cannot set frozen"):
            d.y = 9
        d.z = 9
        assert d.z == 9

    def test_saying_nothing_keeps_the_base_answer(self) -> None:
        class Record(Magic, frozen=True):
            x: int

        class Draft(Record, frozen=False):
            z: int

        d = Draft(1, 2)
        d.z = 9
        with pytest.raises(AttributeError, match="Cannot set frozen"):
            d.x = 9

    def test_the_base_is_left_alone(self) -> None:
        class Record(Magic, frozen=True):
            x: int

        class Draft(Record, frozen=False, override=True):
            pass

        Draft(1).x = 9
        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Record(1).x = 9

    # ------------------------------------------------------------------
    # Every setting a field takes from its class
    # ------------------------------------------------------------------

    def test_frozen_is_decided_again(self) -> None:
        class Base(Magic):
            x: int = 1

        class Sub(Base, frozen=True, override=True):
            pass

        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Sub().x = 2

    def test_kw_only_is_decided_again(self) -> None:
        class Base(Magic):
            x: int = 1

        class Sub(Base, kw_only=True, override=True):
            pass

        assert Sub(x=2).x == 2
        with pytest.raises(TypeError):
            Sub(2)

    def test_positional_only_is_decided_again(self) -> None:
        class Base(Magic):
            x: int = 1

        class Sub(Base, positional_only=True, override=True):
            pass

        assert Sub(2).x == 2
        with pytest.raises(TypeError):
            Sub(x=2)

    def test_convert_is_decided_again(self) -> None:
        class Base(Magic):
            x: int = 1

        class Kept(Base):
            pass

        class Sub(Base, convert=True, override=True):
            pass

        assert Kept("42").x == "42"
        assert Sub("42").x == 42

    def test_validate_is_decided_again(self) -> None:
        class Base(Magic):
            x: int = 1

        class Kept(Base):
            pass

        class Sub(Base, validate=True, override=True):
            pass

        assert Kept("nope").x == "nope"
        with pytest.raises(ValidationError):
            Sub("nope")

    def test_a_rebuilt_converter_is_told_where_to_look(self) -> None:
        # A type written as a name is looked up when the field is first
        # used, and the class asking for the conversion says where and
        # what to do when it is not there.
        class Base(Magic):
            parent: "Nowhere" = None  # noqa: F821

        class Sub(
            Base, convert=True, override=True, unresolved_hints="raise"
        ):
            pass

        with pytest.raises(NameError, match="Sub.parent"):
            Sub("anything")

    def test_factory_is_decided_again(self) -> None:
        class Base(Magic):
            x: list

        class Sub(Base, factory=True, override=True):
            pass

        assert Sub().x == []
        # Still a factory: one list per instance, not one shared list.
        assert Sub().x is not Sub().x

    def test_repr_is_decided_again(self) -> None:
        class Base(Magic):
            x: Optional[int] = None

        class Kept(Base):
            pass

        class Sub(Base, repr=HIDE_IF_NONE, override=True):
            pass

        assert repr(Kept()) == "Kept(x=None)"
        assert repr(Sub()) == "Sub()"
        assert repr(Sub(3)) == "Sub(x=3)"

    def test_a_subclass_still_cannot_stop_being_dict_like(self) -> None:
        class Base(Magic, mapping=True):
            x: int = 1

        with pytest.raises(TypeError, match="does not take them away"):
            class Sub(Base, mapping=False, override=True):
                pass

    # ------------------------------------------------------------------
    # What it is allowed to say
    # ------------------------------------------------------------------

    def test_one_setting_by_name(self) -> None:
        class Base(Magic):
            x: int = 1

        class Sub(Base, frozen=True, kw_only=True, override="frozen"):
            pass

        # frozen was asked for by name; kw_only was not, so `x` stays
        # positional.
        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Sub(2).x = 3

    def test_several_settings_by_name(self) -> None:
        class Base(Magic):
            x: int = 1

        class Sub(
            Base, frozen=True, kw_only=True, override=("frozen", "kw_only")
        ):
            pass

        with pytest.raises(TypeError):
            Sub(2)
        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Sub(x=2).x = 3

    @pytest.mark.parametrize("setting", ["eq", "order", "hash", "mapping"])
    def test_a_setting_a_field_never_takes_from_its_class(
        self, setting: str
    ) -> None:
        # These four are about the class as a whole -- whether a method
        # is generated, whether there is a dict-like view. A field
        # answers them from itself, so there is nothing to decide again
        # and asking says so rather than doing nothing.
        with pytest.raises(ValueError, match="not one of the settings"):
            class Sub(Magic, override=setting):
                x: int = 1

    def test_something_that_names_nothing(self) -> None:
        with pytest.raises(ValueError, match="neither a setting name"):
            class Sub(Magic, override=3):
                x: int = 1

    def test_off_by_name(self) -> None:
        class Base(Magic, frozen=True):
            x: int = 1

        class Sub(Base, frozen=False, override=()):
            pass

        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Sub().x = 2

    # ------------------------------------------------------------------
    # What survives it
    # ------------------------------------------------------------------

    def test_an_annotation_survives_in_both_directions(self) -> None:
        class Base(Magic, frozen=True):
            loose: NotFrozen[int] = 1

        class Sub(Base, frozen=True, override=True):
            pass

        sub = Sub()
        sub.loose = 2
        assert sub.loose == 2

    def test_an_annotated_keyword_stays_keyword_only(self) -> None:
        class Base(Magic, kw_only=True):
            x: KwOnly[int] = 1

        class Sub(Base, kw_only=False, override=True):
            pass

        with pytest.raises(TypeError):
            Sub(2)
        assert Sub(x=2).x == 2

    def test_a_promoted_mutable_default_survives(self) -> None:
        # `x: list = []` becomes a factory when the base is built; that
        # is the field's own from then on, whatever the subclass says
        # about factories.
        class Base(Magic):
            x: list = []

        class Sub(Base, override=True):
            pass

        assert Sub().x == []
        assert Sub().x is not Sub().x

    def test_a_doc_still_reaches_the_field_that_replaces_it(self) -> None:
        class Base(Magic, frozen=True):
            x: Annotated[int, Doc("base doc")] = 1

        class Sub(Base, frozen=False, override=True):
            x: int = 2

        assert _api.fields(Sub)[0].doc == "base doc"

    def test_a_redeclared_field_is_built_fresh(self) -> None:
        # A field the subclass declares again is resolved against the
        # subclass's settings like any other, with no `override` needed.
        class Base(Magic, frozen=True):
            x: int = 1

        class Sub(Base, frozen=False):
            x: int = 2

        sub = Sub()
        sub.x = 3
        assert sub.x == 3

    # ------------------------------------------------------------------
    # Inheriting the setting itself
    # ------------------------------------------------------------------

    def test_a_base_can_turn_it_on_for_a_family(self) -> None:
        class Base(Magic, frozen=True, override=True):
            x: int = 1

        class Sub(Base, frozen=False):
            pass

        Sub().x = 2

    def test_a_middle_class_turns_it_on_for_what_follows(self) -> None:
        class Top(Magic, frozen=True):
            x: int = 1

        class Middle(Top, frozen=False, override=True):
            y: int = 2

        class Bottom(Middle):
            z: int = 3

        with pytest.raises(AttributeError, match="Cannot set frozen"):
            Top().x = 9
        middle = Middle()
        middle.x = 9
        bottom = Bottom()
        bottom.x = 9
        bottom.y = 9
        bottom.z = 9
        assert (bottom.x, bottom.y, bottom.z) == (9, 9, 9)


class TestDeclaredValues:
    """The record of what a field asked for, which `override` reads."""

    def test_it_is_taken_before_anything_is_filled_in(self) -> None:
        field = Field.from_hint("x", Frozen[int])
        assert field.declared is MISSING
        field.setdefault(Options.make_default())
        assert field.declared["frozen"] is True
        assert field.declared["converter"] is MISSING

    def test_it_is_taken_once(self) -> None:
        field = Field.from_hint("x", int)
        field.setdefault(Options(**dict(Options._DEFAULTS, frozen=True)))
        assert field.frozen is True
        field.setdefault(Options.make_default())
        # Already answered, so a second pass changes nothing.
        assert field.frozen is True
        assert field.declared["frozen"] is MISSING

    def test_a_copy_shares_nothing_with_its_original(self) -> None:
        class Base(Magic, frozen=True):
            x: int = 1

        class Sub(Base, frozen=False, override=True):
            pass

        base_field = _api.fields(Base)[0]
        sub_field = _api.fields(Sub)[0]
        assert sub_field.declared is not base_field.declared
        assert base_field.frozen is True
        assert sub_field.frozen is False

    def test_a_field_that_declared_nothing_copies_cleanly(self) -> None:
        field = Field(name="x")
        assert field.copy().declared is MISSING

    def test_it_stays_out_of_the_repr(self) -> None:
        field = Field.from_hint("x", int)
        field.setdefault(Options.make_default())
        assert "declared" not in repr(field)
        assert "name='x'" in repr(field)

    def test_recording_a_value_on_an_unresolved_field(self) -> None:
        field = Field(name="x")
        field._redeclare(factory=list)
        assert field.factory is list
        assert field.declared is MISSING


class TestOverridableSettings:
    """Which settings a field takes from its class, checked not assumed."""

    def test_they_are_exactly_the_ones_a_field_reads(self) -> None:
        # Twice a setting has been listed here that a field never takes
        # from its class, and re-resolving it would have done nothing at
        # all. `mapping` was the second: it stopped reaching a field the
        # day `key` began defaulting to `not var`. So the list is read
        # off the code that does the resolving rather than kept by hand.
        read = re.findall(
            r"options\.(\w+)", inspect.getsource(Field.setdefault)
        )
        assert set(_fields._OVERRIDABLE) == set(read)

    def test_they_are_class_settings(self) -> None:
        assert set(_fields._OVERRIDABLE) <= set(Options._DEFAULTS)

    def test_they_name_field_attributes(self) -> None:
        slots = set(Field._slots())
        for setting, attrs in _fields._OVERRIDABLE.items():
            assert set(attrs) <= slots, setting
        assert set(_fields._RESOLVED_ATTRS) <= slots

# ======================================================================
# _FuncBuilder
# ======================================================================


class TestFuncBuilder:

    def test_decorator_and_no_return_type(self) -> None:
        fb = m._FuncBuilder({"deco": lambda f: f})
        fb.add_fn(
            name="foo", args=["self"], body=["return 1"], decorator="@deco"
        )
        ns = {"__qualname__": "C"}
        fb.insert_fns("C", ns)
        assert "foo" in ns

    def test_unconditional_add(self) -> None:
        fb = m._FuncBuilder({})
        fb.add_fn(
            name="foo",
            args=["self"],
            body=["return 2"],
            unconditional_add=True,
        )
        ns = {"__qualname__": "C", "foo": "already here"}
        fb.insert_fns("C", ns)
        assert callable(ns["foo"])

    def test_overwrite_error_with_message(self) -> None:
        fb = m._FuncBuilder({})
        fb.add_fn(
            name="foo",
            args=["self"],
            body=["return 3"],
            overwrite_error="extra hint",
        )
        ns = {"__qualname__": "C", "foo": "already here"}
        with pytest.raises(TypeError, match="Cannot overwrite.*extra hint"):
            fb.insert_fns("C", ns)

    def test_overwrite_error_true(self) -> None:
        fb = m._FuncBuilder({})
        fb.add_fn(
            name="foo",
            args=["self"],
            body=["return 4"],
            overwrite_error=True,
        )
        ns = {"__qualname__": "C", "foo": "already here"}
        with pytest.raises(TypeError, match="Cannot overwrite attribute foo"):
            fb.insert_fns("C", ns)

    def test_empty_builder(self) -> None:
        fb = m._FuncBuilder({})
        ns = {"__qualname__": "C"}
        fb.insert_fns("C", ns)
        assert ns == {"__qualname__": "C"}


# ======================================================================
# Metaclass feature coverage
# ======================================================================


class TestMetaclassFeatures:

    def test_custom_module_globals(self) -> None:
        # A class whose __module__ is not importable falls back to empty
        # globals but still functions.
        cls = m.MetaMagic(
            "Custom",
            (),
            {
                "__module__": "no.such.module.exists",
                "__qualname__": "Custom",
                "__annotations__": {"a": int},
            },
        )
        assert cls(3).a == 3

    def test_dunder_annotation_ignored(self) -> None:
        class C(Magic):
            __private__: int = 5
            x: int

        # The dunder annotation is not treated as a field.
        assert "__private__" not in getattr(C, _FIELDS)
        assert C(1).x == 1

    def test_class_attr_field_no_default(self) -> None:
        class C(Magic):
            x: int = Field(repr=False)
            y: int

        p = C(1, 2)
        assert repr(p) == "C(y=2)"

    def test_class_attr_field_with_default(self) -> None:
        class C(Magic):
            x: int = Field(default=5)

        assert C().x == 5
        assert C.x == 5

    def test_pre_init(self) -> None:
        seen = []

        class C(Magic):
            x: int
            s: InitVar[int]

            def __pre_init__(self, arguments: Arguments) -> None:
                seen.append(arguments.s)

            def __post_init__(self, arguments: Arguments) -> None:
                self.x += arguments.s

        c = C(1, 3)
        assert c.x == 4
        assert seen == [3]

    def test_hash_disabled(self) -> None:
        class C(Magic, frozen=True, eq=True, hash=False):
            x: int

        assert C.__hash__ is None

    def test_unsafe_hash_explicit_hash_error(self) -> None:
        with pytest.raises(TypeError, match="Cannot overwrite attribute"):
            class Bad(Magic, unsafe_hash=True):
                x: int
                __hash__ = object.__hash__

    def test_repr_hide_if_none_field(self) -> None:
        class C(Magic):
            x: Annotated[Optional[int], Field(repr=HIDE_IF_NONE)]
            y: int

        assert repr(C(None, 2)) == "C(y=2)"
        assert repr(C(5, 2)) == "C(x=5, y=2)"

    def test_repr_hide_if_none_var_field(self) -> None:
        class C(Magic):
            x: int
            c: Annotated[int, ClassVar(), Field(repr=HIDE_IF_NONE)] = 0

        assert repr(C(5)) == "C(x=5)"

    def test_setattr_converter(self) -> None:
        class C(Magic):
            x: ConvertTo[int]

        c = C("1")
        c.x = "42"
        assert c.x == 42
        assert isinstance(c.x, int)

    def test_setattr_validator(self) -> None:
        class C(Magic):
            x: Validate[int]

        c = C(3)
        c.x = 7
        assert c.x == 7
        with pytest.raises(ValidationError):
            c.x = "bad"

    def test_frozen_delete_non_field(self) -> None:
        class C(Magic, frozen=True):
            x: int

        c = C(1)
        with pytest.raises(
            AttributeError, match="Cannot delete attribute"
        ):
            del c.missing

    def test_frozen_set_non_field(self) -> None:
        class C(Magic, frozen=True):
            x: int

        c = C(1)
        with pytest.raises(AttributeError, match="Cannot set attribute"):
            c.missing = 1

    def test_field_named_self(self) -> None:
        class C(Magic):
            self: int
            x: int

        c = C(1, 2)
        assert c.self == 1
        assert c.x == 2

    def test_positional_only_field(self) -> None:
        # A single positional-only field (via NotKw).
        class C(Magic):
            x: NotKw[int]

        assert C(5).x == 5
        with pytest.raises(TypeError):
            C(x=5)

    def test_positional_only_initvar(self) -> None:
        class C(Magic):
            s: Annotated[
                int, Field(var=True, init=True, positional=True, kw=False)
            ]

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "doubled", arguments.s * 2)

        assert C(4).doubled == 8

    def test_kw_only_initvar(self) -> None:
        class C(Magic):
            x: int
            s: Annotated[
                int, Field(var=True, init=True, positional=False, kw=True)
            ]

            def __post_init__(self, arguments: Arguments) -> None:
                self.x += arguments.s

        assert C(1, s=5).x == 6

    def test_param_without_default_after_default(self) -> None:
        with pytest.raises(
            SyntaxError, match="parameter without a default follows"
        ):
            class Bad(Magic):
                x: int = 0
                y: int

    def test_fields_function(self) -> None:
        class C(Magic):
            x: int
            c: ClassVar[int] = 1

        result = _api.fields(C)
        names = [f.name for f in result]
        assert names == ["x"]


# ======================================================================
# Mapping: HIDE_IF_NONE key
# ======================================================================


class TestMappingHideKey:

    def test_key_hide_if_none(self) -> None:
        class C(Magic, mapping=True):
            x: Annotated[Optional[int], Field(key=HIDE_IF_NONE)]
            y: int

        assert dict(C(None, 2)) == {"y": 2}
        assert dict(C(5, 2)) == {"x": 5, "y": 2}

    def test_getitem_hidden_key(self) -> None:
        class C(Magic, mapping=True):
            x: Annotated[Optional[int], Field(key=HIDE_IF_NONE)]

        with pytest.raises(KeyError):
            C(None)["x"]
        assert C(5)["x"] == 5


# ======================================================================
# Documentation generation
# ======================================================================


class TestDocGeneration:

    def test_doc_class_with_unions(self) -> None:
        class C(Magic, doc=True):
            """Header."""

            a: Optional[int] = None
            b: Union[int, str] = 0

        doc = C.__doc__
        assert "Attributes" in doc
        assert "a : int, optional" in doc
        assert "b : int | str" in doc

    def test_doc_field_docstring(self) -> None:
        class C(Magic, doc=True):
            x: Annotated[int, Doc("the x value")]

        assert "the x value" in C.__doc__

    def test_doc_class_attributes_section(self) -> None:
        class C(Magic, doc=True):
            x: int
            c: Annotated[int, ClassVar(), Doc("a classvar")] = 5

        doc = C.__doc__
        assert "Class Attributes" in doc
        assert "a classvar" in doc

    def test_doc_a_pseudo_field_with_no_parameter_is_not_a_class_attribute(
        self,
    ) -> None:
        # `NotKw` on a class that takes keywords only leaves the field
        # with no parameter, which does not turn an `InitVar` into a
        # class attribute -- nothing is stored on the class for it.
        class C(Magic, kw_only=True):
            x: InitVar[NotKw[int]] = 0
            y: int = 1

        doc = C.__doc__
        assert "Class Attributes" not in doc
        assert "x :" not in doc
        assert "y : int, default=1" in doc

    def test_doc_a_pseudo_field_that_is_never_an_argument_is_one(self) -> None:
        # A pseudo-field that forbids both ways of passing it is what
        # `ClassVar` is, however it is spelled.
        class C(Magic):
            x: InitVar[NoInit[int]] = 0

        assert "Class Attributes" in C.__doc__
        assert "x : int, default=0" in C.__doc__

    def test_make_doc_elem_annotated_type(self) -> None:
        # `field.type` being a bare Annotated is only reachable by building
        # a Field directly (the public API always strips Annotated).
        field = Field(name="x", type=Annotated[int, "meta"], doc="hi")
        doc = m._make_doc_elem(field)
        assert doc.startswith("x : int")
        assert "hi" in doc


class TestGeneratedDocstring:
    """The constructor's documentation is arbitrary text."""

    def test_doc_holding_triple_quotes(self) -> None:
        ends_a_docstring = 'ends a docstring: """ and then some'

        class C(Magic):
            x: Annotated[int, Doc(ends_a_docstring)]

        assert ends_a_docstring in C.__magic_init__.__doc__
        assert C(1).x == 1

    def test_default_whose_repr_holds_triple_quotes(self) -> None:
        class C(Magic):
            x: str = 'holds """ inside'

        assert 'holds """ inside' in C.__magic_init__.__doc__
        assert C().x == 'holds """ inside'

    def test_default_whose_repr_holds_a_backslash(self) -> None:
        class C(Magic):
            x: str = "a\\b\nc"

        # What the documentation shows is the `repr()`, so the escapes are
        # spelled out rather than acted on.
        assert r"default='a\\b\nc'" in C.__magic_init__.__doc__
        assert C().x == "a\\b\nc"

    def test_an_ordinary_docstring_is_unchanged(self) -> None:
        class C(Magic):
            x: int
            y: Annotated[str, Doc("why not")] = "hi"
            z: Optional[float] = None

        assert C.__magic_init__.__doc__ == (
            "\n"
            "        Parameters\n"
            "        ----------\n"
            "        x : int\n"
            "        y : str, default='hi'\n"
            "            why not\n"
            "        z : float, optional\n"
            "        "
        )


# ======================================================================
# Slots inheritance corner cases
# ======================================================================


class SlotStrMixin:
    __slots__ = "foo"


class SlotPlainMixin:
    pass


class TestSlotsCorners:

    def test_slots_plain_base(self) -> None:
        class C(SlotPlainMixin, Magic, slots=True):
            x: int

        assert C.__slots__ == ("x",)

    def test_slots_str_base(self) -> None:
        class C(SlotStrMixin, Magic, slots=True):
            x: int

        assert "x" in C.__slots__

    def test_slots_iterator_base_error(self) -> None:
        class IterMixin:
            __slots__ = iter(["foo"])

        with pytest.raises(TypeError, match="cannot be determined"):
            class C(IterMixin, Magic, slots=True):
                x: int

    def test_slots_inherited_field(self) -> None:
        class Base(Magic, slots=True):
            x: int

        class Derived(Base, slots=True):
            x: int
            y: int

        assert Derived.__slots__ == ("y",)

    def test_slots_with_doc(self) -> None:
        class C(Magic, slots=True):
            x: Annotated[int, Doc("the x")]

        assert C.__slots__ == {"x": "the x"}


# ======================================================================
# Positional-only / factory features (fixed bugs)
# ======================================================================


class TestPositionalOnly:

    def test_positional_only_class_option(self) -> None:
        class P(Magic, positional_only=True):
            x: int
            y: int

        p = P(1, 2)
        assert (p.x, p.y) == (1, 2)
        # both fields are positional-only: keywords are rejected
        with pytest.raises(TypeError):
            P(x=1, y=2)

    def test_positional_only_field_marker(self) -> None:
        class R(Magic):
            x: PositionalOnly[int]
            y: int

        # x is positional-only, y is normal -- and each keeps its own value
        r = R(1, 2)
        assert (r.x, r.y) == (1, 2)
        r2 = R(1, y=3)
        assert (r2.x, r2.y) == (1, 3)

    def test_positional_only_multiple_fields_keep_values(self) -> None:
        # Regression: positional-only fields used to be assigned from the
        # wrong argument in a multi-field class.
        class R(Magic):
            a: NotKw[int]
            b: NotKw[int]
            c: int

        r = R(1, 2, c=3)
        assert (r.a, r.b, r.c) == (1, 2, 3)


class TestHashOption:
    """The three states of the `hash` option, and per-field `hash=None`."""

    def test_hash_true_generates_a_hash(self) -> None:
        # Regression: the dispatch table only read `unsafe_hash`, so
        # `hash=True` landed on the "eq and not frozen" cell and set
        # `__hash__ = None` -- the opposite of what was asked.
        class H(Magic, hash=True):
            x: int

        assert H.__hash__ is not None
        assert hash(H(1)) == hash(H(1))
        assert hash(H(1)) != hash(H(2))

    def test_hash_false_disables_it(self) -> None:
        class H(Magic, hash=False):
            x: int

        assert H.__hash__ is None

    def test_hash_none_leaves_the_decision_to_eq_and_frozen(self) -> None:
        class Mutable(Magic):
            x: int

        class Immutable(Magic, frozen=True):
            x: int

        assert Mutable.__hash__ is None
        assert hash(Immutable(1)) == hash(Immutable(1))

    def test_field_hash_none_falls_back_to_eq(self) -> None:
        # Regression: `_hash_add` read `f.compare`, which is a constructor
        # alias rather than a slot, so this raised AttributeError.
        class H(Magic, unsafe_hash=True):
            x: Annotated[int, Field(hash=None)]
            y: Annotated[int, Field(hash=None, eq=False)]

        # `y` is out of `__eq__`, so it is out of `__hash__` too.
        assert hash(H(1, 2)) == hash(H(1, 99))
        assert hash(H(1, 2)) != hash(H(3, 2))


class TestMatchArgsRename:

    def test_match_args_accepts_a_name(self) -> None:
        # Regression: the name was computed and then discarded, so the
        # tuple was always written to `__match_args__`.
        class M(Magic, match_args="__my_args__"):
            x: int
            y: int

        assert M.__my_args__ == ("x", "y")
        assert "__match_args__" not in M.__dict__

    def test_match_args_true_uses_the_dunder(self) -> None:
        class M(Magic, match_args=True):
            x: int

        assert M.__match_args__ == ("x",)


class TestFunctionalAPI:

    def test_class_without_a_module_entry(self) -> None:
        # Regression: `namespace["__module__"]` raised KeyError when the
        # class was built through the metaclass directly.
        C = m.MetaMagic("C", (Magic,), {"__annotations__": {"x": int}})
        assert C(1).x == 1

class TestOptimisedInterpreter:
    """`python -OO` strips docstrings; nothing may assume they are there."""

    def test_import_and_class_creation_under_OO(self) -> None:
        # stdlib
        import subprocess
        import sys

        # Regression: the module ran `MetaMagic.__doc__.format(...)` at
        # import time, which is an AttributeError once `-OO` has replaced
        # every docstring with None.
        source = (
            "from bagof.magic import Magic\n"
            "class C(Magic):\n"
            "    x: int = 1\n"
            "assert C(2).x == 2\n"
            "assert C.__doc__ is None\n"
            "print('ok')\n"
        )
        result = subprocess.run(
            [sys.executable, "-OO", "-c", source],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "ok"

class TestUserDefinedAssignment:
    """A hand-written `__setattr__` / `__delattr__` must survive."""

    def test_user_setattr_is_kept(self) -> None:
        # Regression: the guard tested for "__setattr___" (three trailing
        # underscores), so it never matched and the user's method was
        # always overwritten.
        class S(Magic):
            x: int

            def __setattr__(self, name: str, value: int) -> None:
                object.__setattr__(self, name, value * 2)

        s = S(1)
        # `__init__` assigns through `object.__setattr__`, so it is not
        # doubled at construction...
        assert s.x == 1
        # ...but a later assignment goes through the user's method.
        s.x = 3
        assert s.x == 6

    def test_user_delattr_is_kept(self) -> None:
        class D(Magic):
            x: int = 0

            def __delattr__(self, name: str) -> None:
                raise RuntimeError("no deleting")

        with pytest.raises(RuntimeError, match="no deleting"):
            del D(1).x

    def test_frozen_still_applies_without_a_user_method(self) -> None:
        class F(Magic, frozen=True):
            x: int

        with pytest.raises(AttributeError, match="frozen"):
            F(1).x = 2

class TestPublicName:
    """A field whose parameter name differs from its own name."""

    def test_underscored_field(self) -> None:
        # Regression: the generated body referenced the field name while
        # the signature declared the public name, so the class raised
        # `NameError: name '_x' is not defined` at definition time.
        class P(Magic):
            _x: int

        assert P(1)._x == 1
        assert P(x=2)._x == 2
        assert repr(P(3)) == "P(x=3)"

    def test_explicit_alias(self) -> None:
        class A(Magic):
            x: Annotated[int, Field(alias="ex")]

        assert A(ex=1).x == 1
        assert A(1).x == 1
        assert repr(A(1)) == "A(ex=1)"

    def test_alias_false_keeps_the_private_name(self) -> None:
        class A(Magic):
            _x: Annotated[int, Field(alias=False)]

        assert A(_x=1)._x == 1

    def test_underscored_field_with_a_converter(self) -> None:
        class P(Magic, convert=True):
            _x: int

        assert P("5")._x == 5

    def test_underscored_pseudo_field_reaches_post_init(self) -> None:
        class C(Magic):
            x: int
            _seed: Annotated[int, Field(var=True, init=True)] = 0

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "x", self.x + arguments.seed)

        assert C(1, seed=7).x == 8

    def test_two_fields_mapping_to_one_parameter_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="known as 'y'"):
            class Bad(Magic):
                _y: int
                y: int

    def test_a_field_out_of_the_constructor_still_collides(self) -> None:
        # `x` is not a parameter, so the two never meet in the
        # signature -- but they do meet in the repr, which showed two
        # keys called `x`.
        with pytest.raises(TypeError, match="known as 'x'"):
            class Clash(Magic):
                x: NoInit[int] = 1
                _x: int = 2

    def test_an_alias_colliding_with_a_plain_field_is_rejected(self) -> None:
        # No underscore in sight: an alias lands on the name another
        # field already has.
        with pytest.raises(TypeError, match="known as 'b'"):
            class Coll(Magic):
                a: Annotated[int, Field(alias="b")] = 1
                b: NoInit[int] = 2

    def test_a_pseudo_field_collides_too(self) -> None:
        with pytest.raises(TypeError, match="known as 'unit'"):
            class Shifted(Magic):
                _unit: ClassVar[str] = "m"
                unit: str = "m"

    def test_a_collision_inherited_from_a_base_is_rejected(self) -> None:
        class Base(Magic):
            _x: int = 0

        with pytest.raises(TypeError, match="known as 'x'"):
            class Sub(Base):
                x: NoInit[int] = 1

    def test_an_alias_of_its_own_settles_the_collision(self) -> None:
        class Fixed(Magic):
            x: NoInit[int] = 1
            _x: Annotated[int, Field(alias="ex")] = 2

        assert repr(Fixed(5)) == "Fixed(x=1, ex=5)"

    def test_a_field_named_self_still_works(self) -> None:
        class C(Magic):
            self: int

        assert C(1).self == 1


class TestMappingKey:

    def test_a_subclass_turning_mapping_on_sees_inherited_fields(self) -> None:
        # The class option says whether there is a view at all; every
        # real field belongs in one, whichever class declared it.
        class Base(Magic):
            x: int = 1

        class Sub(Base, mapping=True):
            z: int = 3

        assert dict(Sub()) == {"x": 1, "z": 3}
        assert len(Sub()) == 2

    def test_a_class_turning_mapping_on_below_two_levels(self) -> None:
        class Base(Magic):
            x: int = 1

        class Middle(Base):
            y: int = 2

        class Sub(Middle, mapping=True):
            z: int = 3

        assert dict(Sub()) == {"x": 1, "y": 2, "z": 3}

    def test_a_pseudo_field_still_has_no_key(self) -> None:
        class C(Magic, mapping=True):
            a: int = 1
            tag: ClassVar[str] = "x"

        assert dict(C()) == {"a": 1}
        assert C.__magic_fields__["tag"].public_key is None
    """Two fields cannot share one key of the dict-like view."""

    def test_two_explicit_keys_that_are_the_same_are_rejected(self) -> None:
        # Both fields answered to `k`, so `a` was unreachable through
        # the view and `len()` came out one short of the field count.
        with pytest.raises(TypeError, match="both take 'k' as their key"):
            class Row(Magic, mapping=True):
                a: Annotated[int, Key("k")] = 1
                b: Annotated[int, Key("k")] = 2

    def test_the_same_pair_is_rejected_without_a_view(self) -> None:
        # A key is carried by the field, and `mapping` can be turned on
        # by any subclass, so the pair is refused where it is written
        # rather than on the first subclass that asks for a view.
        with pytest.raises(TypeError, match="both take 'k' as their key"):
            class Row(Magic):
                a: Annotated[int, Key("k")] = 1
                b: Annotated[int, Key("k")] = 2

    def test_an_explicit_key_landing_on_a_field_name_is_rejected(self) -> None:
        # `k` takes its key from its own name, `b` asks for the same one.
        with pytest.raises(TypeError, match="'k' and 'b'"):
            class Row(Magic, mapping=True):
                k: int = 1
                b: Annotated[int, Key("k")] = 2

    def test_a_collision_inherited_from_a_base_is_rejected(self) -> None:
        class Base(Magic, mapping=True):
            a: Annotated[int, Key("k")] = 1

        with pytest.raises(TypeError, match="'a' and 'b'"):
            class Sub(Base):
                b: Annotated[int, Key("k")] = 2

    def test_keys_of_their_own_are_fine(self) -> None:
        class Row(Magic, mapping=True):
            a: Annotated[int, Key("first")] = 1
            b: Annotated[int, Key("second")] = 2

        assert dict(Row()) == {"first": 1, "second": 2}
        assert len(Row()) == 2

    def test_a_field_out_of_the_view_cannot_collide(self) -> None:
        # `b` has no key at all, so `a` may have the one it gave up.
        class Row(Magic, mapping=True):
            a: Annotated[int, Key("b")] = 1
            b: NotKey[int] = 2

        assert dict(Row()) == {"b": 1}

    def test_a_pseudo_field_named_after_a_key_is_fine(self) -> None:
        # `unit` is a class attribute, never part of the view, so it
        # leaves the key of that name free for a field that is.
        class Row(Magic, mapping=True):
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0
            length: Annotated[int, Key("unit")] = 1

        row = Row()
        assert dict(row) == {"unit": 1}
        assert row.unit == "m"

    def test_the_public_name_check_still_comes_first(self) -> None:
        # Two fields sharing a public name share a key as well; the
        # name is what the reader has to fix, so that is what is said.
        with pytest.raises(TypeError, match="known as 'y'"):
            class Row(Magic, mapping=True):
                _y: int = 1
                y: int = 2


class TestAnnotationPolarity:
    """Every annotation sets its own slots to its own value."""

    # (annotation, expected {slot: value})
    CASES = [
        # `Init` sets neither half: a field is an argument unless
        # something says otherwise.
        ("Init", {"kw": MISSING, "positional": MISSING}),
        ("NoInit", {"kw": False, "positional": False}),
        ("Kw", {"kw": True}),
        ("NotKw", {"kw": False}),
        ("Positional", {"positional": True}),
        ("NotPositional", {"positional": False}),
        ("KwOnly", {"kw": True, "positional": False}),
        ("PositionalOnly", {"kw": False, "positional": True}),
        ("NotKwOnly", {"positional": True}),
        ("NotPositionalOnly", {"kw": True}),
        ("Frozen", {"frozen": True}),
        ("NotFrozen", {"frozen": False}),
        ("Repr", {"repr": True}),
        ("NoRepr", {"repr": False}),
        ("Eq", {"eq": True}),
        ("NoEq", {"eq": False}),
        ("Order", {"order": True}),
        ("NoOrder", {"order": False}),
        ("Compare", {"eq": True, "order": True}),
        ("NoCompare", {"eq": False, "order": False}),
        ("Hash", {"hash": True}),
        ("NoHash", {"hash": False}),
        ("Key", {"key": True}),
        ("NotKey", {"key": False}),
        ("Var", {"var": True}),
        ("InitVar", {"var": True}),
        ("ClassVar", {"kw": False, "positional": False, "var": True}),
    ]

    @pytest.mark.parametrize("name,expected", CASES, ids=[c[0] for c in CASES])
    def test_called_form(self, name: str, expected: dict) -> None:
        annotation = getattr(m, name)()
        for slot, value in expected.items():
            assert getattr(annotation, slot) is value, slot

    @pytest.mark.parametrize("name,expected", CASES, ids=[c[0] for c in CASES])
    def test_subscript_form(self, name: str, expected: dict) -> None:
        # `X[int]` must lower to the same field options as `X()`.
        (annotation,) = tx.get_args(getattr(m, name)[int])[1:]
        for slot, value in expected.items():
            assert getattr(annotation, slot) is value, slot

    def test_multi_slot_inverse_clears_every_slot(self) -> None:
        # Regression: an inverse only ever flipped its first slot, so
        # `NoCompare` cleared `order` and left `eq` at True.
        class C(Magic, order=True):
            x: int
            y: NoCompare[int]

        y = {f.name: f for f in _api.fields(C)}["y"]
        assert (y.eq, y.order) == (False, False)
        assert C(1, 2) == C(1, 99)

    def test_a_mixed_pair_keeps_one_of_each(self) -> None:
        # `KwOnly` is `Kw` + `NotPositional`: the inverse must not flip
        # the positive half.
        class C(Magic):
            x: KwOnly[int]

        assert C(x=1).x == 1
        with pytest.raises(TypeError):
            C(1)

    def test_subscript_keeps_extra_metadata(self) -> None:
        hint = NoRepr[int, "some note"]
        assert tx.get_args(hint)[2] == "some note"


class TestAlwaysGenerated:
    """Every generated method is available under its private name."""

    def test_init_false_still_exposes_the_generated_init(self) -> None:
        class B(Magic, init=False):
            x: int

            def __init__(self, raw: str) -> None:
                self.__magic_init__(int(raw))

        assert B("5").x == 5
        assert "__init__" in B.__dict__          # the user's, not ours
        assert B.__init__ is not B.__magic_init__

    def test_a_renamed_init_is_also_available_privately(self) -> None:
        class R(Magic, init="__setup__"):
            x: int

        assert R.__setup__ is R.__magic_init__

    def test_the_private_init_takes_every_field(self) -> None:
        # Regression: `init=False` used to turn off `init` on each field
        # too, leaving the generated init with no parameters at all.
        class B(Magic, init=False):
            x: int
            y: int

        obj = object.__new__(B)
        obj.__magic_init__(1, 2)
        assert (obj.x, obj.y) == (1, 2)

    @pytest.mark.parametrize(
        "option,private",
        [("repr", "__magic_repr__"), ("eq", "__magic_eq__"),
         ("order", "__magic_lt__"), ("order", "__magic_le__"),
         ("order", "__magic_gt__"), ("order", "__magic_ge__"),
         ("hash", "__magic_hash__")],
    )
    def test_the_private_name_exists_even_when_turned_off(
        self, option: str, private: str
    ) -> None:
        C = m.MetaMagic(
            "C", (Magic,), {"__annotations__": {"x": int}}, **{option: False}
        )
        assert callable(getattr(C, private))

    def test_the_private_repr_still_works_when_repr_is_off(self) -> None:
        class C(Magic, repr=False):
            x: int

        assert C(1).__magic_repr__() == "C(x=1)"


class TestDisabledOptionsDoNotFallThrough:
    """Turning an option off must not inherit a *generated* method."""

    def test_eq_false_compares_by_identity(self) -> None:
        # Regression: `Magic` is itself built with `eq=True` and no
        # fields, so its generated `__eq__` was `all(())` -- True for
        # any two instances of the same class. Every subclass that
        # opted out inherited it.
        class D(Magic, eq=False):
            x: int

        assert (D(1) == D(2)) is False
        assert (D(1) == D(1)) is False
        obj = D(1)
        assert obj == obj

    def test_eq_false_leaves_the_class_hashable(self) -> None:
        # Assigning `__eq__` into a class body makes Python drop
        # `__hash__` unless one is given too -- but a class that
        # compares by identity should hash by identity.
        class D(Magic, eq=False):
            x: int

        obj = D(1)
        assert D.__hash__ is not None
        assert obj in {obj}
        assert D(1) not in {D(1)}

    def test_repr_false_falls_back_to_object(self) -> None:
        class C(Magic, repr=False):
            x: int

        assert repr(C(1)).startswith("<")
        assert "C object at" in repr(C(1))

    def test_order_false_on_an_ordered_base(self) -> None:
        class Ordered(Magic, order=True):
            x: int

        class Unordered(Ordered, order=False):
            y: int

        assert Ordered(1) < Ordered(2)
        assert Ordered(1) <= Ordered(2)
        assert Ordered(2) > Ordered(1)
        assert Ordered(2) >= Ordered(1)
        for compare in (operator.lt, operator.le, operator.gt, operator.ge):
            with pytest.raises(TypeError, match="not supported between"):
                compare(Unordered(1, 2), Unordered(3, 4))

    def test_hash_false_on_a_frozen_base(self) -> None:
        class F(Magic, frozen=True):
            x: int

        class F2(F, hash=False):
            y: int

        assert isinstance(hash(F(1)), int)
        assert F2.__hash__ is None

    def test_a_hand_written_method_survives(self) -> None:
        # Only a *generated* inherited method is neutralised.
        class Base(Magic, eq=False):
            x: int

            def __eq__(self, other: tx.Any) -> tx.Any:
                return "mine"

            __hash__ = None

        class Derived(Base, eq=False):
            y: int

        assert Base(1) == Base(2) == "mine"
        assert Derived(1, 2) == Derived(3, 4) == "mine"

    def test_turning_an_option_back_on_works(self) -> None:
        class A(Magic, eq=False):
            x: int

        class B(A, eq=True):
            y: int

        assert B(1, 2) == B(1, 2)
        assert B(1, 2) != B(1, 3)


class TestHashResolution:
    """What lands on `__hash__` when no field-wise hash is generated."""

    def test_hash_false_wins_over_identity_equality(self) -> None:
        # `eq=False` installs an identity `__eq__`, which would
        # otherwise pull in an identity `__hash__` and quietly undo the
        # `hash=False` the class asked for.
        class C(Magic, eq=False, hash=False):
            x: int

        assert C.__hash__ is None
        with pytest.raises(TypeError, match="unhashable"):
            hash(C(1))

    def test_hashability_does_not_depend_on_the_base(self) -> None:
        # The same resolved options must give the same class, whether
        # they were inherited or written here.
        class Frozen(Magic, frozen=True):
            x: int

        class Inherited(Frozen, eq=False):
            pass

        class Direct(Magic, frozen=True, eq=False):
            x: int

        assert isinstance(hash(Inherited(1)), int)
        assert isinstance(hash(Direct(1)), int)

    def test_a_hand_written_inherited_hash_is_kept(self) -> None:
        class Base(Magic):
            x: int

            def __hash__(self) -> int:
                return 99

        class Sub(Base, eq=False):
            pass

        assert hash(Base(1)) == 99
        assert hash(Sub(1)) == 99

    def test_a_base_that_declares_itself_unhashable_is_respected(
        self,
    ) -> None:
        # `collections.abc.Mapping` sets `__hash__ = None` on purpose.
        # Our own `__hash__ = None` on `Magic` is an artefact and is
        # skipped; a real one from someone else is not.
        class M(Magic, mapping=True, frozen=True, eq=False):
            x: int

        with pytest.raises(TypeError, match="unhashable"):
            hash(M(1))

    def test_a_frozen_class_still_hashes_by_field(self) -> None:
        class F(Magic, frozen=True):
            x: int

        assert hash(F(1)) == hash(F(1))
        assert hash(F(1)) != hash(F(2))


class TestOrderRequiresEq:

    def test_class_level_contradiction_raises(self) -> None:
        # Total ordering over the fields with identity equality gives
        # `not (a < b) and not (b < a) and a != b`.
        with pytest.raises(ValueError, match="eq must be true"):
            class C(Magic, eq=False, order=True):
                x: int

    def test_field_level_contradiction_raises(self) -> None:
        with pytest.raises(ValueError, match="eq must be true"):
            class C(Magic):
                x: Annotated[int, Field(eq=False, order=True)]

    def test_a_field_out_of_eq_is_out_of_order(self) -> None:
        # `NoEq` on its own is not a contradiction: it takes the field
        # out of the ordering too.
        class C(Magic, order=True):
            x: int
            y: NoEq[int]

        assert C(1, 9) < C(2, 0)
        assert not C(1, 0) < C(1, 9)


class TestInitFalseIsAnEscapeHatch:
    """`init=False` must not be blocked by the generated signature."""

    def test_a_non_default_after_a_default(self) -> None:
        class D(Magic, init=False):
            x: int = 0
            y: int

            def __init__(self, y: int) -> None:
                object.__setattr__(self, "x", 0)
                object.__setattr__(self, "y", y)

        assert D(5).y == 5

    def test_the_same_layout_still_raises_when_init_is_on(self) -> None:
        with pytest.raises(SyntaxError, match="without a default"):
            class D(Magic):
                x: int = 0
                y: int

    def test_a_name_collision_is_refused_even_without_an_init(self) -> None:
        # Two fields under one name are a problem wherever that name is
        # used, so turning `__init__` off does not excuse it.
        with pytest.raises(TypeError, match="known as 'v'"):
            class X(Magic, init=False):
                a: Annotated[int, Field(alias="v")]
                b: Annotated[int, Field(alias="v")]


class TestGeneratedMethodNames:

    def test_init_is_named_init(self) -> None:
        # It shows up in every TypeError, traceback and `help()`.
        class Point(Magic):
            x: int
            y: int

        assert Point.__init__.__name__ == "__init__"
        assert Point.__init__.__qualname__.endswith("Point.__init__")
        with pytest.raises(TypeError, match=r"__init__\(\) missing"):
            Point(1)

    def test_a_renamed_init_is_named_after_the_option(self) -> None:
        class R(Magic, init="__setup__"):
            x: int

        assert R.__setup__.__name__ == "__setup__"

    def test_a_reserved_private_name_is_rejected(self) -> None:
        # The class never finishes being built, so bind an existing
        # function rather than writing a body that can never run.
        with pytest.raises(TypeError, match="__magic_init__"):
            class U(Magic):
                x: int
                __magic_init__ = object.__init__

        with pytest.raises(TypeError, match="__magic_eq__"):
            class V(Magic):
                x: int
                __magic_eq__ = object.__eq__


class TestRenamedOptionsAreNeutralised:

    def test_a_renamed_repr_turned_off_by_a_subclass(self) -> None:
        class R(Magic, repr="__show__"):
            x: int

        class RS(R, repr=False):
            pass

        assert R(3).__show__() == "R(x=3)"
        assert "RS object at" in RS(3).__show__()

    def test_a_renamed_eq_turned_off_by_a_subclass(self) -> None:
        class A(Magic, eq="__same__"):
            x: int

        class B(A, eq=False):
            y: int

        assert A(1).__same__(A(1)) is True
        assert B(1, 2).__same__(B(1, 3)) is NotImplemented


class TestClassLevelHideIfNone:

    def test_the_sentinel_reaches_every_field(self) -> None:
        class C(Magic, repr=HIDE_IF_NONE):
            x: Optional[int] = None
            y: int = 1

        assert repr(C()) == "C(y=1)"
        assert repr(C(5)) == "C(x=5, y=1)"


class TestRebuildingIsRejected:
    """A class can only be built by Magic once.

    `@magic` on a class that already inherits `Magic`, or a second
    `@magic` on the same class, would have to rebuild it -- and a
    rebuilt class cannot tell the methods you wrote from the ones the
    first build added. Both spellings have the same, simpler
    alternative: put the options on the class statement.
    """

    def test_decorating_a_magic_subclass(self) -> None:
        class P(Magic):
            x: int

        with pytest.raises(TypeError, match="already a Magic class"):
            @magic(frozen=True)
            class C(P):
                y: int = 0

    def test_double_decoration(self) -> None:
        with pytest.raises(TypeError, match="already a Magic class"):
            @magic(frozen=True)
            @magic()
            class D:
                x: int

    def test_the_error_explains_what_to_do(self) -> None:
        class P(Magic):
            x: int

        with pytest.raises(TypeError) as info:
            @magic(frozen=True)
            class Chord(P):
                y: int = 0

        message = str(info.value)
        # Names the class, both ways of getting here, and the fix --
        # without mentioning metaclasses or anything else internal.
        assert "Chord" in message
        assert "@magic is used twice" in message
        assert "already inherits from Magic" in message
        assert "class Chord(Magic, frozen=True)" in message

    def test_the_class_statement_does_the_same_job(self) -> None:
        # What the error points at, and it needs no rebuild.
        class P(Magic):
            x: int

        class C(P, frozen=True):
            y: int = 0

        assert repr(C(1)) == "C(x=1, y=0)"
        with pytest.raises(AttributeError, match="frozen"):
            C(1).y = 2


class TestDecoratingAPlainClass:
    """The decorator's actual job: a class Magic has not touched."""

    def test_a_plain_class(self) -> None:
        @magic(frozen=True)
        class Point:
            x: float
            y: float

        assert repr(Point(1.0, 2.0)) == "Point(x=1.0, y=2.0)"
        with pytest.raises(AttributeError, match="frozen"):
            Point(1.0, 2.0).x = 3.0

    def test_a_plain_subclass_of_a_plain_class(self) -> None:
        class Base:
            pass

        @magic()
        class C(Base):
            x: int

        assert C(1).x == 1
        assert isinstance(C(1), Base)

    def test_a_field_written_as_a_default(self) -> None:
        @magic()
        class C:
            x: int
            y: int = Field(repr=False)

        assert repr(C(1, 2)) == "C(x=1)"


class TestPrivateInitIsNeverInherited:

    def test_an_unbuildable_init_raises_rather_than_falling_through(
        self,
    ) -> None:
        # Regression: with no `__magic_init__` of its own, the
        # documented delegation resolved to the *base's* -- built over
        # different fields -- and silently set the wrong attributes.
        class P(Magic):
            x: int

        class C(P, init=False):
            y: int = 0
            z: int

            def __init__(self, z: int) -> None:
                self.__magic_init__(z)

        assert C.__magic_init__ is not P.__dict__["__magic_init__"]
        with pytest.raises(TypeError, match="no __init__ could be generated"):
            C(7)

    def test_an_unrelated_error_is_not_swallowed(self) -> None:
        # The tolerant path must catch the two signature errors, not
        # every TypeError -- `_make_init` renders each default's repr,
        # which runs user code.
        class Boom:
            def __repr__(self) -> str:
                raise TypeError("boom from user __repr__")

        with pytest.raises(TypeError, match="boom from user"):
            class H(Magic, init=False, doc=False):
                a: int = Boom()


class TestEqualInstancesHashEqually:

    def test_a_field_out_of_eq_is_out_of_the_hash(self) -> None:
        # Regression (pre-existing): `hash` was forced True, so a field
        # excluded from `__eq__` still counted towards `__hash__` and
        # equal instances landed in different buckets.
        class C(Magic, frozen=True):
            x: int
            y: NoEq[int]

        a, b = C(1, 2), C(1, 3)
        assert a == b
        assert hash(a) == hash(b)
        assert len({a, b}) == 1
        assert {a: "v"}[b] == "v"

    def test_an_explicit_field_hash_still_wins(self) -> None:
        class C(Magic, frozen=True):
            x: int
            y: Annotated[int, Field(eq=False, hash=True)]

        assert C(1, 2) == C(1, 3)
        assert hash(C(1, 2)) != hash(C(1, 3))


class TestSentinelInstanceRepr:

    def test_an_instance_sentinel_still_skips_pseudo_fields(self) -> None:
        class B(Magic, repr=HIDE_IF_NONE()):
            x: int
            tmp: InitVar[int]

            def __post_init__(self, tmp: int) -> None:
                ...

        assert repr(B(1, 2)) == "B(x=1)"

    def test_an_instance_sentinel_skips_class_vars(self) -> None:
        class B(Magic, repr=HIDE_IF_NONE()):
            x: Optional[int] = None
            z: ClassVar[int] = 99

        assert repr(B()) == "B()"


class TestRenamingAlsoNeutralisesTheDunder:
    """Renaming a slot means the dunder is not wanted either."""

    def test_a_renamed_eq(self) -> None:
        # Regression (pre-existing): `Magic`'s own zero-field `__eq__`
        # answered, so any two instances compared equal.
        class R(Magic, eq="__same__"):
            x: int

        assert (R(1) == R(2)) is False
        assert R(1).__same__(R(2)) is False
        assert R(1).__same__(R(1)) is True

    def test_a_renamed_repr(self) -> None:
        class P(Magic, repr="__show__"):
            x: int

        assert repr(P(1)).startswith("<")
        assert P(1).__show__() == "P(x=1)"

    def test_a_renamed_eq_with_ordering(self) -> None:
        class R(Magic, eq="__same__", order=True):
            x: int

        assert R(1) not in [R(2)]


class TestReservedPrivateHash:

    def test_magic_hash_cannot_be_hand_written(self) -> None:
        with pytest.raises(TypeError, match="__magic_hash__"):
            class E(Magic):
                x: int
                __magic_hash__ = object.__hash__


class TestInstallInternals:
    """Corners of the method-installing helpers."""

    def test_a_hand_written_method_is_not_replaced(self) -> None:
        # `eq` is on, so one would normally be generated -- but a method
        # in the class body always wins.
        class C(Magic):
            x: int

            def __eq__(self, other: tx.Any) -> bool:
                return "mine"

        assert C(1) == C(2) == "mine"
        assert C.__magic_eq__(C(1), C(2)) is False

    def test_defining_class_of_an_unknown_name(self) -> None:
        assert m._defining_class((int, object), "__eq__") is int
        assert m._defining_class((int, object), "not_a_real_name") is None

    def test_a_non_magic_base_owns_the_hash(self) -> None:
        # The base's `__hash__` is not one of ours, so there is no
        # generated hash to replace and nothing for us to decide.
        class Base:
            def __hash__(self) -> int:
                return 5

        class C(Base, Magic, eq=False):
            x: int

            def __eq__(self, other: tx.Any) -> bool:
                return NotImplemented

        # Returning NotImplemented leaves Python to fall back on
        # identity, so two of these are equal only if they are the same
        # object.
        one = C(1)
        assert one == one
        assert C(1) != C(1)

        # Writing `__eq__` in a class body without a `__hash__` makes
        # that class unhashable -- Python's own rule, which applies here
        # exactly as it would to a class Magic had never touched.
        assert C.__dict__.get("__hash__", "unset") is None
        with pytest.raises(TypeError, match="unhashable"):
            hash(C(1))

        # Say `__hash__` too, and the base's is what answers.
        class D(Base, Magic, eq=False):
            x: int

            def __eq__(self, other: tx.Any) -> bool:
                return NotImplemented

            __hash__ = Base.__hash__

        assert hash(D(1)) == 5
        assert D(1) != D(1)


# ===============================================================

# Mutable defaults
# ======================================================================


class _Unhashable:
    """A user class that says its values compare by content."""

    def __init__(self) -> None:
        self.items = []

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Unhashable) and self.items == other.items

    __hash__ = None


class _Uncopyable(_Unhashable):
    """Unhashable, and it refuses to be copied."""

    def __copy__(self) -> None:
        raise TypeError("no copies of me")


class _Hashable:
    """A user class that compares by identity, so it never changes."""


class TestMutableDefaults:

    def test_list_default_is_per_instance(self) -> None:
        class C(Magic):
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert a.x == [1]
        assert b.x == []

    def test_dict_default_is_per_instance(self) -> None:
        class C(Magic):
            x: dict = {}

        a, b = C(), C()
        a.x["k"] = 1
        assert b.x == {}

    def test_set_default_is_per_instance(self) -> None:
        class C(Magic):
            x: set = set()

        a, b = C(), C()
        a.x.add(1)
        assert b.x == set()

    def test_bytearray_default_is_per_instance(self) -> None:
        class C(Magic):
            x: bytearray = bytearray(b"ab")

        a, b = C(), C()
        a.x.append(ord("c"))
        assert b.x == bytearray(b"ab")

    def test_promoted_default_equals_the_written_one(self) -> None:
        class C(Magic):
            x: list = [1, 2]
            y: dict = {"k": "v"}

        assert C().x == [1, 2]
        assert C().y == {"k": "v"}

    def test_promoted_default_leaves_no_class_attribute(self) -> None:
        # The copied-from original must not stay reachable (and mutable)
        # on the class, just as it would not for a hand-written factory.
        class C(Magic):
            x: list = []

        assert not hasattr(C, "x")

    def test_explicit_value_still_wins(self) -> None:
        class C(Magic):
            x: list = []

        assert C([1]).x == [1]

    def test_field_default_behaves_the_same(self) -> None:
        class C(Magic):
            x: list = Field(default=[])

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_annotated_field_default_behaves_the_same(self) -> None:
        class C(Magic):
            x: Annotated[list, Field(default=[])]

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_default_annotation_behaves_the_same(self) -> None:
        class C(Magic):
            x: Default[list, []]

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_explicit_factory_is_left_alone(self) -> None:
        class C(Magic):
            x: Factory[list, lambda: [1, 2]]

        assert C().x == [1, 2]

    def test_immutable_default_is_left_alone(self) -> None:
        class C(Magic):
            x: int = 0
            y: str = "hi"
            z: tuple = ()

        assert C().x == 0
        assert C().z is C().z

    def test_unhashable_user_class_is_copied(self) -> None:
        written = _Unhashable()

        class C(Magic):
            x: _Unhashable = written

        a, b = C(), C()
        assert a.x is not b.x
        # A copy, not a different object: it still equals what was
        # written, and equals the other instance's until one is changed.
        assert a.x == written
        assert a.x == b.x
        a.x.items = [1]
        assert b.x.items == []
        assert a.x != b.x

    def test_the_copy_is_shallow(self) -> None:
        # Each instance gets its own list; what that list holds is the
        # same object, exactly as a factory built from the default would
        # give.
        class C(Magic):
            x: list = [[]]

        a, b = C(), C()
        a.x.append(1)
        assert b.x == [[]]
        a.x[0].append(2)
        assert b.x[0] == [2]

    def test_hashable_user_class_is_shared(self) -> None:
        # Nothing to copy: a class that keeps the default `__hash__`
        # compares by identity, so its values do not change.
        class C(Magic):
            x: _Hashable = _Hashable()

        assert C().x is C().x

    def test_uncopyable_default_is_refused(self) -> None:
        with pytest.raises(ValueError, match="cannot be copied"):

            class C(Magic):
                x: _Uncopyable = _Uncopyable()

    def test_raise_action(self) -> None:
        with pytest.raises(ValueError, match="shared by every instance"):

            class C(Magic, mutable_default="raise"):
                x: list = []

    def test_raise_action_names_the_field(self) -> None:
        with pytest.raises(ValueError, match="'tags'"):

            class C(Magic, mutable_default="raise"):
                tags: list = []

    def test_raise_action_allows_a_factory(self) -> None:
        class C(Magic, mutable_default="raise"):
            x: Factory[list]

        assert C().x == []

    def test_allow_action(self) -> None:
        class C(Magic, mutable_default="allow"):
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert b.x == [1]
        assert C.x == [1]

    def test_action_is_inherited(self) -> None:
        class Base(Magic, mutable_default="raise"):
            pass

        with pytest.raises(ValueError, match="shared by every instance"):

            class Sub(Base):
                x: list = []

    def test_unknown_action_is_refused(self) -> None:
        with pytest.raises(ValueError, match="mutable_default must be"):

            class C(Magic, mutable_default="copy"):
                x: list = []

    def test_no_init_list_default_is_per_instance(self) -> None:
        # A field left out of `__init__` is still stored per instance,
        # so its default is copied like any other.
        class C(Magic):
            x: NoInit[list] = []

        a, b = C(), C()
        a.x.append(1)
        assert (a.x, b.x) == ([1], [])

    def test_class_variable_is_still_shared(self) -> None:
        # A `ClassVar` is a class attribute by definition: it is never
        # assigned per instance, so its value is meant to be shared.
        class C(Magic):
            x: ClassVar[list] = []

        C().x.append(1)
        assert C.x == [1]

    def test_frozen_class(self) -> None:
        class C(Magic, frozen=True):
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_slots_class(self) -> None:
        class C(Magic, slots=True):
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_decorator_form(self) -> None:
        @magic
        class C:
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert b.x == []

    def test_decorator_form_takes_the_option(self) -> None:
        @magic(mutable_default="allow")
        class C:
            x: list = []

        a, b = C(), C()
        a.x.append(1)
        assert b.x == [1]


class TestInheritableUnsetValues:
    """What counts as "this field did not say" is decided per attribute."""

    def test_doc_treats_none_as_unset(self) -> None:
        # A resolved field has `doc = None` when none was given, so an
        # inherited doc fills it in.
        class Base(Magic):
            x: Annotated[int, Doc("base doc")] = 1

        class Child(Base):
            x: int = 2

        assert {f.name: f.doc for f in _api.fields(Child)}["x"] == "base doc"

    def test_every_inheritable_attribute_declares_its_unset_values(
        self,
    ) -> None:
        # `_inherit_attrs` looks the values up rather than assuming, so
        # an attribute added to the list without a decision fails here
        # rather than silently treating None as "did not say". That
        # matters because None is a real answer for some of them --
        # `hash = None` means "follow eq".
        default = m._add_fields.__defaults__[-1]
        assert set(default) <= set(m._INHERITABLE)
        for attr, unset in m._INHERITABLE.items():
            assert MISSING in unset, attr

    def test_a_meaningful_none_would_not_be_treated_as_unset(self) -> None:
        # `hash` is not inheritable today; if it ever is, None must keep
        # meaning "follow eq" rather than "unset".
        field = Field(name="x", hash=None)
        other = Field(name="x", hash=True)
        m._inherit_attrs(field, other, ())
        assert field.hash is None


class TestInitHooks:

    def test_hook_without_a_parameter_is_called_with_nothing(self) -> None:
        seen = []

        class C(Magic):
            x: int

            def __post_init__(self, ) -> None:
                seen.append(self.x)

        C(3)
        assert seen == [3]

    def test_hook_with_a_parameter_gets_every_value(self) -> None:
        seen = []

        class C(Magic):
            x: int
            y: int = 2
            s: InitVar[int] = 7

            def __post_init__(self, arguments: Arguments) -> None:
                seen.append(dict(**arguments))

        C(1)
        assert seen == [{"x": 1, "y": 2, "s": 7}]

    def test_values_are_read_by_name_not_by_position(self) -> None:
        class C(Magic):
            first: int
            second: int

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "first", arguments.second)
                object.__setattr__(self, "second", arguments.first)

        c = C(1, 2)
        assert (c.first, c.second) == (2, 1)

    def test_pre_sees_the_values_as_passed(self) -> None:
        seen = []

        class C(Magic, convert=True):
            port: int

            def __pre_init__(self, arguments: Arguments) -> None:
                seen.append(arguments.port)

        C("9000")
        assert seen == ["9000"]

    def test_post_sees_the_values_as_stored(self) -> None:
        seen = []

        class C(Magic, convert=True):
            port: int

            def __post_init__(self, arguments: Arguments) -> None:
                seen.append(arguments.port)

        C("9000")
        assert seen == [9000]

    def test_a_factory_default_is_built_before_pre_runs(self) -> None:
        seen = []

        class C(Magic):
            tags: Factory[list]

            def __pre_init__(self, arguments: Arguments) -> None:
                seen.append(arguments.tags)

        C()
        assert seen == [[]]

    def test_an_inherited_hook_still_runs(self) -> None:
        seen = []

        class Base(Magic):
            def __post_init__(self, arguments: Arguments) -> None:
                seen.append(dict(**arguments))

        class Child(Base):
            x: int

        Child(5)
        assert seen == [{"x": 5}]

    def test_a_hook_in_the_class_body_wins_over_an_inherited_one(self) -> None:
        seen = []

        class Base(Magic):
            def __post_init__(self, arguments: Arguments) -> None:
                seen.append("base")

        class Inherits(Base):
            x: int

        class Overrides(Base):
            x: int

            def __post_init__(self) -> None:
                seen.append("child")

        Inherits(5)
        Overrides(5)
        assert seen == ["base", "child"]

    def test_an_unreadable_hook_does_not_stop_the_class_being_built(
        self,
    ) -> None:
        class C(Magic):
            x: int
            # Nothing you would write on purpose, but it is the shortest
            # thing whose signature cannot be read. The class is still
            # built; the hook only fails when it is actually called.
            __post_init__ = "not a function"

        with pytest.raises(TypeError, match="not callable"):
            C(1)

    def test_more_than_one_parameter_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="takes several arguments"):
            class Bad(Magic):
                x: int
                y: int

                def __post_init__(self, x: int, y: int) -> None:
                    """Two parameters, and only one object to pass."""

    def test_a_parameter_with_a_default_is_still_one_parameter(self) -> None:
        seen = []

        class C(Magic):
            x: int

            def __post_init__(self, arguments: Arguments = None) -> None:
                seen.append(arguments.x)

        C(4)
        assert seen == [4]

    def test_star_args_counts_as_wanting_the_values(self) -> None:
        seen = []

        class C(Magic):
            x: int

            def __post_init__(self, *arguments: Arguments) -> None:
                seen.append(arguments[0].x)

        C(6)
        assert seen == [6]

    def test_a_keyword_only_parameter_does_not_count(self) -> None:
        seen = []

        class C(Magic):
            x: int

            def __post_init__(self, *, tag: str = "none") -> None:
                seen.append(tag)

        C(6)
        assert seen == ["none"]


class TestArguments:

    def test_reads_by_attribute_and_by_key(self) -> None:
        arguments = Arguments(x=1, y=2)
        assert arguments.x == 1
        assert arguments["y"] == 2

    def test_built_from_a_mapping(self) -> None:
        assert Arguments({"x": 1}) == Arguments(x=1)

    def test_behaves_like_a_read_only_mapping(self) -> None:
        arguments = Arguments(x=1, y=2)
        assert list(arguments) == ["x", "y"]
        assert list(arguments.keys()) == ["x", "y"]
        assert len(arguments) == 2
        assert "x" in arguments and "z" not in arguments
        assert arguments.get("z", 3) == 3
        assert dict(**arguments) == {"x": 1, "y": 2}

    def test_repr_lists_the_values(self) -> None:
        assert repr(Arguments(x=1)) == "Arguments(x=1)"

    def test_compares_by_value(self) -> None:
        assert Arguments(x=1) == Arguments(x=1)
        assert Arguments(x=1) != Arguments(x=2)
        assert Arguments(x=1).__eq__(1) is NotImplemented

    def test_an_unknown_name_says_what_was_passed(self) -> None:
        arguments = Arguments(x=1)
        with pytest.raises(AttributeError, match="'x'"):
            assert arguments.nope
        with pytest.raises(KeyError, match="'x'"):
            arguments["nope"]

    def test_an_empty_set_says_so(self) -> None:
        with pytest.raises(AttributeError, match="no arguments"):
            assert Arguments().nope

    def test_the_values_cannot_be_changed(self) -> None:
        arguments = Arguments(x=1)
        with pytest.raises(AttributeError, match="Cannot set"):
            arguments.x = 2
        with pytest.raises(AttributeError, match="Cannot delete"):
            del arguments.x

    def test_a_value_named_after_a_method_is_read_by_key(self) -> None:
        arguments = Arguments(keys=1, get=2)
        assert arguments["keys"] == 1
        assert arguments["get"] == 2


class TestInitHookForms:
    """The shapes a hook can take, and where one is looked for."""

    def test_a_static_method_hook_gets_the_values(self) -> None:
        seen = []

        class C(Magic):
            x: int

            @staticmethod
            def __post_init__(arguments: Arguments) -> None:
                seen.append(arguments.x)

        C(1)
        assert seen == [1]

    def test_a_static_method_hook_can_take_nothing(self) -> None:
        seen = []

        class C(Magic):
            x: int

            @staticmethod
            def __post_init__() -> None:
                seen.append("ran")

        C(1)
        assert seen == ["ran"]

    def test_a_class_method_hook_gets_the_values(self) -> None:
        seen = []

        class C(Magic):
            x: int

            @classmethod
            def __post_init__(cls, arguments: Arguments) -> None:
                seen.append((cls.__name__, arguments.x))

        C(1)
        assert seen == [("C", 1)]

    def test_a_callable_object_hook_gets_the_values(self) -> None:
        seen = []

        class Recorder:
            def __call__(self, arguments: Arguments) -> None:
                seen.append(arguments.x)

        class C(Magic):
            x: int
            __post_init__ = Recorder()

        C(1)
        assert seen == [1]

    def test_a_hook_on_somebody_elses_base_is_left_alone(self) -> None:
        seen = []

        class Legacy:
            """Not a Magic class: its hook was written for someone else."""

            def __post_init__(self, tag: tx.Any) -> None:
                seen.append(tag)

        class C(Magic, Legacy):
            x: int

        instance = C(1)
        assert seen == []

        # Left alone, not taken away: it is still there for whoever
        # wrote it to call.
        instance.__post_init__("theirs")
        assert seen == ["theirs"]

    def test_the_hook_is_read_in_inheritance_order(self) -> None:
        seen = []

        class Base(Magic):
            def __post_init__(self, arguments: Arguments) -> None:
                seen.append(("base", dict(**arguments)))

        class Left(Base):
            pass

        class Right(Base):
            def __post_init__(self) -> None:
                seen.append(("right", None))

        class Both(Left, Right):
            x: int

        # `Right` comes before `Base` in the inheritance order, so its
        # hook is the one called -- and it takes no argument.
        Both(1)
        assert seen == [("right", None)]

        # `Left` does not override it, so there the base's hook runs.
        Left()
        assert seen[-1] == ("base", {})

    def test_the_error_names_the_class(self) -> None:
        with pytest.raises(TypeError, match=r"Bad\.__post_init__"):
            class Bad(Magic):
                x: int
                y: int

                def __post_init__(self, x: int, y: int) -> None:
                    """Two parameters, and only one object to pass."""

    def test_a_value_named_like_the_slot_is_still_reachable(self) -> None:
        seen = []

        class C(Magic):
            v: Annotated[int, Field(alias="_values")]

            def __post_init__(self, arguments: Arguments) -> None:
                seen.append(arguments._values)

        C(3)
        assert seen == [3]

    def test_a_mapping_is_passed_positionally(self) -> None:
        # So that a value of any name can be given as a keyword.
        arguments = Arguments(values=1, named=2)
        assert (arguments.values, arguments.named) == (1, 2)


# ======================================================================
# Generic classes
# ======================================================================

_T = tx.TypeVar("_T")
_TInt = tx.TypeVar("_TInt", bound=int)


class GenericBox(Magic, tx.Generic[_T]):
    item: _T


class PlainBase(Magic):
    a: int


class GenericSubclass(PlainBase, tx.Generic[_T]):
    b: _T


class TestGenericClasses:
    """A class that takes a type parameter: `class Box(Magic, Generic[T])`."""

    def test_a_generic_class_can_be_defined(self) -> None:
        # Regression: `Generic` used to refuse the class outright.
        assert GenericBox.__parameters__ == (_T,)
        assert [f.name for f in _api.fields(GenericBox)] == ["item"]

    def test_the_generated_methods_work(self) -> None:
        box = GenericBox(1)
        assert box.item == 1
        assert repr(box) == "GenericBox(item=1)"
        assert box == GenericBox(1)
        assert box != GenericBox(2)

    def test_a_parameterised_class_builds_an_instance(self) -> None:
        box = GenericBox[int](1)
        assert isinstance(box, GenericBox)
        assert box == GenericBox(1)

    def test_a_generic_subclass_of_a_plain_class(self) -> None:
        child = GenericSubclass(1, "two")
        assert (child.a, child.b) == (1, "two")
        assert GenericSubclass.__parameters__ == (_T,)

    def test_a_plain_subclass_of_a_generic_class(self) -> None:
        class Labelled(GenericBox[int]):
            label: str = "?"

        assert Labelled(1, "one") == Labelled(1, "one")
        assert repr(Labelled(1)) == "Labelled(item=1, label='?')"

    def test_the_decorator_form(self) -> None:
        @magic
        class Box(tx.Generic[_T]):
            item: _T

        assert Box.__parameters__ == (_T,)
        assert Box[str]("one").item == "one"

    def test_slots_leave_no_instance_dict(self) -> None:
        class Box(Magic, tx.Generic[_T], slots=True):
            item: _T

        assert Box.__slots__ == ("item",)
        assert not hasattr(Box(1), "__dict__")

    def test_frozen_and_ordered(self) -> None:
        class Box(Magic, tx.Generic[_T], frozen=True, order=True):
            item: _T

        assert sorted([Box(2), Box(1)]) == [Box(1), Box(2)]
        assert hash(Box(1)) == hash(Box(1))

    def test_round_trips(self) -> None:
        assert _round_trips(GenericBox(1)) == [GenericBox(1)] * 3
        assert _round_trips(GenericBox[int]) == [GenericBox[int]] * 3

    def test_a_bare_type_parameter_converts_to_nothing(self) -> None:
        # There is no type to convert to, so the value is left alone.
        class Box(Magic, tx.Generic[_T], convert=True):
            item: _T

        assert Box("one").item == "one"

    def test_a_bare_type_parameter_accepts_any_value(self) -> None:
        class Box(Magic, tx.Generic[_T], validate=True):
            item: _T

        assert Box("one").item == "one"

    def test_a_bounded_type_parameter_converts_to_its_bound(self) -> None:
        class Box(Magic, tx.Generic[_TInt], convert=True):
            item: _TInt

        assert Box("1").item == 1

    def test_a_bounded_type_parameter_validates_against_its_bound(
        self
    ) -> None:
        class Box(Magic, tx.Generic[_TInt], validate=True):
            item: _TInt

        assert Box(1).item == 1
        with pytest.raises(ValidationError):
            Box("one")

    def test_plain_generic_is_still_refused(self) -> None:
        # `Generic` itself is not a base you can write; only `Generic[T]`.
        with pytest.raises(TypeError, match="plain Generic"):
            class Box(Magic, tx.Generic):
                item: int


# ======================================================================
# Filling a type parameter in
# ======================================================================


_S = tx.TypeVar("_S")


class ConvertingBox(Magic, tx.Generic[_T], convert=True):
    item: _T


class ValidatingBox(Magic, tx.Generic[_T], validate=True):
    item: _T


class GenericPair(Magic, tx.Generic[_T, _S], convert=True):
    left: _T
    right: _S


class ConvertingPlain(Magic, convert=True):
    a: int


class PlainChild(ConvertingPlain):
    b: str


class TestFillingATypeParameterIn:

    def test_a_subclass_can_ask_for_conversion_of_a_filled_in_field(
        self,
    ) -> None:
        # Filling the parameter in and deciding a setting again are two
        # separate things, and a class can want both: the type comes
        # from the base it parameterises, the setting from itself.
        class Box(Magic, tx.Generic[_T]):
            item: _T

        class Loose(Box[int], convert=True):
            pass

        class Strict(Box[int], convert=True, override=True):
            pass

        # `Loose` inherits a field already settled without a converter.
        assert Loose("1").item == "1"
        # `Strict` decides `convert` again, against the filled-in type.
        assert Strict("1").item == 1
    """A subclass that says what a base's type parameter stands for."""

    def test_the_field_takes_the_type_that_was_filled_in(self) -> None:
        class IntBox(GenericBox[int]):
            pass

        assert _api.fields_dict(IntBox)["item"].type is int

    def test_the_value_is_converted_to_it(self) -> None:
        class IntBox(ConvertingBox[int]):
            pass

        assert IntBox("1").item == 1

    def test_the_value_is_validated_against_it(self) -> None:
        class IntBox(ValidatingBox[int]):
            pass

        assert IntBox(1).item == 1
        with pytest.raises(ValidationError):
            IntBox("one")

    def test_the_base_is_left_as_it_was(self) -> None:
        # The subclass fills the parameter in for itself only.
        class IntBox(ConvertingBox[int]):
            pass

        assert _api.fields_dict(ConvertingBox)["item"].type is _T
        assert ConvertingBox("1").item == "1"

    def test_a_default_factory_is_built_from_it(self) -> None:
        class Box(Magic, tx.Generic[_T]):
            item: Factory[_T]

        class IntBox(Box[int]):
            pass

        assert IntBox().item == 0

    # -- hints the parameter is buried in ------------------------------

    def test_a_parameter_inside_a_list(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            items: tx.List[_T]

        class IntBox(Box[int]):
            pass

        assert _api.fields_dict(IntBox)["items"].type == tx.List[int]
        assert IntBox(["1", "2"]).items == [1, 2]

    def test_a_parameter_inside_an_optional(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            item: Optional[_T] = None

        class IntBox(Box[int]):
            pass

        assert _api.fields_dict(IntBox)["item"].type == Optional[int]
        assert (IntBox("1").item, IntBox().item) == (1, None)

    def test_a_parameter_inside_a_dict(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            items: tx.Dict[str, _T]

        class IntBox(Box[int]):
            pass

        assert IntBox({"a": "1"}).items == {"a": 1}

    def test_an_annotated_parameter_keeps_its_metadata(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            item: Annotated[_T, Field(alias="why")]

        class IntBox(Box[int]):
            pass

        assert _api.fields_dict(IntBox)["why"].type is int
        assert IntBox(why="1").item == 1

    # -- more than one parameter ---------------------------------------

    def test_both_parameters_are_filled_in(self) -> None:
        class Pair(GenericPair[int, str]):
            pass

        assert Pair("1", "two") == Pair(1, "two")

    def test_one_parameter_filled_in_and_one_left_standing(self) -> None:
        class HalfPair(GenericPair[int, _S], tx.Generic[_S]):
            pass

        fields = _api.fields_dict(HalfPair)
        assert (fields["left"].type, fields["right"].type) == (int, _S)
        # The one left standing behaves as it did: no type to work from,
        # so the value goes through as it is.
        assert HalfPair("1", "two") == HalfPair(1, "two")

    def test_a_hint_with_no_parameter_of_its_own_is_left_alone(
        self
    ) -> None:
        class Pair(Magic, tx.Generic[_T, _S]):
            left: _T
            rights: tx.List[_S]
            label: str = "?"

        class HalfPair(Pair[int, _S], tx.Generic[_S]):
            pass

        fields = _api.fields_dict(HalfPair)
        assert fields["left"].type is int
        assert fields["label"].type is str
        # Not merely equal to the hint it started as: the very same one.
        assert fields["rights"].type is _api.fields_dict(Pair)["rights"].type

    def test_a_parameter_passed_straight_through_fills_nothing_in(
        self
    ) -> None:
        class Relabelled(ConvertingBox[_T], tx.Generic[_T]):
            pass

        assert _api.fields_dict(Relabelled)["item"].type is _T

    # -- along a chain of classes --------------------------------------

    def test_a_chain_of_three_classes(self) -> None:
        class Middle(ConvertingBox[int]):
            pass

        class Leaf(Middle):
            pass

        assert _api.fields_dict(Leaf)["item"].type is int
        assert Leaf("1").item == 1

    def test_a_generic_class_in_the_middle_of_the_chain(self) -> None:
        class Middle(ConvertingBox[_T], tx.Generic[_T]):
            pass

        class Leaf(Middle[int]):
            pass

        assert Leaf("1").item == 1

    # -- what must not change ------------------------------------------

    def test_a_field_the_subclass_declares_again_keeps_its_own_type(
        self
    ) -> None:
        class Redeclared(ConvertingBox[int]):
            item: str

        assert _api.fields_dict(Redeclared)["item"].type is str
        assert Redeclared("one").item == "one"

    def test_a_converter_that_was_given_rather_than_worked_out(
        self
    ) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            item: ConvertTo[_T, str.upper]

        class IntBox(Box[int]):
            pass

        assert _api.fields_dict(IntBox)["item"].type is int
        assert IntBox("hi").item == "HI"

    def test_a_plain_subclass_of_a_plain_class_is_untouched(self) -> None:
        # Not merely equivalent: the very same converter, so nothing was
        # built again behind the scenes.
        inherited = _api.fields_dict(PlainChild)["a"]
        declared = _api.fields_dict(ConvertingPlain)["a"]
        assert inherited.type is declared.type
        assert inherited.converter is declared.converter

    def test_a_filled_in_field_really_does_get_a_new_converter(self) -> None:
        # The other half of the test above: an identity check only says
        # something if it can fail.
        class IntBox(ConvertingBox[int]):
            pass

        assert (
            _api.fields_dict(IntBox)["item"].converter
            is not _api.fields_dict(ConvertingBox)["item"].converter
        )

    def test_which_of_the_three_came_from_the_type(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            given: ConvertTo[_T, str.upper]
            worked_out: _T

        fields = _api.fields_dict(Box)
        assert fields["given"].derived == ()
        assert fields["worked_out"].derived == ("converter",)

    def test_a_type_still_written_as_a_name_is_filled_in_too(self) -> None:
        class Box(Magic, tx.Generic[_T], convert=True):
            item: _T

        class LaterBox(Box["_Later"]):
            pass

        assert LaterBox(3).item == _Later(3)


class _Later(Magic):
    value: int


# ======================================================================
# replace / asdict / astuple / fields_dict / is_magic
# ======================================================================


class TestParityHelpers:
    """The functions that work on a built class or one of its instances."""

    # -- replace -------------------------------------------------------

    def test_replace_changes_one_value_and_keeps_the_rest(self) -> None:
        class Point(Magic):
            x: int
            y: int

        assert _api.replace(Point(1, 2), y=20) == Point(1, 20)

    def test_replace_works_on_a_frozen_class(self) -> None:
        class Point(Magic, frozen=True):
            x: int
            y: int

        original = Point(1, 2)
        assert _api.replace(original, x=10) == Point(10, 2)
        # The original is untouched: a copy was built, not mutated.
        assert original == Point(1, 2)

    def test_replace_converts_the_new_value(self) -> None:
        class Conv(Magic, convert=True):
            n: int

        assert _api.replace(Conv(1), n="5").n == 5

    def test_replace_validates_the_new_value(self) -> None:
        class Check(Magic, validate=True):
            n: int

        with pytest.raises(ValidationError):
            _api.replace(Check(1), n="five")

    def test_replace_runs_post_init(self) -> None:
        class Doubled(Magic):
            n: int

            def __post_init__(self) -> None:
                object.__setattr__(self, "n", self.n * 2)

        assert Doubled(3).n == 6
        assert _api.replace(Doubled(3), n=5).n == 10

    def test_replace_names_changes_after_the_constructor(self) -> None:
        class Account(Magic):
            _id: Annotated[int, Field(alias="id")]

        account = _api.replace(Account(1), id=2)
        assert account._id == 2
        with pytest.raises(TypeError, match="no field named '_id'"):
            _api.replace(Account(1), _id=2)

    def test_replace_rejects_a_name_that_is_not_a_field(self) -> None:
        class Point(Magic):
            x: int

        with pytest.raises(TypeError, match="no field named 'z'"):
            _api.replace(Point(1), z=2)

    def test_replace_rejects_a_field_the_constructor_does_not_take(
        self
    ) -> None:
        class Cached(Magic):
            x: int
            seen: NoInit[int] = 0

        with pytest.raises(TypeError, match="does not take 'seen'"):
            _api.replace(Cached(1), seen=5)

    def test_replace_does_not_carry_over_a_non_init_field(self) -> None:
        # It is not a constructor argument, so there is no way to hand it
        # across: the copy gets whatever the class gives it.
        class Cached(Magic):
            x: int
            seen: NoInit[int] = 0

        original = Cached(1)
        object.__setattr__(original, "seen", 99)
        assert _api.replace(original, x=2).seen == 0

    def test_replace_rejects_a_class_var(self) -> None:
        class Counted(Magic):
            x: int
            unit: ClassVar[str] = "clicks"

        with pytest.raises(TypeError, match="does not take 'unit'"):
            _api.replace(Counted(1), unit="taps")

    def test_replace_needs_an_init_var_that_has_no_default(self) -> None:
        class Shifted(Magic):
            x: int
            by: InitVar[int]

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "x", self.x + arguments.by)

        shifted = Shifted(1, by=2)
        assert shifted.x == 3
        with pytest.raises(TypeError, match="pass by= as well"):
            _api.replace(shifted, x=10)
        assert _api.replace(shifted, x=10, by=5).x == 15

    def test_replace_lets_a_defaulted_init_var_default_again(self) -> None:
        class Scaled(Magic):
            size: float
            scale: InitVar[float] = 1.0

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "size", self.size * arguments.scale)

        scaled = Scaled(2.0, scale=3.0)
        assert scaled.size == 6.0
        assert _api.replace(scaled).size == 6.0
        assert _api.replace(scaled, scale=2.0).size == 12.0

    def test_replace_needs_an_instance(self) -> None:
        class Point(Magic):
            x: int

        with pytest.raises(TypeError, match="needs an instance"):
            _api.replace(Point, x=1)
        with pytest.raises(TypeError, match="needs an instance"):
            _api.replace(object())

    # -- asdict --------------------------------------------------------

    def test_asdict_returns_every_field_in_order(self) -> None:
        class Point(Magic):
            x: int
            y: int

        assert _api.asdict(Point(1, 2)) == {"x": 1, "y": 2}
        assert list(_api.asdict(Point(1, 2))) == ["x", "y"]

    def test_asdict_does_not_recurse_or_copy(self) -> None:
        class Inner(Magic):
            n: int

        class Outer(Magic):
            inner: Inner
            items: list

        items = [1, 2]
        outer = Outer(Inner(1), items)
        assert _api.asdict(outer) == {"inner": Inner(1), "items": [1, 2]}
        assert isinstance(_api.asdict(outer)["inner"], Inner)
        assert _api.asdict(outer)["items"] is items

    def test_asdict_keys_by_the_constructor_name(self) -> None:
        class Account(Magic):
            _id: Annotated[int, Field(alias="id")]
            _tag: str

        assert _api.asdict(Account(1, "a")) == {"id": 1, "tag": "a"}

    def test_asdict_skips_pseudo_fields(self) -> None:
        class Shifted(Magic):
            x: int
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0

        assert _api.asdict(Shifted(1)) == {"x": 1}

    def test_asdict_covers_more_than_dict(self) -> None:
        # The dict-like interface is about the fields marked as keys;
        # asdict is about all of them.
        class Row(Magic, mapping=True):
            name: str
            age: Annotated[int, Field(key=False)]

        row = Row("ada", 36)
        assert dict(row) == {"name": "ada"}
        assert _api.asdict(row) == {"name": "ada", "age": 36}

    def test_asdict_needs_an_instance(self) -> None:
        with pytest.raises(TypeError, match="needs an instance"):
            _api.asdict(object())

    # -- astuple -------------------------------------------------------

    def test_astuple_returns_the_values_in_field_order(self) -> None:
        class Point(Magic):
            x: int
            y: int

        assert _api.astuple(Point(1, 2)) == (1, 2)

    def test_astuple_follows_the_reverse_option(self) -> None:
        class Base(Magic, reverse=True):
            a: int

        class Derived(Base):
            b: int

        assert [f.name for f in _api.fields(Derived)] == ["b", "a"]
        assert _api.astuple(Derived(1, 2)) == (1, 2)
        assert _api.asdict(Derived(1, 2)) == {"b": 1, "a": 2}

    def test_astuple_does_not_recurse_or_copy(self) -> None:
        class Inner(Magic):
            n: int

        class Outer(Magic):
            inner: Inner

        inner = Inner(1)
        assert _api.astuple(Outer(inner)) == (inner,)
        assert _api.astuple(Outer(inner))[0] is inner

    def test_astuple_skips_pseudo_fields(self) -> None:
        class Shifted(Magic):
            x: int
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0

        assert _api.astuple(Shifted(1)) == (1,)

    def test_astuple_needs_an_instance(self) -> None:
        with pytest.raises(TypeError, match="needs an instance"):
            _api.astuple(object())

    # -- fields_dict ---------------------------------------------------

    def test_fields_dict_is_the_mapping_form_of_fields(self) -> None:
        class Point(Magic):
            x: int
            y: int

        found = _api.fields_dict(Point)
        assert list(found) == ["x", "y"]
        assert tuple(found.values()) == _api.fields(Point)

    def test_fields_dict_keys_by_the_constructor_name(self) -> None:
        class Account(Magic):
            _id: Annotated[int, Field(alias="id")]

        found = _api.fields_dict(Account)
        assert list(found) == ["id"]
        assert found["id"].name == "_id"

    def test_fields_dict_skips_pseudo_fields(self) -> None:
        class Shifted(Magic):
            x: int
            unit: ClassVar[str] = "m"
            by: InitVar[int] = 0

        assert list(_api.fields_dict(Shifted)) == ["x"]

    def test_fields_dict_of_a_plain_class_is_empty(self) -> None:
        # The same answer `fields` gives, for the same reason: a class
        # that was never built has no fields to report.
        class Plain:
            x: int

        assert _api.fields_dict(Plain) == {}

    # -- is_magic ------------------------------------------------------

    def test_is_magic_on_every_shape(self) -> None:
        class Point(Magic):
            x: int

        class Sub(Point):
            y: int

        @magic
        class Decorated:
            x: int

        class Plain:
            x: int

        assert _api.is_magic(Point) and _api.is_magic(Point(1))
        assert _api.is_magic(Sub) and _api.is_magic(Sub(1, 2))
        assert _api.is_magic(Decorated) and _api.is_magic(Decorated(1))
        assert _api.is_magic(Magic)
        assert not _api.is_magic(Plain)
        assert not _api.is_magic(Plain())
        assert not _api.is_magic(int)
        assert not _api.is_magic(3)

    def test_is_magic_is_not_inheritance_from_magic(self) -> None:
        # A decorated class gets the fields and the generated methods
        # without gaining `Magic` as a base.
        @magic
        class Decorated:
            x: int

        assert not issubclass(Decorated, Magic)
        assert _api.is_magic(Decorated)

    # -- how each value is passed back ---------------------------------

    def test_replace_with_a_positional_only_field(self) -> None:
        # A positional-only parameter cannot be passed by name, so the
        # copy has to count it off instead.
        class P(Magic):
            a: PositionalOnly[int] = 1
            b: int = 2

        assert _api.replace(P(7, 8), b=9) == P(7, 9)
        assert _api.replace(P(7, 8), a=0) == P(0, 8)

    def test_replace_on_a_positional_only_class(self) -> None:
        class PO(Magic, positional_only=True):
            x: int
            y: int

        assert _api.replace(PO(1, 2), y=3) == PO(1, 3)

    def test_replace_with_every_kind_of_parameter(self) -> None:
        class Mix(Magic):
            a: PositionalOnly[int]
            b: int
            c: KwOnly[int] = 3

        mixed = Mix(1, 2, c=4)
        assert _api.replace(mixed, b=20) == Mix(1, 20, c=4)
        assert _api.replace(mixed, a=9, c=5) == Mix(9, 2, c=5)

    def test_replace_keeps_positional_only_arguments_lined_up(self) -> None:
        # A defaulted InitVar sits between two positional-only fields.
        # Leaving it out would shift every value after it along by one,
        # so its default is passed in its place.
        class Mid(Magic, positional_only=True):
            seed: InitVar[int] = 1
            value: int = 2

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "value", self.value + arguments.seed)

        assert Mid(7, 8).value == 15
        assert _api.replace(Mid(7, 8)).value == 16

    def test_replace_hands_an_init_var_factory_back_to_the_class(
        self
    ) -> None:
        class Seeded(Magic):
            n: int = 0
            extra: Annotated[list, Field(var=True, init=True, factory=list)]

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "n", self.n + len(arguments.extra))

        assert Seeded(5).n == 5
        assert _api.replace(Seeded(5), n=7).n == 7

    def test_replace_rejects_a_field_that_is_no_kind_of_argument(
        self
    ) -> None:
        # Neither by position nor by name leaves it out of the
        # signature altogether, the same as opting out of `__init__`.
        class Neither(Magic):
            x: Annotated[int, Field(kw=False, positional=False)] = 5

        assert _api.replace(Neither()) == Neither()
        with pytest.raises(TypeError, match="does not take 'x'"):
            _api.replace(Neither(), x=1)

    # -- the sharp edges -----------------------------------------------

    def test_replace_reruns_a_post_init_that_derives_a_field(self) -> None:
        # The copy starts from the stored value, which the hook has
        # already worked on, so it works on it again. Documented rather
        # than papered over: there is no way to tell a derived value
        # from an original one.
        class Post(Magic):
            x: int = 1
            scale: InitVar[int] = 10

            def __post_init__(self, arguments: Arguments) -> None:
                object.__setattr__(self, "x", self.x * arguments.scale)

        post = Post(5)
        assert post.x == 50
        assert _api.replace(post).x == 500
        assert _api.replace(post, scale=1).x == 50

    def test_an_unset_field_is_left_out_of_asdict(self) -> None:
        class Lazy(Magic):
            a: int = 1
            b: Annotated[int, Field(init=False, repr=False)]

        lazy = Lazy()
        assert lazy.a == 1
        assert _api.asdict(lazy) == {"a": 1}
        lazy.b = 2
        assert _api.asdict(lazy) == {"a": 1, "b": 2}

    def test_an_unset_field_is_reported_not_leaked_by_astuple(self) -> None:
        class Lazy(Magic):
            a: int = 1
            b: Annotated[int, Field(init=False, repr=False)]

        with pytest.raises(
            AttributeError, match="Lazy.b has never been given a value"
        ):
            _api.astuple(Lazy())

    def test_the_three_views_of_one_unset_field(self) -> None:
        # A key names the field it belongs to and a position does not,
        # so the two dict-shaped answers can leave a field out where
        # the tuple cannot.
        class Draft(Magic, mapping=True):
            title: str
            slug: NoInit[str]

        draft = Draft("Ada")
        assert _api.asdict(draft) == {"title": "Ada"}
        assert dict(draft) == _api.asdict(draft)
        with pytest.raises(
            AttributeError, match="Draft.slug has never been given a value"
        ):
            _api.astuple(draft)

    def test_an_unset_field_is_reported_by_replace_too(self) -> None:
        # Reachable through a hand-written `__init__` that leaves a
        # constructor argument unassigned.
        class Half(Magic, init=False):
            a: int
            b: int

            def __init__(self, a: int) -> None:
                object.__setattr__(self, "a", a)

        with pytest.raises(
            AttributeError, match="Half.b has never been given a value"
        ):
            _api.replace(Half(1), a=2)

    # -- the public face -----------------------------------------------

    def test_every_helper_is_exported(self) -> None:
        import bagof.magic as package

        for name in ("fields", "fields_dict", "asdict", "astuple",
                     "replace", "is_magic"):
            assert name in package.__all__
            assert getattr(package, name) is getattr(_api, name)

# Quoted annotations
# ======================================================================
# This module has no `from __future__ import annotations`, so an
# annotation is only text when it is written in quotes -- which is what
# these two tests are about. The whole-module case has its own file,
# `test_annotations_as_strings.py`.


class TestQuotedAnnotations:

    def test_a_quoted_type_stays_text(self) -> None:
        class Node(Magic):
            value: int = 0
            parent: "Node" = None

        assert Node.__magic_fields__["parent"].type == "Node"
        assert Node(1, Node(2)).parent.value == 2

    def test_a_quoted_family_annotation_still_applies(self) -> None:
        class Server(Magic):
            port: int = 80
            debug: "KwOnly[bool]" = False

        parameters = signature(Server.__init__).parameters
        assert parameters["debug"].kind is Parameter.KEYWORD_ONLY


# ======================================================================
# Which field a failure is about
# ======================================================================
# A converter, a validator and a factory each say what went wrong and
# nothing about where. These are about the class and the field being
# named too, without losing what went wrong.


class TestTheFailingFieldIsNamed:

    def test_conversion_names_the_class_and_the_field(self) -> None:
        class Server(Magic, convert=True):
            port: int

        with pytest.raises(ConversionError) as caught:
            Server("not a number")
        assert "Server.port" in str(caught.value)
        assert "'not a number'" in str(caught.value)

    def test_validation_names_the_class_and_the_field(self) -> None:
        class Server(Magic, validate=True):
            port: int

        with pytest.raises(ValidationError) as caught:
            Server("nope")
        assert "Server.port" in str(caught.value)
        assert "'nope'" in str(caught.value)

    def test_the_field_that_failed_is_the_one_named(self) -> None:
        class Ports(Magic, convert=True):
            first: int
            second: int

        with pytest.raises(ConversionError) as caught:
            Ports(1, "not a number")
        assert "Ports.second" in str(caught.value)
        assert "Ports.first" not in str(caught.value)

    def test_a_nested_class_names_every_field_on_the_way(self) -> None:
        class Inner(Magic, convert=True):
            name: str

        class Outer(Magic, convert=True):
            thing: Inner = None

        with pytest.raises(ConversionError) as caught:
            Outer()
        assert "Outer.thing" in str(caught.value)
        assert "Inner.name" in str(caught.value)

    def test_a_factory_failure_names_the_field(self) -> None:
        def boom() -> int:
            raise ValueError("nothing to build it from")

        class Server(Magic):
            port: Factory[int, boom]

        with pytest.raises(ValueError) as caught:
            Server()
        assert "Server.port: could not build a value" in str(caught.value)
        assert "nothing to build it from" in str(caught.value)

    def test_a_factory_failure_names_a_field_that_is_not_a_parameter(
        self
    ) -> None:
        def boom() -> int:
            raise ValueError("nothing to build it from")

        class Server(Magic):
            port: NoInit[Factory[int, boom]]

        with pytest.raises(ValueError) as caught:
            Server()
        assert "Server.port: could not build a value" in str(caught.value)

    def test_a_conversion_on_assignment_names_the_field(self) -> None:
        class Server(Magic, convert=True):
            port: int

        server = Server(80)
        with pytest.raises(ConversionError) as caught:
            server.port = "not a number"
        assert "Server.port" in str(caught.value)

    def test_a_validation_on_assignment_names_the_field(self) -> None:
        class Server(Magic, validate=True):
            port: int

        server = Server(80)
        with pytest.raises(ValidationError) as caught:
            server.port = "nope"
        assert "Server.port" in str(caught.value)

    def test_the_error_is_still_the_one_that_was_raised(self) -> None:
        class Server(Magic, convert=True):
            port: int

        # The class is what a caller catches, so it is unchanged: the
        # narrowest `except` written before still catches.
        with pytest.raises(ValueConversionError) as caught:
            Server("not a number")
        assert type(caught.value) is type(caught.value.__cause__)
        assert isinstance(caught.value, ValueError)

    def test_what_the_error_was_carrying_comes_across(self) -> None:
        class Server(Magic, convert=True):
            port: int

        with pytest.raises(ConversionError) as caught:
            Server("not a number")
        assert caught.value.value == "not a number"

    def test_the_original_is_kept_whole_as_the_cause(self) -> None:
        class Server(Magic, convert=True):
            port: int

        with pytest.raises(ConversionError) as caught:
            Server("not a number")
        original = caught.value.__cause__
        assert isinstance(original, ConversionError)
        # Every word of it is still there, at the end of the fuller one.
        assert str(caught.value).endswith(str(original))

    def test_an_ordinary_error_is_named_too(self) -> None:
        def refuse(value: tx.Any) -> int:
            raise ValueError("I would rather not")

        class Server(Magic):
            port: ConvertTo[int, refuse]

        with pytest.raises(ValueError) as caught:
            Server(80)
        assert "Server.port" in str(caught.value)
        assert "I would rather not" in str(caught.value)
        assert isinstance(caught.value.__cause__, ValueError)

    def test_an_error_that_needs_more_than_a_message_is_left_alone(
        self
    ) -> None:
        class Fussy(Exception):
            def __init__(self, what: str, why: str) -> None:
                super().__init__(what, why)

        raised = []

        def refuse(value: tx.Any) -> int:
            error = Fussy("no", "not that either")
            raised.append(error)
            raise error

        class Server(Magic):
            port: ConvertTo[int, refuse]

        # Nothing can be added to this one without changing its class,
        # and its class is what a caller catches, so it comes through
        # exactly as it was raised.
        with pytest.raises(Fussy) as caught:
            Server(80)
        assert caught.value is raised[0]
        assert caught.value.args == ("no", "not that either")

    def test_nothing_generated_is_mentioned(self) -> None:
        class Server(Magic, convert=True, validate=True):
            port: int

        with pytest.raises(ConversionError) as caught:
            Server("not a number")
        assert "__magic" not in str(caught.value)

    def test_a_value_that_is_fine_is_left_alone(self) -> None:
        class Server(Magic, convert=True, validate=True):
            port: int
            name: str = "localhost"
            spare: NoInit[int] = 8080

        server = Server("80")
        assert server.port == 80
        assert server.name == "localhost"
        assert server.spare == 8080
        server.port = "443"
        assert server.port == 443


class TestFieldNamesThatShadowGeneratedLocals:
    """
    A field may be called anything at all, including the names the
    generated `__init__` is itself written in terms of.
    """

    def test_a_field_named_object(self) -> None:
        class Box(Magic):
            object: int

        box = Box(3)
        assert box.object == 3
        assert repr(box) == "Box(object=3)"

    def test_a_field_named_object_is_stored_on_assignment_too(self) -> None:
        class Box(Magic, convert=True):
            object: int

        box = Box(3)
        box.object = "4"
        assert box.object == 4

    def test_a_field_named_isinstance(self) -> None:
        class Box(Magic):
            isinstance: Factory[list]

        assert Box().isinstance == []
        assert Box([1, 2]).isinstance == [1, 2]

    def test_a_field_named_exception(self) -> None:
        def refuse(value: tx.Any) -> int:
            raise ValueError("I would rather not")

        class Box(Magic):
            Exception: ConvertTo[int, refuse]

        with pytest.raises(ValueError) as caught:
            Box(1)
        assert "Box.Exception" in str(caught.value)
        assert "I would rather not" in str(caught.value)

    def test_a_field_named_after_the_factory_marker(self) -> None:
        class Box(Magic):
            # `alias=False` keeps the leading underscore on the
            # parameter, which is what puts the name in the way.
            _HasFactory: Annotated[list, Field(alias=False, factory=list)]

        box = Box()
        assert box._HasFactory == []
        assert Box([1])._HasFactory == [1]

    def test_all_of_them_at_once(self) -> None:
        class Box(Magic):
            self: int
            object: int
            isinstance: Factory[list]
            Exception: str = "fine"

        box = Box(1, 2)
        assert box.self == 1
        assert box.object == 2
        assert box.isinstance == []
        assert box.Exception == "fine"

    def test_every_generated_statement_under_a_shadowing_name(self) -> None:
        def double(value: int) -> int:
            return value * 2

        def five() -> int:
            return 5

        def three() -> int:
            return 3

        def positive(value: int) -> int:
            if value <= 0:
                raise ValueError("must be positive")
            return value

        # A parameter that is built, converted and validated, and a
        # field that is not a parameter and goes through all three from
        # its own default -- every statement the builder writes, with
        # `object` shadowing the builtin the stores are written with.
        class Box(Magic):
            object: Annotated[
                int,
                Field(factory=five, converter=double, validator=positive),
            ]
            spare: NoInit[
                Annotated[
                    int,
                    Field(factory=three, converter=double,
                          validator=positive),
                ]
            ]

        assert repr(Box()) == "Box(object=10, spare=6)"
        assert repr(Box(4)) == "Box(object=8, spare=6)"
        with pytest.raises(ValueError) as caught:
            Box(-1)
        assert "Box.object" in str(caught.value)
        assert "must be positive" in str(caught.value)
