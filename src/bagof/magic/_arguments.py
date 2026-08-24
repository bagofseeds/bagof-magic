"""The object handed to `__pre_init__` and `__post_init__`."""
from __future__ import annotations

import typing_extensions as tx

__all__ = ["Arguments"]


class Arguments:
    """Everything that was passed to `__init__`, reachable by name.

    A class whose `__pre_init__` or `__post_init__` takes a parameter is
    handed one of these. It is the whole set of values the constructor
    was called with -- ordinary fields and `InitVar` fields alike, with
    any default already filled in.

    ```pycon
    >>> from bagof.magic import Magic, InitVar
    >>> class Circle(Magic):
    ...     radius: float
    ...     scale: InitVar[float] = 1.0
    ...
    ...     def __post_init__(self, arguments):
    ...         self.radius = self.radius * arguments.scale
    >>> Circle(2.0, scale=3.0)
    Circle(radius=6.0)
    ```

    `__pre_init__` sees the values as they came in; `__post_init__` sees
    them as they were stored, after any conversion and validation.

    Read a value by attribute or by key, and unpack the whole set with
    `**arguments`:

    ```pycon
    >>> from bagof.magic import Arguments
    >>> arguments = Arguments(radius=2.0, scale=3.0)
    >>> arguments.scale, arguments["scale"], dict(**arguments)
    (3.0, 3.0, {'radius': 2.0, 'scale': 3.0})
    ```

    A value named `keys` or `get` can only be read by key, since those
    two names belong to the methods.
    """

    __slots__ = ("_values",)

    def __init__(
        self, _values: tx.Optional[tx.Mapping] = None, **values
    ) -> None:
        """
        Parameters
        ----------
        _values : mapping, optional
            The values, if it is easier to pass them as one mapping.
        **values
            The values, one keyword each.
        """
        merged = dict(_values or {})
        merged.update(values)
        object.__setattr__(self, "_values", merged)

    def keys(self) -> tx.KeysView:
        """The names, in the order `__init__` declares them."""
        return self._values.keys()

    def get(self, name: str, default: tx.Any = None) -> tx.Any:
        """The value passed for `name`, or `default` if there is none."""
        return self._values.get(name, default)

    def __getitem__(self, name: str) -> tx.Any:
        try:
            return self._values[name]
        except KeyError:
            raise KeyError(
                f"{name!r} was not passed to __init__; it takes "
                f"{', '.join(map(repr, self._values)) or 'no arguments'}"
            ) from None

    def __getattr__(self, name: str) -> tx.Any:
        # Only reached for a name that is not a slot or a method, so
        # every lookup here is either a value or a mistake.
        try:
            return self._values[name]
        except KeyError:
            raise AttributeError(
                f"{name!r} was not passed to __init__; it takes "
                f"{', '.join(map(repr, self._values)) or 'no arguments'}"
            ) from None

    def __setattr__(self, name: str, value: tx.Any) -> tx.NoReturn:
        raise AttributeError(
            f"Cannot set {name!r}: these are the values __init__ was "
            f"called with, and changing one here would not change what "
            f"gets stored. Assign to the field instead."
        )

    def __delattr__(self, name: str) -> tx.NoReturn:
        raise AttributeError(
            f"Cannot delete {name!r}: these are the values __init__ was "
            f"called with."
        )

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def __iter__(self) -> tx.Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other: tx.Any) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return self._values == other._values

    def __repr__(self) -> str:
        values = ", ".join(
            f"{name}={value!r}" for name, value in self._values.items()
        )
        return f"{type(self).__name__}({values})"
