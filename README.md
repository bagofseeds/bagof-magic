# bagof-magic

**Classes that build themselves from your type hints.**

Fields are written as annotations, and `Magic` generates `__init__`,
`__repr__`, `__eq__` and the other methods from them.

```python
from bagof.magic import Magic

class Point(Magic, frozen=True):
    x: float
    y: float
```

```pycon
>>> Point(1.0, 2.0)
Point(x=1.0, y=2.0)
>>> Point(1.0, 2.0) == Point(1.0, 2.0)
True
>>> Point(1.0, 2.0).x = 3.0
Traceback (most recent call last):
AttributeError: Cannot set frozen field 'x'
```

The same class can also be written with the `magic` decorator:

=== "Base class"

    ```python
    from bagof.magic import Magic

    class Point(Magic, frozen=True):
        x: float
        y: float
    ```

=== "Decorator"

    ```python
    from bagof.magic import magic

    @magic(frozen=True)
    class Point:
        x: float
        y: float
    ```

## What sets it apart

- **Settings are class keyword arguments, and subclasses inherit them.** A
  base class sets `frozen=True` once, every subclass keeps it, and a
  subclass overrides only the settings it needs to change. See
  [Settings][settings].
- **Per-field behaviour lives in the annotation**, not in a `field()` call:
  `tags: Factory[list]`, `token: NoRepr[str] = ""`. See
  [Field annotations][fields].
- **Conversion and validation come from the type hint**, and are turned on
  per class or per field. `Config("localhost", "9000")` stores `port=9000`
  because the hint says `int`. See [Conversion and validation][conversion].
- **A class can build one of its own subclasses**, chosen from the
  arguments it is called with. See [Building the right subclass][polymorphic].
- **A field can accept several input names**, and can be read through
  forwarding properties under other names. See
  [Input aliases and forwarding properties][aliases].
- **A required field can follow one with a default**, so a subclass can
  add a required field to a base whose fields all have defaults. See
  [Field annotations][fields].
- **A subclass can forget a field it inherits** by writing `x: Forget`,
  which frees the name for a field of its own. See [Field annotations][fields].
- **A subclass can change part of an inherited field** and keep the rest:
  `x: ... = Inherit(frozen=True)` freezes the inherited `x` without losing
  its default or its aliases, and `_x: ... = Inherit("x")` stores the
  inherited `x` under a private name while it is still read and passed as
  `x`. See [Field annotations][fields].
- The [Extras][extras] page covers the rest: dict-like instances,
  `replace`, `asdict` and `astuple`, mutable defaults that are not shared,
  hooks around construction, generic classes, and docstrings generated
  from the fields.

## How it compares

`magic` is close to [attrs][attrs] in spirit. Like [pydantic][pydantic], it
does real work with the type hints, and like pydantic it uses inheritance
where dataclasses and attrs use decorators.

|  | dataclasses | attrs | pydantic | magic |
| --- | --- | --- | --- | --- |
| settings inherited by subclasses | no | no | yes | **yes** |
| per-field behaviour in the annotation | no | no | partly | **yes** |
| conversion from the type hint | no | partly | yes | **yes** |
| validation from the type hint | no | partly | yes | **yes** |
| dict-like instances | no | no | partly | **yes** |
| no methods added unless asked | yes | yes | no | **yes** |

The [comparison page][comparison] sets the four side by side in more detail.

## Settings

<!-- --8<-- [start:settings] -->
```python
class Thing(Magic, frozen=True, kw_only=True, slots=True):
    ...
```

| Setting | Default | What it does |
| --- | --- | --- |
| `init` | `True` | generate `__init__` |
| `repr` | `True` | generate `__repr__`; a test such as `HideIfNone()` applies to every field |
| `eq` | `True` | generate `__eq__` |
| `order` | `False` | generate the comparisons |
| `hash` | `None` | generate `__hash__`; decides for itself by default |
| `unsafe_hash` | `False` | generate one even when the class is mutable |
| `frozen` | `False` | refuse assignment after construction |
| `match_args` | `False` | support structural pattern matching |
| `kw_only` | `False` | every field must be passed by name |
| `positional_only` | `False` | every field must be passed by position |
| `slots` | `False` | use `__slots__`, and drop `__dict__` |
| `weakref_slot` | `False` | allow weak references under `slots` |
| `convert` | `False` | convert every field from its type |
| `validate` | `False` | check every field against its type |
| `convert_defaults` | `True` | convert a value that came from a default, too |
| `validate_defaults` | `True` | check a value that came from a default, too |
| `unresolved_hints` | `"warn"` | what to do when a type hint still names something undefined the first time a field needs it; or `"raise"`, or `"ignore"` |
| `factory` | `False` | build every missing default from its type |
| `mutable_default` | `"factory"` | give each instance its own copy of `x: list = []`; or `"raise"`, or `"allow"` |
| `alias` | default public name | input names; `True` includes enabled property names, `False` keeps underscores |
| `property` | `False` | forwarding attributes; `True` or `"readonly"` exposes the public name, `"all"` every input alias |
| `mapping` | `False` | behave like a dictionary; a subclass inherits the methods and cannot turn them off |
| `override` | `False` | apply this class's settings to inherited fields too |
| `polymorphic` | `False` | build one of this class's subclasses, chosen from the arguments; or `"strict"`, which refuses to build this class when none of them matches |
| `pin_discriminant` | `"pin"` | what a subclass does with the field it matches on; also `"classvar"`, `"keep"`, or any of those with `+narrow` (and `"narrow"` = `"pin+narrow"`) to narrow its type and reject other values; a field's own `Pin[T, mode]` wins over it |
| `reverse` | `False` | list a subclass's own fields before inherited ones |
| `doc` | `True` | add the field table to the class docstring |

Most of the settings that generate a method also accept a string in place
of `True`. The generated method is then bound under that name, so that a
hand-written method can call it.
<!-- --8<-- [end:settings] -->

The [Settings][settings] page explains how settings are inherited and how a
subclass overrides them.

## Install

```sh
pip install git+https://github.com/bagofseeds/bagof-magic.git
```

Python 3.8 and later.

## Status

The package is at an early stage. The API is still settling, and parts of it
may change. Issues and ideas are welcome at [bagofseeds/bagof-magic][issues].

[settings]: https://bagofseeds.github.io/bagof-magic/intro/settings/
[fields]: https://bagofseeds.github.io/bagof-magic/intro/fields/
[conversion]: https://bagofseeds.github.io/bagof-magic/intro/conversion/
[polymorphic]: https://bagofseeds.github.io/bagof-magic/intro/polymorphism/
[aliases]: https://bagofseeds.github.io/bagof-magic/intro/aliases/
[extras]: https://bagofseeds.github.io/bagof-magic/intro/extras/
[converters]: https://bagofseeds.github.io/bagof-converters/
[validators]: https://bagofseeds.github.io/bagof-validators/
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[comparison]: https://bagofseeds.github.io/bagof-magic/comparison/
[issues]: https://github.com/bagofseeds/bagof-magic/issues
