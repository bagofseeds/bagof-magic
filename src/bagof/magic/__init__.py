"""Classes that build themselves from your type hints.

Everything here is re-exported from the modules beside this one; import
it from `bagof.magic` rather than from those, which are free to move.
"""
from ._api import *  # noqa: F401, F403
from ._api import __all__ as __all_api__

# isort: off
from ._magic import *  # noqa: F401, F403

# The annotation family arrives through `_magic` at run time, but that
# module's `__all__` is assembled as it goes. A type checker follows it
# all the same, and finds the classes. `_checkers` lists the family again
# and, for a checker only, declares each marker so that `Frozen[int]`
# reads as `int`. It has to come after `_magic` to be the binding a
# checker keeps. At run time it binds the same objects again, so nothing
# changes when the code runs.
from ._checkers import *  # noqa: F401, F403

# isort: on
from ._magic import MetaMagic  # noqa: F401
from ._magic import __all__ as __all_magic__

__all__ = list(__all_magic__) + list(__all_api__) + ["MetaMagic"]
