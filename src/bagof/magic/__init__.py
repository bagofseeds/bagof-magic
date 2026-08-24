"""Classes that build themselves from your type hints.

Everything here is re-exported from the modules beside this one; import
it from `bagof.magic` rather than from those, which are free to move.
"""
from __future__ import annotations

from ._api import *  # noqa: F401, F403
from ._api import __all__ as __all_api__
from ._magic import *  # noqa: F401, F403
from ._magic import MetaMagic  # noqa: F401
from ._magic import __all__ as __all_magic__

__all__ = list(__all_magic__) + list(__all_api__) + ["MetaMagic"]
