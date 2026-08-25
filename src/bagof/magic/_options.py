from __future__ import annotations

__all__ = ["Options"]
import typing_extensions as tx

from ._utils import SlotsBase, slots


@slots(
    'init',             # Generate __init__ method (or its name)
    'repr',             # Generate __repr__ method (or its name)
    'eq',               # Generate __eq__ method (or its name)
    'order',            # Generate comparison methods (or the name of __lt__)
    'hash',             # Generate __hash__ method (or its name)
    'unsafe_hash',      # Always generate __hash__ method
    'frozen',           # Disable __setattr__ and __delattr__
    'match_args',       # Generate __match_args__ for pattern matching
    'kw_only',          # Make all fields keyword-only by default
    'positional_only',  # Make all fields positional-only by default
    'slots',            # Generate __slots__ and remove __dict__
    'weakref_slot',     # Generate a weakref slot in __slots__
    'factory',          # Use field type as factory if none is provided
    'mutable_default',  # What to do with a mutable default (x: list = [])
    'convert',          # Use field type as converter if none is provided
    'validate',         # Use field type as validator if none is provided
    'convert_defaults',   # Convert a value that came from a default
    'validate_defaults',  # Validate a value that came from a default
    'unresolved_hints',  # What to do about a type hint that never resolves
    'mapping',          # Generate Mapping methods for dict-like behavior
    # Resolve an inherited field's settings again from this class
    'override',
    'reverse',          # Use the reverse MRO order when listing fields
    'doc',              # Generate class docstring from field docstrings
)
class Options(SlotsBase):
    """
    The resolved set of class-level options for a `Magic` class.

    `MetaMagic` builds one `Options` instance per class from the keyword
    arguments passed to the class statement (or to the `magic` decorator),
    merged with the options inherited from base classes in MRO order --
    a base class's value is used unless a derived class explicitly sets
    its own. The result is stored on the class as `cls.__magic_options__`
    and, together with each field's own overrides, decides which dunder
    methods (`__init__`, `__repr__`, `__eq__`, ...) get generated and how.

    See `Magic` for the full list of supported options and their
    defaults.
    """

    _DEFAULTS: tx.Dict[str, tx.Any] = dict(
        init=True,
        repr=True,
        eq=True,
        order=False,
        hash=None,
        unsafe_hash=False,
        frozen=False,
        match_args=False,
        kw_only=False,
        positional_only=False,
        slots=False,
        weakref_slot=False,
        factory=False,
        mutable_default="factory",
        convert=False,
        validate=False,
        convert_defaults=True,
        validate_defaults=True,
        unresolved_hints="warn",
        mapping=False,
        override=False,
        reverse=False,
        doc=True,
    )

    @staticmethod
    def make_default() -> tx.Self:
        """Return a new `Options` instance populated with default values."""
        return Options(**Options._DEFAULTS)
