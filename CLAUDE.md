# CLAUDE.md — bagof-magic

Repo-specific guidance for coding agents. bagofseeds publishes two families of
packages — standalone **`bagof-*`** packages (this repo is one) and the
**`fiery-*`** namespace matches; they share the same packaging, CI, docs, and
workflow conventions. For those shared conventions see the org guide
(`bagofseeds/.github`, `CONTRIBUTING.md` + `CLAUDE.md`). This file records only
what is specific to `bagof.magic`.

## What this package is

A `dataclass`-like base class whose behaviour is driven by **type hints**.
`Magic` generates `__init__`, `__repr__`, `__eq__` and the rest, the way
`dataclasses` does, with three differences that shape everything else:

- **Options are class keyword arguments, and they are inherited.**
  `class Point(Magic, frozen=True)` rather than `@dataclass(frozen=True)`, and
  a subclass keeps its base's options unless it overrides them. (An equivalent
  `@magic(...)` decorator exists, but the class form is the primary one.)
- **Per-field behaviour lives in the annotation**, not in a `field()` call:
  `x: ConvertTo[int]`, `y: Annotated[str, Field(alias="why")]`.
- **Conversion, validation and default construction are resolved from the
  hint** through the sibling bags — `bagof-converters`, `bagof-validators`,
  `bagof-factories` — via the thin adapters in `_resolve.py`.

## Layout

```
src/bagof/magic/
  __init__.py   # re-exports, and nothing else -- the package's public face
  _api.py       # the functions you call on a class or an instance: fields()
  _magic.py     # the builder: MetaMagic, Magic, the `magic` decorator, and
                #   every `_make_*` method generator
  _arguments.py # Arguments -- what the init hooks are handed
  _fields.py    # Field, and the annotation family (Default, Factory,
                #   ConvertTo, Validate, Init, KwOnly, ClassVar, Doc, ...)
  _options.py   # Options -- the resolved per-class option set
  _constants.py # sentinels (MISSING, REQUIRED, SHOW_ATTR) and the
                #   `__magic_*__` attribute names
  _utils.py     # SlotsBase, rebuild_cls, the `slots` decorator
  _resolve.py   # adapters to bagof-converters / -validators / -factories,
                #   and the deferred resolution of a hint that is still
                #   a name when the class is built
  _generics.py  # what a base's type parameters stand for, and filling
                #   them in on the hints that mention them
  _errors.py    # field_error -- names the class and the field when a
                #   converter, a validator or a factory raises
tests/
  test_magic.py                 # the builder, option by option
  test_docstrings.py            # every `pycon` block in a docstring or page
  test_options_are_documented.py  # every option is written down everywhere
  test_licensing.py             # the license files reach the wheel
  test_import.py
```

**Every module is private, and `__init__.py` holds no code.** A name a user
should reach is re-exported there and listed in `__all__`; everything else is
free to move. Two reasons it is worth keeping that way: griffe builds its
API-reference model from dotted paths, so a public function and a module of
the same name collide (which is why `fields.py` became `_fields.py` — the
`fields()` function owns `bagof.magic.fields`); and the builder was a
1759-line module that was also the package, which made "where does this
live?" unanswerable.

Tests that exercise internals import them from the module that defines them
(`import bagof.magic._magic as m`), not from the package.

## How the class building works

- **`MetaMagic.__new__` calls `__pre_new__` before the class exists.** It reads
  the annotations out of the raw namespace, builds a `Field` for each, resolves
  the class `Options`, and writes the generated methods straight into the
  namespace. So the class object is complete the moment it is created — nothing
  is bolted on afterwards.
- **`__post_new__` runs after**, for the two methods that need to reference the
  class itself (`__setattr__` / `__delattr__`, which close over it).
- **Generated methods are written with `namespace.setdefault`**, so a
  hand-written method in the class body always wins.
- **`_FuncBuilder` compiles `__init__`** from generated source text, because a
  real signature (defaults, positional-only markers, keyword-only markers) can
  only be produced by `exec`. Everything else is a closure.
