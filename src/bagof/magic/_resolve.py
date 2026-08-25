"""
Adapters that resolve a type hint to a field converter / validator /
factory, using the sibling ``bagof-converters``, ``bagof-validators`` and
``bagof-factories`` packages.

A [`Magic`][bagof.magic.Magic] field's ``converter`` and ``validator`` are
both called as ``value = f(value)``. A converter already returns the
converted value, but a validator only *raises* on failure and returns
``None`` -- so it is wrapped to return the value it was given. A ``factory``
is called with no arguments to produce a default value.

A hint is not always a type yet. A class that names itself, a type
imported under ``if TYPE_CHECKING:``, a name bound further down the
module -- each of those reaches the builder as the text it was written
as, because the name it needs is not bound while the class statement is
running. Building a converter out of that text gives one that fails on
every value, so instead the three makers hand back a callable that
resolves the hint the first time it is *used* and builds the real
converter, validator or factory then. By then the module has finished
executing, and the ordinary forward reference simply works.

What is still unresolved at that point is reported once for the field --
not once per call, which would flood a hot constructor -- and the class's
``unresolved_hints`` option says whether that is a warning, an error, or
nothing at all. A value can be passed through unconverted and
unvalidated, so those two carry on; a default value cannot be invented,
so a factory raises whatever the option says.
"""

from __future__ import annotations

__all__ = ["Hints", "POLICIES", "make_converter", "make_validator",
           "make_factory"]

# stdlib
import ast
import builtins
import warnings

# dependencies
import typing_extensions as tx

# bags
from bagof.converters import Converter
from bagof.factories import get_factory
from bagof.validators import Validator

from ._constants import MISSING

#: What `unresolved_hints` accepts, and what each of them does once a
#: hint has failed to resolve on first use.
POLICIES = ("warn", "raise", "ignore")


class _UnresolvedHint(UserWarning):
    """A type hint whose name was still not defined when it was needed."""


class Hints:
    """
    Where the name in an unresolved hint is looked up when the field is
    first used, and what to do if it is still not there.

    Parameters
    ----------
    globals : dict
        The namespace of the module the class is written in.
    namespace : dict
        Names that module does not have. The class being built is put
        here once it exists, so that a class written inside a function
        can still name itself.
    owner : str
        The name of the class, for the report.
    policy : str
        One of `POLICIES`.
    """

    __slots__ = ("globals", "namespace", "owner", "policy")

    def __init__(
        self,
        globals: tx.Optional[dict] = None,
        namespace: tx.Optional[dict] = None,
        owner: str = "",
        policy: str = "warn",
    ) -> None:
        self.globals = {} if globals is None else globals
        self.namespace = {} if namespace is None else namespace
        self.owner = owner
        self.policy = policy

    def where(self, name: str) -> str:
        """`Server.port` -- the field, said the way it was written."""
        return f"{self.owner}.{name}" if self.owner else name


def make_converter(
    hint: tx.Any, hints: tx.Optional[Hints] = None, name: str = ""
) -> tx.Callable[[tx.Any], tx.Any]:
    """Return a callable that converts a value to ``hint``."""
    return _make(_CONVERTER, hint, hints, name)


def make_validator(
    hint: tx.Any, hints: tx.Optional[Hints] = None, name: str = ""
) -> tx.Callable[[tx.Any], tx.Any]:
    """
    Return a callable that validates a value against ``hint`` and returns
    it unchanged (raising on failure).
    """
    return _make(_VALIDATOR, hint, hints, name)


def make_factory(
    hint: tx.Any, hints: tx.Optional[Hints] = None, name: str = ""
) -> tx.Callable[[], tx.Any]:
    """Return a no-argument callable producing a default value for ``hint``."""
    return _make(_FACTORY, hint, hints, name)


# ----------------------------------------------------------------------
# The three, each built from a type that is really there
# ----------------------------------------------------------------------


def _converter(type: tx.Any) -> tx.Callable[[tx.Any], tx.Any]:
    return Converter.get(type)


def _validator(type: tx.Any) -> tx.Callable[[tx.Any], tx.Any]:
    validator = Validator.get(type)

    def validate(value: tx.Any) -> tx.Any:
        validator(value)
        return value

    return validate


def _factory(type: tx.Any) -> tx.Callable[[], tx.Any]:
    return get_factory(type)


def _unchanged(value: tx.Any) -> tx.Any:
    # What a field is worth when the hint it was to be checked against
    # never turned up: whatever it was given.
    return value


class _Kind:
    # One of the three, and how to talk about it: how it is built from a
    # type, how the report words the consequence -- once for carrying on
    # without it, once for refusing -- and what it does instead of the
    # real thing. `fallback` is None for a factory, which has no value to
    # hand back and so has no choice but to refuse.

    __slots__ = ("build", "skipped", "blocked", "fallback")

    def __init__(
        self,
        build: tx.Callable,
        skipped: str,
        blocked: str,
        fallback: tx.Optional[tx.Callable],
    ) -> None:
        self.build = build
        self.skipped = skipped
        self.blocked = blocked
        self.fallback = fallback


