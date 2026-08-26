---
icon: fontawesome/solid/scale-balanced
---

# How it compares

Four libraries solve overlapping problems. The choice depends on what you
want the type hints to do.

- **[dataclasses][]** is in the standard library. It generates `__init__`,
  `__repr__`, `__eq__`. It reads your hints but never acts on them.
- **[attrs][]** does the same, with more control, and adds converters and
  validators you write yourself.
- **[pydantic][]** reads the hints and acts on them: parsing, coercing and
  rejecting values. This is why it dominates web and config code.
- **`magic`** sits with attrs on API design and with pydantic on hints.
  Nothing is added to your class unless you ask for it. When you do ask,
  the type hint drives it.

## At a glance

|  | dataclasses | attrs | pydantic | magic |
| --- | --- | --- | --- | --- |
| **How you opt in** | decorator | decorator | base class | **base class or decorator** |
| Settings inherited by subclasses | no | no | yes | **yes** |
| Per-field behaviour written in the annotation | no | no | partly | **yes** |
| Adds public methods to your class | no | no | yes | **only if asked** |
| | | | | |
| **Values** | | | | |
| Conversion from the type hint | no | no | yes | **yes** |
| Conversion from your own callable | no | yes | yes | **yes** |
| Validation from the type hint | no | no | yes | **yes** |
| Validation from your own callable | no | yes | yes | **yes** |
| Defaults converted and validated | no | yes | opt-in | **yes, or opt out** |
| Defaults built by a factory | yes | yes | yes | **yes** |
| Mutable defaults caught | raises | raises | copies | **copies, or raises** |
| | | | | |
| **Generated methods** | | | | |
| `__init__` / `__repr__` / `__eq__` | yes | yes | yes | **yes** |
| Full set of ordering methods | yes | yes | no | **yes** |
| `__slots__` | yes | yes | no | **yes** |
| Keyword-only and positional-only fields | keyword only | keyword only | keyword only | **both** |
| Rename a generated method | no | no | no | **yes** |
| Dict-like instances | no | no | partly | **yes** |
| Docstring built from the fields | no | no | no | **yes** |
| | | | | |
| **Around the edges** | | | | |
| Copy with changes | `replace` | `evolve` | `model_copy` | **`replace`** |
| Convert to a plain `dict` | `asdict` | `asdict` | `model_dump` | **`asdict`** |
| JSON schema | no | no | yes | no |
| Generic classes | yes | yes | yes | **yes**, *[named subclass only][generics]* |
| Runtime dependency | none | `attrs` | `pydantic-core` (compiled) | the `bagof` packages |

## The same class, four ways

=== "magic"

    ```python
    from bagof.magic import Magic, Factory

    class User(Magic, frozen=True, convert=True):
        name: str
        age: int
        tags: Factory[list]
    ```

=== "dataclasses"

    ```python
    from dataclasses import dataclass, field

    @dataclass(frozen=True)
    class User:
        name: str
        age: int
        tags: list = field(default_factory=list)
        # nothing converts "36" to 36
    ```

=== "attrs"

    ```python
    from attrs import define, field

    @define(frozen=True)
    class User:
        name: str
        age: int = field(converter=int)   # one field at a time
        tags: list = field(factory=list)
    ```

=== "pydantic"

    ```python
    from pydantic import BaseModel, Field

    class User(BaseModel, frozen=True):
        name: str
        age: int
        tags: list = Field(default_factory=list)
    ```

## Where each one fits best

### dataclasses

Use it when you want no dependency and only need the basics. It is in the
standard library, everyone recognises it, and every tool supports it. If
your data is already the right type by the time it reaches you, the other
three have nothing to add.

### attrs

Use it when you want the basics done well, with full control and no
surprises. It is older and more battle-tested than either of the others,
has no heavy runtime dependency, and its validator library is excellent.
`magic` follows its design lead. If you like attrs and want the type hints
to do more of the work, `magic` should feel familiar.

