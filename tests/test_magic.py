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
