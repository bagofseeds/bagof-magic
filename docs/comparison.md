---
icon: fontawesome/solid/scale-balanced
---

# How it compares

Four libraries solve overlapping problems, and picking between them is mostly a
question of what you want the type hints to *do*.

- **[dataclasses][]** is in the standard library and does the boring part:
  `__init__`, `__repr__`, `__eq__`. It reads your hints but never acts on them.
- **[attrs][]** does the same, better and with more control, and adds
  converters and validators you write yourself.
- **[pydantic][]** reads the hints and *acts* on them — parsing, coercing and
  rejecting values — which is why it is everywhere in web and config code.
- **`magic`** sits with attrs on API design and with pydantic on hints: nothing
  is added to your class unless you ask for it, but when you do ask, the type
  hint is what drives it.

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
| Convert to a plain `dict` | `asdict` | `asdict` | `model_dump` | **`asdict`**, *without recursing* |
| JSON schema | no | no | yes | no |
| Generic classes | yes | yes | yes | **yes**, *[without substitution][generics]* |
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

## Where each one is the better choice

### Reach for dataclasses when…

…you want no dependency at all and you only need the boring part. It is in the
standard library, everyone recognises it, and every tool understands it. If
your data is already the right type by the time it reaches you, the other three
have nothing to add.

### Reach for attrs when…

…you want the boring part done well, with full control and no surprises. It is
older and more battle-tested than either of the others, has no runtime
dependency to speak of, and its validator library is excellent. `magic` follows
its design lead — which means if you like attrs and want the type hints to do
more of the work, `magic` should feel familiar rather than foreign.

### Reach for pydantic when…

…you are parsing untrusted input at a boundary, and you want JSON schema,
serialisation, and an enormous ecosystem of integrations. Nothing here competes
with that. It also means your model class gains a large public API you did not
write, which is fine at a boundary and less fine for a domain object.

### Reach for magic when…

…you want the hints to drive conversion and validation, but you want a plain
class at the end of it — one where the only methods are the ones you wrote and
the ones you asked for.

## Things magic does that the others do not

### Settings are inherited

Every other library re-applies its decorator per class. `magic` merges settings
down the inheritance chain, so a base class sets the house style once:

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
itself. Add `override=True` and it changes for the inherited fields too —
except where a field asked for something in its own annotation, which always
wins.

### Per-field behaviour is part of the annotation

The others put it in a `field()` call on the right-hand side, which pushes the
default out of the way and reads oddly once you use more than one:

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

Useful for anything that is conceptually a record — a config section, a row, a
header block:

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

A key is there while its field is holding a value, so a field that is only
filled in later stays out of the view until it is.

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

Being honest about the gaps, with links to where they are being worked on:

- **JSON schema and serialisation.** Pydantic's real draw, and `magic` has
  neither yet.
- **A recursive `asdict`.** `asdict` hands back the values as they are
  stored, so a field holding another object gives you that object rather
  than a dict of its fields. The others walk the whole tree, copying
  lists and dicts as they go.
- **Type parameters in a generic class.** `class Box(Magic, Generic[T])`
  works, but a subclass that fills the parameter in — `class IntBox(Box[int])`
  — leaves the field's type as `T`, so conversion and validation have nothing
  to work from and let any value through. [Tracked here][generics]. Pydantic
  substitutes the parameter; `dataclasses` and `attrs` do not either.
- **Editor and type-checker support.** The others are understood by mypy and
  pyright today, so your editor completes the constructor and catches a wrong
  argument type. `magic` is not, yet — [tracked here][typing]. The route is
  the same standard the others use, so most of it should follow; the part
  that will not is a field written purely as an annotation
  (`tags: Factory[list]`), which a checker cannot see a default for.

[dataclasses]: https://docs.python.org/3/library/dataclasses.html
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[generics]: https://github.com/bagofseeds/bagof-magic/issues/50
[typing]: https://github.com/bagofseeds/bagof-magic/issues/30
