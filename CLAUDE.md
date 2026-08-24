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
  __init__.py   # the builder: MetaMagic, Magic, the `magic` decorator, the
                #   module-level `fields()` helper, and every `_make_*` method
                #   generator
  _fields.py    # Field, and the annotation family (Default, Factory,
                #   ConvertTo, Validate, Init, KwOnly, ClassVar, Doc, ...) --
                #   named with a leading underscore so the module doesn't
                #   shadow the top-level `fields()` function at the dotted
                #   path `bagof.magic.fields` in griffe's API-reference model
  options.py    # Options -- the resolved per-class option set
  constants.py  # sentinels (MISSING, REQUIRED, SHOW_ATTR) and the
                #   `__magic_*__` attribute names
  utils.py      # SlotsBase, rebuild_cls, the `slots` decorator
  _resolve.py   # adapters to bagof-converters / -validators / -factories
tests/
  test_magic.py
  test_import.py
```

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
   `__magic_*__` and is defined in `constants.py` — never a bare string
   literal at the point of use.
4. **`Field` slots are declared through the `slots` decorator**, not a plain
   `__slots__`, so `SlotsBase`'s `_slots()` walk sees them. A new slot must be
   added to the `@slots(...)` list *and* documented in `Field.__init__`'s
   numpydoc block, which is what the API reference renders.
5. **Never leak an internal name into a user-facing error.** The generated
   source uses `__magic_<field>_type__` and friends; an error message must
   name the *field*, not the local.
6. **A new class option has to be registered in six places.** The `@slots`
   list and `_DEFAULTS` in `options.py`, and then the option list written out
   three times in `__init__.py` — the module docstring, `_DOC_OPTIONS`, and
   the `MetaMagic` and `Magic` docstrings — plus the settings table in
   `README.md` and the comparison table in `docs/comparison.md`. Grep for an
   existing option name to find them all. `MetaMagic.__doc__` and
   `Magic.__doc__` are passed through `str.format`, so a `{` in one of them
   is read as a placeholder: spell an option's accepted values in prose, not
   in numpydoc's `{"a", "b"}` notation.

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
   `slots` helper in `utils.py` is ours; an error that mentions it sends the
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

## Known follow-ups (see the tracking issues)

- **Correctness**: unresolved string/forward annotations breaking
  `convert`/`validate`/`factory` (#13); fields shared and mutated across
  classes (#14); `slots=True` with defaults (#15); `order` missing three
  dunders (#17); generic classes (#18); a disabled option falling through to
  `Magic`'s own generated method (#23).
- **Model**: naming the field kind instead of inferring it from `init` (#16),
  which also carries the declared/resolved split that makes option inheritance
  work (#20).
- **Features**: parity helpers — `replace`, `asdict`, `astuple` (#22);
  polymorphic construction (#21).
