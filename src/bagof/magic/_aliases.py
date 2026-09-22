"""Normalize public names and install access paths to stored fields."""

import keyword
from functools import wraps

import typing_extensions as tx

from ._constants import MISSING


def _name(name: tx.Any) -> str:
    if (
        not isinstance(name, str)
        or not name.isidentifier()
        or keyword.iskeyword(name)
    ):
        raise ValueError(
            f"Invalid alias or property name {name!r}: use a Python "
            "identifier that is not a keyword."
        )
    return name


def _property_name(name: tx.Any) -> str:
    name = _name(name)
    if name.startswith("__"):
        raise ValueError(
            f"Invalid property name {name!r}: double-underscore names "
            "are reserved by Python."
        )
    return name


def alias_option(value: tx.Any) -> tx.Any:
    """Copy an alias declaration into immutable, validated names."""
    if value is MISSING or value is True or value is False:
        return value
    if isinstance(value, str):
        return _name(value)
    if not isinstance(value, tx.Sequence) or isinstance(value, bytes):
        raise TypeError("alias must be a name, a sequence of names or a bool")
    names = tuple(_name(name) for name in value)
    if not names:
        raise ValueError("alias must contain at least one name")
    if len(set(names)) != len(names):
        raise ValueError("alias contains repeated names")
    return names


def _mode(mode: tx.Any) -> tx.Union[bool, str]:
    if mode is True or mode is False or mode == "readonly":
        return mode
    if mode == "readwrite":
        return True
    raise ValueError(
        "property access must be True, False, 'readwrite' or 'readonly'"
    )


def property_option(value: tx.Any) -> tx.Any:
    """Copy explicit property names and access modes into immutable pairs."""
    if value is MISSING or value is True or value is False:
        return value
    if isinstance(value, str):
        if value in ("readonly", "readwrite"):
            return _mode(value)
        return ((_property_name(value), True),)
    if isinstance(value, tx.Mapping):
        pairs = tuple(
            (_property_name(name), _mode(mode)) for name, mode in value.items()
        )
    elif isinstance(value, tx.Sequence) and not isinstance(value, bytes):
        # Pairs are the already-normalized spelling, also used by copies.
        pairs = tuple(
            (_property_name(item[0]), _mode(item[1]))
            if isinstance(item, tuple) and len(item) == 2
            else (_property_name(item), True)
            for item in value
        )
    else:
        raise TypeError("property must be a name, sequence, mapping or mode")
    if len({name for name, _ in pairs}) != len(pairs):
        raise ValueError("property contains repeated names")
    return pairs


def readonly_property(value: tx.Any) -> tx.Any:
    """Turn every enabled mode of a normalized property value read-only.

    Given the output of `property_option`, force each read/write mode to
    "readonly" while leaving disabled names (`False`) untouched.
    """
    if value is True:
        return "readonly"
    if value is MISSING or value is False or value == "readonly":
        return value
    return tuple(
        (name, mode if mode is False else "readonly") for name, mode in value
    )


class InputAliases:
    """Resolve keywords before binding, hooks or polymorphic selection."""

    def __init__(self, fields: tx.Mapping[str, tx.Any]) -> None:
        self.names = {
            name: field.public_name
            for field in fields.values()
            if field.kw
            for name in field.aliases
        }
        positional = [f for f in fields.values() if f.positional]
        order = [f for f in positional if not f.kw]
        order += [f for f in positional if f.kw]
        self.positions = tuple(f.public_name for f in order)
        self.multiple = any(
            name != target for name, target in self.names.items()
        )

    def normalize(
        self,
        args: tuple,
        kwargs: dict,
        clsname: str,
    ) -> dict:
        result = {}
        occupied = set(self.positions[: len(args)])
        for name, value in kwargs.items():
            target = self.names.get(name, name)
            if name in self.names and (target in result or target in occupied):
                raise TypeError(
                    f"{clsname} got multiple values for argument {target!r}"
                )
            result[target] = value
        return result

    def wrap(self, func: tx.Callable, clsname: str) -> tx.Callable:
        if not self.multiple:
            return func

        @wraps(func)
        def init(instance: tx.Any, /, *args, **kwargs) -> None:
            func(instance, *args, **self.normalize(args, kwargs, clsname))

        return init


class ForwardingProperty(property):
    """An identifiable generated property, so subclasses can replace it."""

    def __init__(self, target: str, mode: tx.Union[bool, str]) -> None:
        self.target = target

        def get(instance: tx.Any) -> tx.Any:
            return getattr(instance, target)

        def set(instance: tx.Any, value: tx.Any) -> None:
            setattr(instance, target, value)

        access = "read/write" if mode is True else "read-only"
        super().__init__(
            get,
            set if mode is True else None,
            doc=f"Alias of {target!r}, with {access} access.",
        )


class RemovedProperty:
    """Mask a generated property removed by a subclass's declaration."""

    def __get__(self, instance: tx.Any, owner: tx.Any = None) -> tx.Any:
        raise AttributeError("This forwarding property is disabled")

    def __set__(self, instance: tx.Any, value: tx.Any) -> None:
        raise AttributeError("This forwarding property is disabled")

    def __delete__(self, instance: tx.Any) -> None:
        raise AttributeError("This forwarding property is disabled")


class AbsentAttribute:
    """Let a new instance field shadow an inherited forwarding descriptor."""

    def __get__(self, instance: tx.Any, owner: tx.Any = None) -> tx.Any:
        raise AttributeError("This field has not been set")


def install_properties(
    clsname: str,
    fields: tx.Mapping[str, tx.Any],
    namespace: dict,
    bases: tx.Sequence[type],
) -> None:
    inherited = {}
    for base in bases:
        for name, value in base.__dict__.items():
            inherited.setdefault(name, value)
    desired = {}
    input_owners = {
        name: field.name for field in fields.values() for name in field.aliases
    }
    for field in fields.values():
        for name, mode in field.properties.items():
            if mode is False:
                continue
            if field.var:
                raise TypeError(
                    f"{clsname}.{field.name}: forwarding properties need "
                    "a stored instance field, not a ClassVar or InitVar"
                )
            if name == field.name:
                # The implicit public-name shorthand may already be stored.
                if not isinstance(field.property, tuple):
                    continue
                raise TypeError(
                    f"{clsname}.{name}: a property cannot target itself"
                )
            if (
                name in fields
                or name in desired
                or name in namespace
                or input_owners.get(name, field.name) != field.name
            ):
                raise TypeError(
                    f"{clsname}: property {name!r} conflicts with an "
                    "existing field, property or class attribute"
                )
            previous = inherited.get(name, MISSING)
            if previous is not MISSING and not isinstance(
                previous, (ForwardingProperty, RemovedProperty)
            ):
                raise TypeError(
                    f"{clsname}: property {name!r} conflicts with an "
                    "inherited attribute"
                )
            desired[name] = ForwardingProperty(field.name, mode)
    for name, previous in inherited.items():
        if isinstance(previous, ForwardingProperty) and name not in desired:
            if name not in namespace:
                if name not in fields:
                    namespace[name] = RemovedProperty()
                elif name not in namespace.get("__slots__", ()):
                    namespace[name] = AbsentAttribute()
    namespace.update(desired)