- **Every call to a converter, a validator or a factory is guarded**, in the
  generated `__init__` and in `__setattr__` alike, and its failure goes
  through `field_error` in `_errors.py` — which raises the same error again
  (same class, so an existing `except` still catches) with the class, the
  field and the value in front of the original text, and the original as its
  cause. The guard is per call rather than one around the whole body: a
  single one could only name the field by guessing which call raised, and a
  `try` costs nothing while nothing fails.
- **Options are inherited by merging down the MRO** (`Options.update` per base,
  in reverse MRO order), so a derived class only overrides what it states.

### Reading annotations

`_namespace_annotations` has two paths and both matter:

- **Python ≤ 3.13** — the namespace carries `__annotations__` directly.
- **Python 3.14+ (PEP 649/749)** — annotations are lazy; the namespace carries
  an `__annotate__` function instead, retrieved through `annotationlib` and
  called with `Format.FORWARDREF` so an undefined name becomes a `ForwardRef`
  rather than raising during class creation.

CI runs both, so a change here needs testing on both. Coverage of one branch
will look "dead" on the other — that is expected, not a gap.

Whichever path they came from, annotations that are **text** are read back
by `_resolve_string_annotations`. A module with `from __future__ import
annotations` (and any single quoted annotation elsewhere) hands over strings,
and a string hides the entire annotation family — `ClassVar`, `KwOnly`,
`Frozen`, an `alias` inside `Annotated`, all of it — because there is no
`Annotated` metadata to find.

The text is **parsed, not executed**. `ast` splits an annotation into the
marker in front of the brackets and what is inside them, and the two are
recovered independently:

- the **marker** is a plain (possibly dotted) name, looked up by name in the
  defining module and the builtins — never called, never searched for in the
  half-built class body. It counts as structural when it is `ClassVar`,
  `Annotated`, or a member of the family in `_fields.py`.
- the **type** inside the brackets is evaluated only when it is made of the
  nodes a type can be made of (`_TYPE_NODES`: names, attributes, subscripts,
  unions, literals) — so a call in an annotation is never run — and only
  against the defining module. When it cannot be evaluated, it is carried by
  name in a `ForwardRef` and the marker still applies.
- **metadata** (`Annotated[int, Field(alias="n")]`, `Doc[int, "..."]`) may
  hold a call, but only to a member of the family, and a lambda's body is
  never looked into because it is not run.

Three rules come out of that, and each of them fixed a real failure:

1. **The structure is recovered separately from the type.** A type imported
   under `if TYPE_CHECKING:` is the single commonest reason to write the
   future import; `KwOnly[registry.Port]` must stay keyword-only even though
   `registry` is not there at runtime. An earlier version evaluated the whole
   annotation and dropped all of it when any part failed, which lost the
   family for exactly the modules that need it most.
2. **Nothing is looked up in the class body.** Merging the namespace being
   built into the lookup scope let a method shadow the type it is named
   after: in a class with `def dict(self)`, the field `payload: dict` took
   the method as its type.
3. **A payload is never evaluated unless it is safe to.** `list[str]` and
   `int | None` raise when evaluated on Python 3.8 and 3.9 — the spellings
   the future import exists to allow — so they fall back to being carried by
   name, with the marker intact.

When a marker is recognised by name but cannot be applied, a
`_UnreadableAnnotation` warning names the class, the field and the part that
could not be read. A type that is simply unavailable says nothing: there is
no structure to lose. `_doc_type` renders a type carried by name as that
name, so generated documentation shows `parent : Node`.

Only the structure is recovered eagerly, because it decides the generated
`__init__`, which is compiled once.

`tests/test_annotations_as_strings.py` is the regression suite, and its
future import is what makes it one — `tests/test_magic.py` cannot see any of
this, since annotations there are already objects. The two quoted-annotation
tests at the end of `test_magic.py` depend on that file *not* having the
future import.