### pydantic

Use it when you are parsing untrusted input at a boundary, and you need
JSON schema, serialisation, and a large ecosystem of integrations. Nothing
here competes with that. It also means your model class gains a large
public API you did not write. That is fine at a boundary and less fine for
a domain object.

### magic

Use it when you want the hints to drive conversion and validation, but you
want a plain class at the end of it. One where the only methods are the
ones you wrote and the ones you asked for.

## Things magic does that the others do not

### Settings are inherited

Every other library re-applies its decorator per class. `magic` merges
settings down the inheritance chain. A base class sets the house style once:

```python
from bagof.magic import Magic

class Record(Magic, frozen=True, kw_only=True, convert=True):
    """Every record is immutable, keyword-built and type-coerced."""

class User(Record):
    name: str
    age: int
```

```pycon
>>> User(name="ada", age="36")
User(name='ada', age=36)
```

A subclass that changes a setting changes it for the fields it declares
itself. Add `override=True` and it changes inherited fields too. A field
that asked for something in its own annotation always wins.

### Per-field behaviour is part of the annotation

The others put it in a `field()` call on the right-hand side. That pushes
the default out of the way and reads oddly once you use more than one:

=== "magic"

    ```python
    from bagof.magic import Magic, ConvertTo, KwOnly, NoRepr

    class Session(Magic):
        user: str
        retries: ConvertTo[int] = 0
        token: NoRepr[str] = ""
        debug: KwOnly[bool] = False
    ```

=== "attrs"

    ```python
    from attrs import define, field

    @define
    class Session:
        user: str
        retries: int = field(default=0, converter=int)
        token: str = field(default="", repr=False)
        debug: bool = field(default=False, kw_only=True)
    ```

### Instances can behave like dictionaries

Useful for anything that is conceptually a record: a config section, a row,
a header block:

```python
from bagof.magic import Magic

class Header(Magic, mapping=True):
    content_type: str
    length: int
```

```pycon
>>> dict(Header("text/plain", 12))
{'content_type': 'text/plain', 'length': 12}
```

A key is present while its field holds a value. A field that is only filled
in later stays out of the view until it is.

### The docstring writes itself

```python
from bagof.magic import Magic, Doc

class Retry(Magic):
    """Retry policy."""

    times: Doc[int, "how many times to try again"] = 3
```

```pycon
>>> print(Retry.__doc__)
Retry policy.
<BLANKLINE>
Attributes
----------
times : int, default=3
    how many times to try again
<BLANKLINE>
<BLANKLINE>
```

## Things the others do that magic does not

- **JSON schema and serialisation.** Pydantic's strongest feature. `magic`
  has neither yet.
- **Deep-copying leaves.** `dataclasses.asdict` deep-copies every non-dataclass
  value; `magic`'s `asdict` returns non-Magic values as-is. This is deliberate:
  a field holding a NumPy array or a large object should not be silently copied.
- **A type parameter filled in at the call site.** A subclass fills one in:
  `class IntBox(Box[int])` gives `item` the type `int`, and converts and
  validates against it. But `Box[int]("1")` does not: that is a `typing`
  alias, not a class, so it builds a plain `Box` whose `item` is still `T`.
  [Tracked here][generics]. Pydantic fills that one in too. `dataclasses`
  and `attrs` fill in neither.
- **Editor and type-checker support.** The others are understood by mypy and
  pyright today, so your editor completes the constructor and catches wrong
  argument types. `magic` is not, yet ([tracked here][typing]). The route
  is the same standard the others use, so most of it should follow. The
  part that will not is a field written purely as an annotation
  (`tags: Factory[list]`), which a checker cannot see a default for.

[dataclasses]: https://docs.python.org/3/library/dataclasses.html
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[generics]: https://github.com/bagofseeds/bagof-magic/issues/50
[typing]: https://github.com/bagofseeds/bagof-magic/issues/30
