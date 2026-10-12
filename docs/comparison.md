---
icon: fontawesome/solid/scale-balanced
---

# How it compares

Four libraries solve overlapping problems, and the choice between them
depends mostly on what the type hints should do.

- **[dataclasses][]** is in the standard library. It generates `__init__`,
  `__repr__` and `__eq__`, and it reads the type hints but never acts on
  them.
- **[attrs][]** does the same with more control, and adds converters and
  validators that are written by hand.
- **[pydantic][]** reads the hints and acts on them by parsing, coercing and
  rejecting values, which is why it dominates web and configuration code.
- **`magic`** follows attrs in its API design and pydantic in its use of
  the hints. Nothing is added to a class unless the class asks for it, and
  whatever it asks for is driven by the type hint.

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
| Required field after a defaulted one | refused | refused | keyword only | **yes** |
| Remove an inherited field | no | no | no | **yes** |
| Change part of an inherited field | no | no | no | **yes** |
| Store an inherited field under another name | no | no | no | **yes** |
| Rename a generated method | no | no | no | **yes** |
| Dict-like instances | no | no | partly | **yes** |
| Docstring built from the fields | no | no | no | **yes** |
| | | | | |
| **Around the edges** | | | | |
| Copy with changes | `replace` | `evolve` | `model_copy` | **`replace`** |
| Convert to a plain `dict` | `asdict` | `asdict` | `model_dump` | **`asdict`** |
| JSON schema | no | no | yes | no |
| Generic classes | yes | yes | yes | **yes** |
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

Use it when the basics are enough and no dependency is wanted. It is in the
standard library, everyone recognises it, and every tool supports it. When
the data already has the right types by the time it arrives, the other three
have nothing to add.

### attrs

Use it when the basics should be done well, with full control and no
surprises. It is older and more widely used in production than pydantic or
`magic`, it has no heavy runtime dependency, and its validator library is
excellent. `magic` follows its design, so anyone who likes attrs and wants
the type hints to do more of the work should find `magic` familiar.

### pydantic

Use it to parse untrusted input at a boundary, when JSON schema,
serialisation and a large ecosystem of integrations are needed. `magic` does
not compete with that. The cost is that a pydantic model gains a large public
API that its author did not write, which is acceptable at a boundary and less
so for a domain object.

### magic

Use it when the hints should drive conversion and validation, but the
result should still be a plain class, whose only methods are the ones its
author wrote and the ones the author asked for.

## Things magic does that the others do not

### Settings are inherited

dataclasses and attrs apply their decorator to each class separately, and
pydantic inherits only the `model_config` of its models. `magic` merges the
settings down the inheritance chain, so a base class sets the house style
once:

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

A subclass that changes a setting changes it for the fields that it
declares itself, and with `override=True` the change applies to the inherited
fields as well. A field that asks for something in its own annotation always
keeps it.

### Per-field behaviour is part of the annotation

The others put per-field behaviour in a `field()` call on the right-hand
side. The default then moves inside the call, and the class becomes harder to
read once several settings are involved:

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

Dict-like access is useful for anything that is a record at heart, such as
a configuration section, a table row or a block of headers:

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

A key is present while its field holds a value, so a field that is filled
in later stays out of the view until then.

### The docstring writes itself

A field described with `Doc` is listed in the class docstring:

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

- **JSON schema and serialisation.** These are pydantic's strongest
  features, and `magic` has neither yet.
- **Deep-copying leaves.** `dataclasses.asdict` deep-copies every value that
  is not a dataclass, while `asdict` in `magic` returns every value that is
  not a Magic instance as it is. The difference is deliberate, because a
  field that holds a NumPy array or another large object should not be
  copied silently.
- **Editor and type-checker support.** The others are understood by mypy and
  pyright today, so your editor completes the constructor and catches wrong
  argument types. `magic` is not, yet ([tracked here][typing]). The route
  is the same standard the others use, so most of it should follow. The
  part that will not is a field written purely as an annotation
  (`tags: Factory[list]`), which a checker cannot see a default for.
  Nor will a required field after one with a default, which checkers
  report by the `dataclasses` rule even though the class works.

[dataclasses]: https://docs.python.org/3/library/dataclasses.html
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[typing]: https://github.com/bagofseeds/bagof-magic/issues/30