### Hints that are still names when the class is built

The other half of #13 is the converter, validator and factory a field
resolves from its type. A hint that is still a `ForwardRef` or a string
gives each of them something that fails on every value, so `_resolve.py`
hands back a `_Deferred` instead: it evaluates the text the first time
the field is *used*, builds the real converter/validator/factory there,
caches it and delegates from then on. By first use the module has
finished executing, so a class that names itself and a name written
further down the file both simply resolve.

Three things make that work, and each is load-bearing:

- **The deferred callable is installed once, at build time.** `_make_init`
  snapshots `field.converter` into the generated `__init__`'s locals,
  while `__setattr__` reads it live on every call. Resolving later and
  writing the answer back onto the `Field` would fix one path and leave
  the other holding the old callable; doing the resolving *inside* the
  installed object keeps both paths on the same one.
- **`Hints` says where to look.** It holds the defining module's globals,
  plus a namespace that `__post_new__` puts the class itself into under
  its own name -- which is what lets a class written inside a function
  (every class in the test suite) refer to itself.
- **Whatever `_settle` works out is kept**, success or failure alike. A
  hint that never resolves is therefore reported once for the field and
  not once per call: a deferred converter on a hot constructor that said
  so every time would be both a performance bug and a log flood, and
  would end up suppressed wholesale.

The `unresolved_hints` option chooses the report -- `"warn"` (the
default) says so once and carries on, `"raise"` makes it a `NameError`,
`"ignore"` says nothing. The per-resolver asymmetry is deliberate and
lives in `_Kind.fallback`: a value can be passed through unconverted and
unvalidated, but nothing can be invented in place of a default that
cannot be built, so a factory raises whatever the option says.

