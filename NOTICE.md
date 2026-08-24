# Third-party notices

`bagof-magic` is distributed under the MIT license (see [`LICENSE`](LICENSE)).

Parts of it are copied from, or derived from, CPython's standard library
`dataclasses` module, which is licensed under the **Python Software Foundation
License Version 2**. A copy of that license, together with the PSF copyright
notice its clause 2 requires us to retain, is in
[`LICENSE-PSF-2.0.txt`](LICENSE-PSF-2.0.txt).

> Copyright (c) 2001-2026 Python Software Foundation; All Rights Reserved

Clause 3 of that license requires a brief summary of the changes made. This
file is that summary.

## Where the derived code is

Upstream source: [`Lib/dataclasses.py`](https://github.com/python/cpython/blob/main/Lib/dataclasses.py)
in CPython. Where a helper changed shape across Python versions, the version we
followed is noted.

### `src/bagof/magic/__init__.py`

| Ours | Upstream |
| --- | --- |
| `__pre_new__` | `_process_class` |
| `_add_fields` | the inherited-field collection loop inside `_process_class` |
| `_FuncBuilder` | `_FuncBuilder` (3.13+) |
| `_make_init` | `_init_fn`, `_init_param`, `_field_init` |
| `_make_repr` | `_repr_fn` (3.11) / the `__repr__` branch of `_process_class` (3.13+) |
| `_make_eq`, `_make_lt` | `_cmp_fn` (3.11) / the `__eq__` and `__lt__` branches of `_process_class` (3.13+) |
| `_make_assign` | `_frozen_get_del_attr` |
| `_make_state` | `_dataclass_getstate`, `_dataclass_setstate` |
| `_hash_set_none`, `_hash_exception`, `_hash_add`, `_hash_action` | the same names |
| `_get_slots` | `_get_slots` |
| `_make_slots` | the slot-computing half of `_add_slots` |
| the `slots` handling in `__pre_new__` | the field defaults `_add_slots` drops from the class dict |

### `src/bagof/magic/utils.py`

| Ours | Upstream |
| --- | --- |
| `_update_func_cell_for__class__` | the same name (a helper of `_add_slots`, 3.12+) |
| `rebuild_cls` | the class-rebuilding half of `_add_slots` |

### `src/bagof/magic/constants.py`

| Ours | Upstream |
| --- | --- |
| `_MissingType`, `MISSING` | `_MISSING_TYPE`, `MISSING` |
| `_HasFactory` | `_HAS_DEFAULT_FACTORY_CLASS` |
| `_FIELDS`, `_POST_INIT_NAME` | the same names |

## Summary of changes

- **A metaclass, not a decorator.** `dataclasses` processes a class after it
  exists; `bagof-magic` builds it in `MetaMagic.__new__`, so the generated
  methods are written into the namespace before the class object is created.
  `_process_class` was restructured into `__pre_new__` and `__post_new__`
  accordingly, and every `_set_new_attribute(cls, ...)` call became a
  `namespace.setdefault(...)`.
- **Options are inherited.** They are given as class keyword arguments and
  merged down the MRO into an `Options` object, rather than passed to a
  decorator per class. `_add_fields` was written for that merge; upstream has
  no equivalent, since a decorator sees only one class at a time.
- **Fields come from annotations, not from a `field()` call.** `Field` is
  configured through `Annotated` metadata, resolved by `Field.from_hint`, and
  carries options `dataclasses` has no equivalent for: `converter`,
  `validator`, `factory`, `key`, `alias`, `doc`, `kw`, `positional`.
- **Conversion and validation.** The generated `__init__` and `__setattr__`
  run a per-field converter and validator, resolved from the field's type hint
  through the sibling `bagof-converters` and `bagof-validators` packages.
- **Names are configurable.** Options accept a string as well as a boolean, so
  a generated method can be written under a name other than its dunder.
- **A dict-like protocol.** The `mapping` option generates `__getitem__`,
  `__setitem__`, `__delitem__`, `__iter__` and `__len__`, and registers the
  class as a `Mapping` or `MutableMapping`. There is no upstream equivalent.
- **Generated documentation.** The `doc` option appends an attribute table to
  the class docstring, built from each field's own documentation.
- **Version reach.** The code runs on Python 3.8 and later, so `match`
  statements were rewritten as `if`/`elif` (`_get_slots`), and annotations are
  read through `annotationlib` on 3.14+ and from the class namespace below it.
- **Per-field, rather than per-class, control** of `repr`, `eq`, `order`,
  `hash`, `frozen`, `kw_only` and `positional_only`.
- **Slots are worked out before the class exists**, so the defaults that
  cannot share a name with a slot are dropped from the namespace as the
  fields are read, rather than from the dict of a class being rebuilt.
