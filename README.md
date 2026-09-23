# bagof-magic

**Classes that build themselves from your type hints.**

Write your fields as annotations. `Magic` generates `__init__`, `__repr__`,
`__eq__`, and everything else.

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

If you prefer a decorator:

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

- **Settings are class keyword arguments, and subclasses inherit them.** Set
  `frozen=True` on a base once; every subclass keeps it, and can override
  just the settings it needs to change. See [Settings][settings].
- **Per-field behaviour lives in the annotation**, not in a `field()` call:
  `tags: Factory[list]`, `token: NoRepr[str] = ""`. See
  [Field annotations][fields].
- **Conversion and validation come from the type hint**, opt in per class or
  per field. `Config("localhost", "9000")` becomes `port=9000` because the
  hint says `int`. See [Conversion and validation][conversion].
- **A class can build one of its own subclasses**, chosen from the
  arguments it's called with. See [Building the right subclass][polymorphic].
- **A field can accept several input names**, and expose forwarding
  properties under other names. See
  [Input aliases and forwarding properties][aliases].
- Also included: dict-like instances, `replace`/`asdict`/`astuple`,
  mutable defaults that aren't shared, hooks around construction, generic
  classes, and docstrings generated from the fields. See [Extras][extras].

## How it compares

Close to [attrs][attrs] in spirit, with [pydantic][pydantic]'s habit of doing
real work from your type hints, and inheritance where the others use decorators.

|  | dataclasses | attrs | pydantic | magic |
| --- | --- | --- | --- | --- |
| settings inherited by subclasses | no | no | yes | **yes** |
| per-field behaviour in the annotation | no | no | partly | **yes** |
| conversion from the type hint | no | partly | yes | **yes** |
| validation from the type hint | no | partly | yes | **yes** |
| dict-like instances | no | no | partly | **yes** |
| no methods added unless asked | yes | yes | no | **yes** |

There is a fuller side-by-side in [the comparison page][comparison].

## Settings

<!-- --8<-- [start:settings] -->
```python
class Thing(Magic, frozen=True, kw_only=True, slots=True):
    ...
```

| Setting | Default | What it does |
| --- | --- | --- |
| `init` | `True` | generate `__init__` |
| `repr` | `True` | generate `__repr__` |
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
| `pin_discriminant` | `"pin"` | what a subclass does with the field it matches on; or `"classvar"`, or `"keep"` |
| `reverse` | `False` | list a subclass's own fields before inherited ones |
| `doc` | `True` | add the field table to the class docstring |

Most of them also accept a string instead of `True`, which binds the
generated method under that name. This is useful when you want to call the
generated method from your own.
<!-- --8<-- [end:settings] -->

See [Settings][settings] for how they're inherited and how to override them.

## Install

```sh
pip install git+https://github.com/bagofseeds/bagof-magic.git
```

Python 3.8 and later.

## Status

Early. The API is settling, and things may still move. Issues and ideas are
welcome at [bagofseeds/bagof-magic][issues].

[settings]: https://bagofseeds.github.io/bagof-magic/settings/
[fields]: https://bagofseeds.github.io/bagof-magic/fields/
[conversion]: https://bagofseeds.github.io/bagof-magic/conversion/
[polymorphic]: https://bagofseeds.github.io/bagof-magic/polymorphism/
[aliases]: https://bagofseeds.github.io/bagof-magic/aliases/
[extras]: https://bagofseeds.github.io/bagof-magic/extras/
[converters]: https://bagofseeds.github.io/bagof-converters/
[validators]: https://bagofseeds.github.io/bagof-validators/
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[comparison]: https://bagofseeds.github.io/bagof-magic/comparison/
[issues]: https://github.com/bagofseeds/bagof-magic/issues