_CONVERTER = _Kind(
    _converter,
    "`{name}` is not being converted",
    "`{name}` cannot be converted",
    _unchanged,
)
_VALIDATOR = _Kind(
    _validator,
    "`{name}` is not being validated",
    "`{name}` cannot be validated",
    _unchanged,
)
_FACTORY = _Kind(
    _factory,
    "",
    "no default value can be built for `{name}`",
    None,
)

#: What to do about it, said the same way wherever the report appears.
_REMEDY = (
    "A name that is only imported under `if TYPE_CHECKING:` is not there "
    "at runtime -- import it normally where the class is written."
)


# ----------------------------------------------------------------------
# Hints that are still text
# ----------------------------------------------------------------------


def _make(
    kind: _Kind, hint: tx.Any, hints: tx.Optional[Hints], name: str
) -> tx.Callable:
    text = _unresolved(hint)
    if text is None:
        return kind.build(hint)
    return _Deferred(kind, text, Hints() if hints is None else hints, name)


def _unresolved(hint: tx.Any) -> tx.Optional[str]:
    # The text a hint was written as, when it is a name rather than a
    # type, and None when it is a type and can be used straight away.
    if isinstance(hint, str):
        return hint
    if isinstance(hint, tx.ForwardRef):
        return hint.__forward_arg__
    return None


class _Deferred:
    """A converter, validator or factory for a hint that is still a name."""

    __slots__ = ("_kind", "_text", "_hints", "_name", "_call")

    def __init__(
        self, kind: _Kind, text: str, hints: Hints, name: str
    ) -> None:
        self._kind = kind
        self._text = text
        self._hints = hints
        self._name = name
        self._call = None

    def __call__(self, *value: tx.Any) -> tx.Any:
        call = self._call
        if call is None:
            call = self._call = self._settle()
        return call(*value)

    def _settle(self) -> tx.Callable:
        # The first use is the second chance: the module has finished
        # executing by now, so the name the class statement could not see
        # is almost always there. What is settled here is kept, so a hint
        # that is still missing is reported once and not once per call.
        tree = _readable(self._text)
        type = MISSING if tree is None else _evaluate(self._text, self._hints)
        if type is not MISSING:
            return self._kind.build(type)
        return self._give_up(tree)

    def _give_up(self, tree: tx.Optional[ast.AST]) -> tx.Callable:
        hints, kind = self._hints, self._kind
        if kind.fallback is None or hints.policy == "raise":
            # A factory has nothing to hand back, so saying so quietly is
            # not an option for it whatever the policy is.
            report = self._report(kind.blocked, tree)

            def refuse(*value: tx.Any) -> tx.Any:
                raise NameError(report)

            return refuse
        if hints.policy == "warn":
            # `_give_up`, `_settle`, `__call__`, the generated `__init__`
            # or `__setattr__`, then the line that built the object --
            # which is the one worth pointing at.
            warnings.warn(
                self._report(kind.skipped, tree), _UnresolvedHint,
                stacklevel=5,
            )
        return kind.fallback

    def _report(self, consequence: str, tree: tx.Optional[ast.AST]) -> str:
        where = self._hints.where(self._name)
        reason = _reason(self._text, tree, self._hints)
        said = consequence.format(name=self._name)
        return f"{where}: {reason}, so {said}. {_REMEDY}"


def _readable(text: str) -> tx.Optional[ast.AST]:
    # The hint as an expression, when looking up what it names is all it
    # takes to evaluate it. An annotation is never *called* to find out
    # what a field holds -- not while the class statement runs, and not
    # later either -- so text with a call in it is left unread.
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            return None
    return tree


def _evaluate(text: str, hints: Hints) -> tx.Any:
    # The type a hint names, or MISSING while the names in it are still
    # not defined where the class was written.
    try:
        return eval(text, hints.globals, hints.namespace)
    except Exception:
        return MISSING


def _reason(text: str, tree: tx.Optional[ast.AST], hints: Hints) -> str:
    name = None if tree is None else _undefined_name(tree, hints)
    if name is None:
        return f"the type `{text}` could not be worked out"
    return f"the name `{name}` is not defined"


def _undefined_name(tree: ast.AST, hints: Hints) -> tx.Optional[str]:
    # The first name in the hint that is not defined anywhere it is
    # looked up, so the report can say which one is missing rather than
    # quote the whole annotation back.
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not _defined(node.id, hints):
            return node.id
    return None


def _defined(name: str, hints: Hints) -> bool:
    return (
        name in hints.namespace
        or name in hints.globals
        or hasattr(builtins, name)
    )
