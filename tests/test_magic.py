"""Unit tests for the bagof.magic module."""
from typing import ClassVar as TypingClassVar
from typing import Optional, Union

import pytest
import typing_extensions as tx
from bagof.validators.exceptions import ValidationError
from typing_extensions import Annotated

import bagof.magic as m
from bagof.magic import (
    HIDE_IF_NONE,
    ClassVar,
    ConvertTo,
    Default,
    Doc,
    Factory,
    Field,
    Frozen,
    InitVar,
    Key,
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
    PositionalOnly,
    Validate,
    magic,
)
from bagof.magic.constants import (
    _FIELDS,
    _OPTIONS,
    MISSING,
    REQUIRED,
    SHOW_ATTR,
)
from bagof.magic.constants import (
    HIDE_IF_NONE as HideIfNoneCls,
)
from bagof.magic.options import Options
from bagof.magic.utils import (
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
        from bagof.magic.constants import _MissingType
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

    def test_order_different_class(self) -> None:
        class A(Magic, order=True):
            x: int

        class B(Magic, order=True):
            x: int

        assert A(1).__lt__(B(2)) is NotImplemented

    def test_no_order_field(self) -> None:
        class Point(Magic, order=True):
            x: int
            y: NoOrder[int]

        # y excluded from ordering
        assert not Point(1, 2) < Point(1, 1)
        assert not Point(1, 1) < Point(1, 2)

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


# ======================================================================
# Slots
# ======================================================================


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
# Var / InitVar / ClassVar
# ======================================================================


class TestVarFields:

    def test_init_var(self) -> None:

        class WithInitVar(Magic):
            x: int
            scale: InitVar[int]

            def __post_init__(self, scale: int) -> None:
                self.x = self.x * scale

        w = WithInitVar(5, 10)
        assert w.x == 50
        assert not hasattr(w, "scale") or getattr(w, "scale", None) is None


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
        f = Field(init=True, repr=False)
        r = repr(f)
        assert "init=True" in r
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


class TestPickle:

    def test_pickle_round_trip(self) -> None:
        import pickle

        restored = pickle.loads(pickle.dumps(PicklePoint(1, 2)))
        assert restored == PicklePoint(1, 2)
        assert restored.x == 1 and restored.y == 2

    def test_pickle_frozen(self) -> None:
        import pickle

        restored = pickle.loads(pickle.dumps(PickleFrozen(5)))
        assert restored == PickleFrozen(5)


# ======================================================================
# Constants: REQUIRED / SHOW_ATTR / HIDE_IF_NONE
# ======================================================================


class TestConstants:

    def test_required_repr(self) -> None:
        assert repr(REQUIRED) == "<REQUIRED>"

    def test_required_bool(self) -> None:
        assert bool(REQUIRED) is True

    def test_required_singleton(self) -> None:
        from bagof.magic.constants import _RequiredType
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
# fields.py: Field internals
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
        # new field has doc MISSING -> the inherit loop hits `continue`.
        new = Field(name="a")
        assert new.doc is MISSING
        m._add_fields(fields, [new], replace=True, reverse=False)
        assert fields["a"] is new

    def test_replace_no_reverse_inherit_copy(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a", doc="newdoc")
        m._add_fields(fields, [new], replace=True, reverse=False)
        # inherit copies the *old* doc onto the new field.
        assert fields["a"].doc == "olddoc"

    def test_replace_no_inherit(self) -> None:
        fields = {"a": Field(name="a", doc="olddoc")}
        new = Field(name="a", doc="newdoc")
        m._add_fields(fields, [new], replace=True, inherit=())
        assert fields["a"] is new
        assert fields["a"].doc == "newdoc"

    def test_replace_reverse(self) -> None:
        fields = {
            "a": Field(name="a", doc="da"),
            "b": Field(name="b", doc="db"),
        }
        new = Field(name="a")  # overrides 'a', doc MISSING
        assert new.doc is MISSING
        m._add_fields(fields, [new], replace=True, reverse=True)
        # new fields go first; the overriding 'a' inherits the old doc.
        assert list(fields) == ["a", "b"]
        assert fields["a"] is new
        assert fields["a"].doc == "da"

    def test_not_replace_no_reverse(self) -> None:
        fields = {"a": Field(name="a")}  # doc MISSING
        new_a = Field(name="a", doc="fromnew")
        new_b = Field(name="b", doc="db")
        m._add_fields(fields, [new_a, new_b], replace=False, reverse=False)
        # existing 'a' preserved, 'b' appended; 'a' inherits new doc.
        assert list(fields) == ["a", "b"]
        assert fields["a"].doc == "fromnew"

    def test_not_replace_reverse(self) -> None:
        fields = {"a": Field(name="a")}  # doc MISSING
        new_a = Field(name="a", doc="fromnew")
        new_b = Field(name="b", doc="db")
        m._add_fields(fields, [new_a, new_b], replace=False, reverse=True)
        assert list(fields) == ["a", "b"]
        assert fields["a"].doc == "fromnew"

    def test_reverse_option_inheritance(self) -> None:
        class Base(Magic, reverse=True):
            x: int

        class Derived(Base):
            y: int

        # reverse=True places derived fields before base fields.
        assert list(getattr(Derived, _FIELDS)) == ["y", "x"]


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

            def __pre_init__(self, s: int) -> None:
                seen.append(s)

            def __post_init__(self, s: int) -> None:
                self.x += s

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

            def __post_init__(self, s: int) -> None:
                object.__setattr__(self, "doubled", s * 2)

        assert C(4).doubled == 8

    def test_kw_only_initvar(self) -> None:
        class C(Magic):
            x: int
            s: Annotated[
                int, Field(var=True, init=True, positional=False, kw=True)
            ]

            def __post_init__(self, s: int) -> None:
                self.x += s

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

        result = m.fields(C)
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

    def test_make_doc_elem_annotated_type(self) -> None:
        # `field.type` being a bare Annotated is only reachable by building
        # a Field directly (the public API always strips Annotated).
        field = Field(name="x", type=Annotated[int, "meta"], doc="hi")
        doc = m._make_doc_elem(field)
        assert doc.startswith("x : int")
        assert "hi" in doc


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

            def __post_init__(self, seed: int) -> None:
                object.__setattr__(self, "x", self.x + seed)

        assert C(1, seed=7).x == 8

    def test_two_fields_mapping_to_one_parameter_is_rejected(self) -> None:
        with pytest.raises(TypeError, match="both map to"):
            class Bad(Magic):
                _y: int
                y: int

    def test_a_field_named_self_still_works(self) -> None:
        class C(Magic):
            self: int

        assert C(1).self == 1


class TestAnnotationPolarity:
    """Every annotation sets its own slots to its own value."""

    # (annotation, expected {slot: value})
    CASES = [
        ("Init", {"init": True}),
        ("NoInit", {"init": False}),
        ("Kw", {"kw": True}),
        ("NotKw", {"kw": False}),
        ("Positional", {"positional": True}),
        ("NotPositional", {"positional": False}),
        ("KwOnly", {"kw": True, "positional": False}),
        ("PositionalOnly", {"kw": False, "positional": True}),
        ("NotKwOnly", {"kw": True, "positional": True}),
        ("NotPositionalOnly", {"kw": True, "positional": True}),
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
        ("InitVar", {"init": True, "var": True}),
        ("ClassVar", {"init": False, "var": True}),
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

        y = {f.name: f for f in m.fields(C)}["y"]
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
         ("order", "__magic_lt__"), ("hash", "__magic_hash__")],
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
        with pytest.raises(TypeError, match="not supported between"):
            assert Unordered(1, 2) < Unordered(3, 4)

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

    def test_two_fields_sharing_a_public_name(self) -> None:
        class X(Magic, init=False):
            a: Annotated[int, Field(alias="v")]
            b: Annotated[int, Field(alias="v")]

        assert X.__name__ == "X"

    def test_the_same_layouts_still_raise_when_init_is_on(self) -> None:
        with pytest.raises(SyntaxError, match="without a default"):
            class D(Magic):
                x: int = 0
                y: int

        with pytest.raises(TypeError, match="both map to"):
            class X(Magic):
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
        with pytest.raises(TypeError, match="__magic_init__"):
            class U(Magic):
                x: int

                def __magic_init__(self) -> None:
                    ...

        with pytest.raises(TypeError, match="__magic_eq__"):
            class V(Magic):
                x: int

                def __magic_eq__(self, other: tx.Any) -> bool:
                    return True


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


class TestRebuild:
    """`@magic`, `slots()` and anything else through `rebuild_cls`."""

    def test_decorating_a_magic_subclass(self) -> None:
        # Regression: `rebuild_cls` copies the class dict, so the second
        # build was handed the first build's generated methods and took
        # them for hand-written ones.
        class P(Magic):
            x: int

        @magic(frozen=True)
        class C(P):
            y: int = 0

        assert C(1).x == 1
        assert repr(C(1)) == "C(x=1, y=0)"
        with pytest.raises(AttributeError, match="frozen"):
            C(1).y = 2

    def test_double_decoration(self) -> None:
        @magic(frozen=True)
        @magic()
        class D:
            x: int

        assert D(1).x == 1

    def test_the_slots_helper(self) -> None:
        # locals
        from bagof.magic.utils import slots as slots_

        @slots_("x")
        class S(Magic):
            x: int

        assert S(1).x == 1

    def test_a_rebuilt_class_still_records_what_it_bound(self) -> None:
        # Otherwise a descendant reads the inherited methods as
        # hand-written and refuses to neutralise them -- silently
        # reinstating the fall-through this all exists to close.
        class P(Magic):
            x: int

        @magic(frozen=True)
        class C(P):
            y: int = 0

        class G(C, eq=False):
            pass

        assert (G(1) == G(1)) is False

    def test_a_field_written_as_a_default_survives_a_rebuild(self) -> None:
        # The first build consumes a `Field()` used as a default value --
        # the class attribute becomes the plain default, or goes away --
        # so a rebuild would otherwise see a field stripped of
        # everything the `Field()` said.
        class P(Magic):
            x: int

        @magic(frozen=True)
        class Rebuilt(P):
            y: int = Field(repr=False)
            z: int = Field(default=5, repr=False)

        class Direct(P, frozen=True):
            y: int = Field(repr=False)
            z: int = Field(default=5, repr=False)

        rebuilt = {f.name: f for f in m.fields(Rebuilt)}
        direct = {f.name: f for f in m.fields(Direct)}
        assert bool(rebuilt["y"].repr) is bool(direct["y"].repr) is False
        assert bool(rebuilt["z"].repr) is bool(direct["z"].repr) is False
        assert rebuilt["z"].default == direct["z"].default == 5
        assert repr(Rebuilt(1, 2)) == "Rebuilt(x=1)"
        assert repr(Direct(1, 2)) == "Direct(x=1)"


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

                def __magic_hash__(self) -> int:
                    return 7
