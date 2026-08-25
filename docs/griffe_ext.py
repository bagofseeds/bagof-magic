"""Griffe extension showing the constructor and the fields `Magic` writes.

griffe reads source code without running it. A `Magic` class writes its
`__init__` -- and the rest of its methods -- while the class is being
created, so none of that is in the source for griffe to find: the API
reference for a `Magic` subclass would show a class with no constructor,
no parameters and no fields, which is considerably less than `help()` on
the same class prints.

This extension runs once griffe's object tree is complete (`on_class`),
imports the real class, and fills in what only exists at run time:

- the generated `__init__`, with its true signature and the
  per-parameter documentation the class already writes for `help()`;
- a table of the fields -- name, type, default or factory, and whether
  each one is keyword-only, frozen, converted or validated;
- the other generated methods (`__eq__`, `__repr__`, the dict-like
  interface, ...), each labelled `generated`, so a page can show or hide
  them as a group rather than one at a time.

The runtime `doc` option is left to do its own job: it writes an
`Attributes` section into `__doc__`, which is what `help()` and the REPL
read. This extension serves the site.
"""

from __future__ import annotations

import importlib
import inspect

import griffe

try:
    from bagof.magic import is_magic
    from bagof.magic._constants import (
        _FIELDS,
        _GENERATED,
        _OPTIONS,
        MISSING,
        _HasFactory,
    )
    from bagof.magic._magic import _doc_field_type, _make_mapping
except ImportError:  # pragma: no cover
    # `bagof.magic` is not installed in this docs-build environment, so
    # there is nothing to import and read. Everything below is skipped,
    # and the reference shows whatever reading the source alone found.
    is_magic = None

# A one-line description of each method a class can generate, keyed by
# the option that asks for it. A class records which option each of its
# generated methods came from, so nothing here is keyed by method name:
# an option that takes a name (`eq="same_as"`) binds the method under
# that name instead, and this still describes it correctly.
_GENERATED_DOC = {
    "init": "Build an instance from its fields.",
    "repr": "Show the instance as the call that would build it again.",
    "eq": "Compare field by field with another instance of the same class.",
    "lt": "Order instances by comparing their fields in turn.",
    "le": "Order instances by comparing their fields in turn.",
    "gt": "Order instances by comparing their fields in turn.",
    "ge": "Order instances by comparing their fields in turn.",
    "hash": "Hash the fields that take part in the comparison.",
    "state": "Save and restore the fields, for pickling and copying.",
    "match_args": "The fields a positional pattern matches, in order.",
    "mapping": "Read the fields the way a mapping is read.",
}


def _live_object(obj: griffe.Object) -> object:
    """The real, imported object griffe read this one from the source of.

    `None` when it cannot be reached -- the module does not import in
    this environment, or the object is not bound under the name it is
    written with.
    """
    path = []
    while not obj.is_module and obj.parent is not None:
        path.append(obj.name)
        obj = obj.parent
    try:
        live = importlib.import_module(obj.path)
    except ImportError:
        return None
    for name in reversed(path):
        live = getattr(live, name, None)
        if live is None:
            return None
    return live


def _docstring(text: str, parent: griffe.Object) -> griffe.Docstring:
    """A docstring read the same way as the ones griffe read from source.

    Which style a docstring is written in is a setting of the site, and
    griffe records the answer on everything it reads. A docstring made
    here carries no such record, so it takes the one from the nearest
    object that has it.
    """
    obj = parent
    while obj is not None:
        if obj.docstring is not None:
            return griffe.Docstring(
                text,
                parent=parent,
                parser=obj.docstring.parser,
                parser_options=obj.docstring.parser_options,
            )
        obj = obj.parent
    return griffe.Docstring(text, parent=parent)


def _parameters(func: object, fields: dict) -> griffe.Parameters:
    """The parameters of `func`, typed the way the field table types them.

    The compiled signature annotates each parameter with the name of the
    local that holds its type, which is an internal name and no use to a
    reader. The field behind the parameter has the type itself, spelled
    exactly as `help()` spells it, so the signature and the
    documentation beside it cannot drift apart.
    """
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return griffe.Parameters()
    by_parameter = {field.public_name: field for field in fields.values()}
    parameters = []
    for parameter in signature.parameters.values():
        if parameter.name in ("self", "cls"):
            continue
        field = by_parameter.get(parameter.name)
        parameters.append(
            griffe.Parameter(
                parameter.name,
                annotation=_doc_field_type(field) if field else None,
                kind=griffe.ParameterKind(parameter.kind.description),
                default=(
                    repr(parameter.default)
                    if parameter.default is not inspect.Parameter.empty
                    else None
                ),
            )
        )
    return griffe.Parameters(*parameters)


