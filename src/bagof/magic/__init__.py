"""Classes that build themselves from your type hints.

Everything here is re-exported from the modules beside this one; import
it from `bagof.magic` rather than from those, which are free to move.
"""
from __future__ import annotations

from ._api import *  # noqa: F401, F403
from ._api import __all__ as __all_api__

# The annotation family arrives through `_magic` at run time, but that
# module's `__all__` is assembled as it goes and a type checker only
# reads the literal at the top of it. `_fields` lists its own names in
# one literal, so importing from there directly is what makes
# `Field`, `Factory` and the rest resolve for a checker. It binds names
# that are already bound, so nothing changes when the code runs.
from ._fields import *  # noqa: F401, F403
from ._magic import *  # noqa: F401, F403
from ._magic import MetaMagic  # noqa: F401
from ._magic import __all__ as __all_magic__

__all__ = list(__all_magic__) + list(__all_api__) + ["MetaMagic"]
