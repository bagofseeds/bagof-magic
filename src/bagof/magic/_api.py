"""Functions you call on a Magic class or one of its instances."""
from __future__ import annotations

import typing_extensions as tx

from ._constants import _FIELDS
from ._fields import Field

__all__ = ["fields"]


def fields(cls: type) -> tx.Tuple[Field]:
    """
    Get the fields of a Magic class.

    Parameters
    ----------
    cls : type
        The class to get the fields of.

    Returns
    -------
    fields : tuple[Field]
        All concrete fields (that are not `ClassVar` or `InitVar`).
    """
    return tuple(
        field for field in getattr(cls, _FIELDS, {}).values()
        if not field.var
    )