Evaluating the text later does not reopen the "an annotation is never
called" rule. `_readable` refuses text with a call in it, so `x:
_record()` is reported rather than run at first use, exactly as it is at
class creation.

### Filling in a base's type parameters

`class IntBox(Box[int])` says that `Box`'s `T` stands for `int` here, so
the inherited field `item: T` has to become `item: int` -- otherwise both
resolvers get a bare `TypeVar` to work from, let every value through, and
a class that asked for `validate=True` checks nothing.

Two things make that work, and neither takes a hint apart by hand:

- **What each base fills in is read off `__orig_bases__`**, the bases as
  they were written, which is the same attribute `_mro` needs and the only
  place `Box[int]` survives -- by the time the metaclass runs, the bases
  themselves are plain `Box`. `type_arguments` zips a base's
  `__parameters__` against `tx.get_args` of the alias, and keys the answer
  by the base, so two parameterised bases fill in their own variables and
  not each other's.
- **The substitution itself is `typing`'s.** A hint that mentions a type
  variable lists it in `__parameters__` and can be subscripted to fill it
  in -- `List[T][int]` is `List[int]` -- which is exactly what writing
  `Box[int]` does. Going through that rather than walking the hint and
  rebuilding it keeps every shape working the same way on 3.8 through
  3.13: nested (`Dict[str, T]`), carrying metadata (`Annotated[T,
  Field(alias="why")]`, whose metadata survives), a callable signature,
  and a base that fills one parameter of two. The two spellings a walk
  would need -- `copy_with` and `__args__` -- disagree with `get_args`
  about `Callable` and about `Annotated`, and differ by version; this one
  does not exist in two forms.

A generic class named on its own (a bare `Box` as a field's type) lists
its parameters too, and is deliberately **not** filled in: it stands for
`Box` with anything in it. That is why `substitute` also asks for an
origin before doing anything.

Which of a field's converter, validator and factory came from its type is
recorded on the field as `derived` when `setdefault` resolves them, and
`Field._rebuild` builds those again from the new type. One that was handed
over ready made (`ConvertTo(some_callable)`) is not in `derived` and is
left exactly as it is: filling in a type variable says nothing about it.
The snapshot holds the *names* of the three, not the type they came from,
so there is no second copy of the type to keep in step with the first.

Out of scope, and said so in `README.md` and `docs/comparison.md`:
`Box[int]("1")`. That is a `typing` alias rather than a class, so there is
no class being built and nowhere to hang a filled-in field table;
catching it means intercepting `__call__` on the alias.

## Conventions specific to this repo (do not regress)

1. **Wide Python (3.8+).** Runtime code must stay old-compatible: no walrus in
   runtime paths that 3.8 would reject, no PEP 604 `|` or PEP 585 `list[...]`
   in *values*, and never subscript an abc/builtin generic at runtime. Modern
   typing lives in **annotations only** — every module starts with
   `from __future__ import annotations`, so they are lazy strings.
2. **All typing goes through `import typing_extensions as tx`.** `tx.Union`,
   `tx.Sequence`, `tx.Self`, … — do not import from `typing` or
   `collections.abc`. This matches the bagof-hints house style.
3. **Attribute names are namespaced.** Anything stored on a user's class is
   `__magic_*__` and is defined in `_constants.py` — never a bare string
   literal at the point of use.
4. **`Field` slots are declared through the `slots` decorator**, not a plain
   `__slots__`, so `SlotsBase`'s `_slots()` walk sees them. A new slot must be
   added to the `@slots(...)` list *and* documented in `Field.__init__`'s
   numpydoc block, which is what the API reference renders.
5. **Never leak an internal name into a user-facing error.** The generated
   source uses `__magic_<field>_type__` and friends; an error message must
   name the *field*, not the local.
6. **A new class option has to be registered in six places.** The `@slots`
   list and `_DEFAULTS` in `_options.py`, the option list written out three
   times — the module docstring at the top of `_magic.py`, and the
   `MetaMagic` and `Magic` docstrings — and the settings table in
   `README.md`. `tests/test_options_are_documented.py` checks all six, so a
   missing one is a test failure rather than a doc page that quietly
   disagrees with the code. The comparison table in `docs/comparison.md` is
   not one row per option and is not checked; update it by hand when a new
   option is worth comparing. `MetaMagic.__doc__` and `Magic.__doc__` are
   passed through `str.format`, so a `{` in one of them is read as a
   placeholder: spell an option's accepted values in prose, not in
   numpydoc's `{"a", "b"}` notation.

## Documentation style (`README.md`, `docs/*.md`, public docstrings)

Docs are for **humans who are not necessarily experts in arcane Python
features**. They want to know how to use `magic` well — to write correct,
readable, efficient code. Apply this to every hand-written page and to every
public docstring:

1. **Show the sugar first.** When several spellings do the same thing, lead
   with the nicest one and list the rest in `=== "..."` tabs.
2. **Plain language.** No agentic or internal-monologue phrasing, and no
   unexplained internal names — those belong in code comments and in this
   file, not in the docs. Say what a reader needs in order to *use* the
   library, not what the builder does internally.
3. **Real `pycon`, not pseudo-code.** An example that shows a value must show
   the value the interpreter actually prints. For the annotation family in
   `_fields.py` this means showing the lowering as it really is:

   ```pycon
   >>> Factory[list]
   typing.Annotated[list, Factory(factory=True)]
   ```

   not an invented `~>` arrow. Every such block should be copy-pasteable and
   true.
4. **An example must run on the oldest supported Python.** `tests/
   test_docstrings.py` executes every `pycon` block, and CI runs it on 3.8 as
   well as current. The usual trap is `typing`: `Annotated` only exists from
   3.9. Prefer the package's own sugar (`Doc[int, "..."]`, `Frozen[int]`) in
   examples, which works everywhere and is what the docs should be showing
   anyway.
5. **Leanness bar.** If an example does not read as short and natural, that is
   a signal: either a nicer spelling already exists and the example should use
   it, or `magic` is missing sugar — file an `enhancement` issue for the gap
   rather than shipping an awkward example.

**This applies equally to every public docstring** (anything without a leading
underscore, reachable from `bagof.magic`) — the API reference renders them
directly through `mkdocstrings`, so a docstring *is* a doc page. Concretely, a
public docstring must **not**:

- reference an issue or PR number, or a review finding — that belongs in a
  commit message, a code comment, or this file;
- name an internal mechanism the reader has no reason to know about (which
  helper resolves it, which private attribute holds it);
- read like a note to a fellow contributor ("kept for symmetry with X", "this
  used to be broken") — say what the reader needs, not how it got that way.

Internal rationale and history still belong somewhere — just not in a public
docstring. Use a code comment near the implementation, or a section of this
file.

### Code comments, private docstrings and error messages

Same standard, different reader. The audience here is a contributor opening
the file for the first time, with no background on how the builder works —
not you, later, remembering why you did it.

1. **Say what the code does, not what you decided.** "Replace any inherited
   generated method for this option" is useful. "Rather than try to tell them
   apart, we now raise" is a changelog entry; put that in the commit message.
2. **Name a helper for what it actually does**, not for the shape of what it
   returns. `_defines` sounded like a predicate and returned a class;
   `_defining_class` says it.
3. **An error message is read by someone stuck**, not by whoever wrote the
   check. It must name what happened, in the reader's vocabulary, and what to
   write instead. Never mention metaclasses, namespaces, rebuilding, or any
   private helper — a user has no reason to know those exist, and naming them
   makes a fixable mistake feel like a library bug. Compare:

   > `Chord has already been built by Magic, so it cannot be rebuilt: pass
   > the options to the class statement instead`

   with what it became:

   > `Chord is already a Magic class, so it cannot be built a second time.
   > This happens when @magic is used twice on the same class, or when it is
   > used on a class that already inherits from Magic. Put the options on the
   > class statement instead — `class Chord(Magic, frozen=True)` — which does
   > the same job.`

4. **Don't reference an internal name a user could not have typed.** The
   `slots` helper in `_utils.py` is ours; an error that mentions it sends the
   reader looking for something they never used.

## Third-party code

Parts of the builder are copied from or derived from CPython's `dataclasses`.
They carry the PSF license: see `LICENSE-PSF-2.0.txt` and `NOTICE.md`. **If
you port more code from the standard library, add it to `NOTICE.md`'s
component table and to its summary of changes** — the license requires both,
and an attribution comment alone does not satisfy it.

Every license file must stay **at the repository root** and be listed in
`pyproject.toml`'s `license-files`. A subdirectory pattern there is accepted
by the config and then silently ignored by every setuptools before 77, so the
file never reaches the wheel and the build says nothing.
`tests/test_licensing.py` enforces both.

## Gate before a PR

```sh
pip install .[test]
cd /tmp && python -m pytest <repo>/tests -q     # run from a neutral cwd
ruff check src tests
codespell src tests
```

**Run the tests on more than one Python before pushing** if you touched
anything version-sensitive — the `ast` module, `typing` internals,
`inspect`, or how annotations are read. CI covers 3.8 and current, and
those are the two ends where things differ; a change that passes on one
interpreter can fail to *import* on another. `ast.Ellipsis` disappearing
in 3.14 took out every test in the suite at collection time, and no
amount of local testing on a single version would have shown it.

Whatever interpreters are to hand will do, pointed at the sources
directly rather than at an install:

```sh
cd /tmp && PYTHONPATH=<repo>/src:<each sibling>/src:<site-packages> \
    python3.13 -m pytest <repo>/tests -q
```

## Known follow-ups (see the tracking issues)

- **Correctness**: fields shared and mutated across classes (#14); a
  disabled option falling through to `Magic`'s own generated method
  (#23).
- **Model**: naming the field kind instead of inferring it from `init` (#16),
  which also carries the declared/resolved split that makes option inheritance
  work (#20).
- **Features**: parity helpers — `replace`, `asdict`, `astuple` (#22);
  polymorphic construction (#21).
