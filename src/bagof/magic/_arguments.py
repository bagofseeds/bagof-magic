"""The object handed to `__pre_init__` and `__post_init__`."""
import typing_extensions as tx

__all__ = ["Arguments"]


class Arguments:
    """The values passed to `__init__`, readable by name.

    A `__pre_init__` or `__post_init__` method that takes a parameter
    receives an `Arguments` instance. The instance holds every value
    that the constructor was called with, for ordinary fields and
    `InitVar` fields alike, with any default already filled in.

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

    `__pre_init__` sees the values as they were passed, and
    `__post_init__` sees them as they were stored, after any conversion
    and validation.

    A value can be read as an attribute or by key, and the whole set can
    be unpacked with `**arguments`:

    ```pycon
    >>> from bagof.magic import Arguments
    >>> arguments = Arguments(radius=2.0, scale=3.0)
    >>> arguments.scale, arguments["scale"], dict(**arguments)
    (3.0, 3.0, {'radius': 2.0, 'scale': 3.0})
    ```

    A value named `keys` or `get` can only be read by key, because those
    two names belong to methods. Every other name, including a name that
    starts with an underscore, can be read either way.
    """

    __slots__ = ("__values",)

    def __init__(
        self, values: tx.Optional[tx.Mapping] = None, /, **named
    ) -> None:
        """
        Parameters
        ----------
        values : mapping, optional
            The values as a single mapping. The parameter is
            positional-only, so a value of any name, `values` included,
            can also be given as a keyword.
        **named
            The values, given as keyword arguments.
        """
        merged = dict(values or {})
        merged.update(named)
        object.__setattr__(self, "_Arguments__values", merged)

    def keys(self) -> tx.KeysView:
        """Return the names, in the order in which `__init__` declares them."""
        return self.__values.keys()

    def get(self, name: str, default: tx.Any = None) -> tx.Any:
        """Return the value passed for `name`, or `default` if none was."""
        return self.__values.get(name, default)

    def __getitem__(self, name: str) -> tx.Any:
        try:
            return self.__values[name]
        except KeyError:
            raise KeyError(
                f"{name!r} was not passed to __init__; it takes "
                f"{', '.join(map(repr, self.__values)) or 'no arguments'}"
            ) from None

    def __getattr__(self, name: str) -> tx.Any:
        # Only reached for a name that is not a slot or a method, so
        # every lookup here is either a value or a mistake.
        try:
            return self.__values[name]
        except KeyError:
            raise AttributeError(
                f"{name!r} was not passed to __init__; it takes "
                f"{', '.join(map(repr, self.__values)) or 'no arguments'}"
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
        return name in self.__values

    def __iter__(self) -> tx.Iterator[str]:
        return iter(self.__values)

    def __len__(self) -> int:
        return len(self.__values)

    def __eq__(self, other: tx.Any) -> bool:
        if other.__class__ is not self.__class__:
            return NotImplemented
        return self.__values == other.__values

    def __repr__(self) -> str:
        values = ", ".join(
            f"{name}={value!r}" for name, value in self.__values.items()
        )
        return f"{type(self).__name__}({values})"