def _notes(field: object) -> str:
    """What is worth saying about a field beyond its type and default."""
    notes = []
    if field.var:
        notes.append("init-only" if field.init else "class attribute")
    elif not field.init:
        notes.append("not a parameter")
    elif field.kw and not field.positional:
        notes.append("keyword-only")
    elif field.positional and not field.kw:
        notes.append("positional-only")
    if field.frozen:
        notes.append("frozen")
    if field.convert:
        notes.append("converted")
    if field.validate:
        notes.append("validated")
    return ", ".join(notes)


def _description(field: object) -> str:
    """A field's own documentation, on one line.

    Empty for a field that is a constructor parameter: the parameter
    table beside this one already carries its documentation.
    """
    if field.init:
        return ""
    return " ".join((field.doc or "").split())


def _default(field: object) -> str:
    """A field's default, or what builds one, as the table shows it."""
    if field.build:
        return f"`{_HasFactory(field.factory)!r}`"
    if field.default is MISSING:
        return "*required*"
    return f"`{field.default!r}`"


def _field_table(fields: dict) -> str:
    """The fields of a class, as a markdown table.

    Every field has a name, a type and a default, so those are always
    columns. The two that are often the same for every field -- what it
    behaves like, and what it is documented as -- are only columns when
    some field has something to put in them. A field that is a
    constructor parameter is documented in the parameter table beside
    this one, so only a field that is not one counts there.
    """
    columns = [
        ("Field", lambda f: f"`{f.public_name}`"),
        ("Type", lambda f: f"`{_doc_field_type(f)}`"),
        ("Default", _default),
        ("Notes", _notes),
        ("Description", _description),
    ]
    columns = [
        (title, cell)
        for title, cell in columns
        if title in ("Field", "Type", "Default")
        or any(cell(field) for field in fields.values())
    ]
    rows = [
        [title for title, _ in columns],
        ["---"] * len(columns),
    ]
    rows += [
        [cell(field) for _, cell in columns]
        for field in fields.values()
    ]
    lines = ["| " + " | ".join(row) + " |" for row in rows]
    return "**Fields**\n\n" + "\n".join(lines)


def _add_field_table(cls: griffe.Class, fields: dict) -> None:
    """Put the field table at the end of the class's documentation."""
    table = _field_table(fields)
    if cls.docstring is None:
        cls.docstring = _docstring(table, cls)
    else:
        cls.docstring.value = cls.docstring.value.rstrip() + "\n\n" + table


def _add_method(
    cls: griffe.Class, name: str, method: object, doc: str, fields: dict
) -> None:
    """Add one generated method to the class, labelled as generated."""
    function = griffe.Function(
        name,
        parameters=_parameters(method, fields),
        returns="None" if name == "__init__" else None,
        docstring=_docstring(doc, cls) if doc else None,
        parent=cls,
    )
    function.labels.add("generated")
    cls.set_member(name, function)


def _generated_names(live: type) -> dict:
    """Every method the class generated, and the option that asked for it.

    The class keeps this record itself, for every option but the
    dict-like interface -- whose method names are asked of the code that
    writes them.
    """
    names = dict(getattr(live, _GENERATED, None) or {})
    options = getattr(live, _OPTIONS, None)
    if getattr(options, "mapping", False):
        for name in _make_mapping("", {}):
            names.setdefault(name, "mapping")
    return names


class MagicExtension(griffe.Extension):
    """Document what a `Magic` class writes when it is created."""

    def on_class(
        self,
        *,
        cls: griffe.Class,
        loader: griffe.GriffeLoader,
        **kwargs: object,
    ) -> None:
        if is_magic is None:
            return
        live = _live_object(cls)
        if not isinstance(live, type) or not is_magic(live):
            return
        fields = getattr(live, _FIELDS, None) or {}
        if not fields:
            # A class with no fields has nothing this can add: its
            # constructor takes nothing, its field table would be empty,
            # and the methods it generates for no fields say nothing
            # that plain Python does not already say.
            return
        for name, option in _generated_names(live).items():
            method = getattr(live, name, None)
            if not inspect.isroutine(method):
                # Not everything an option writes is a method: a class
                # that compares by identity is given `__hash__ = None`,
                # and `match_args` binds a tuple.
                continue
            if name in cls.members:
                # Reading the source found it, so it is in the class
                # body -- written by hand, and a hand-written method
                # always wins over the generated one. What is already
                # documented is what runs.
                continue
            # A generated method carries no documentation of its own,
            # apart from `__init__`, which is written with the
            # per-parameter documentation the class already produces for
            # `help()`. Use that where it is there, and the one-line
            # description of the option everywhere else. The docstring
            # is read off the method itself rather than through
            # `inspect.getdoc`, which would answer with the one the
            # plain-Python method of that name carries -- "Return
            # repr(self)." in front of a generated `__repr__`.
            own_doc = inspect.cleandoc(method.__doc__ or "")
            _add_method(
                cls,
                name,
                method,
                own_doc or _GENERATED_DOC.get(option, ""),
                fields if option == "init" else {},
            )
        _add_field_table(cls, fields)
