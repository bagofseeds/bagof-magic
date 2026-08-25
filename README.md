# bagof-magic

**Classes that build themselves from your type hints.**

Write down what your data looks like. `Magic` writes the `__init__`, the
`__repr__`, the comparisons — and, if you ask it to, converts and checks every
value on the way in.

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

If you would rather decorate than inherit, both spellings do the same thing:

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

---

## Three things that make it different

### Settings are inherited

Say it once on a base class and every subclass keeps it. No repeating the same
decorator down a hierarchy.

```python
class Record(Magic, frozen=True, kw_only=True):
    id: int

class User(Record):
    name: str
```

```pycon
>>> User(id=1, name="ada")
User(id=1, name='ada')
```

A subclass that wants something different just says so — `class Draft(Record,
frozen=False)`.

### Per-field behaviour lives in the annotation

What a field does is written where the field is, so the default stays where
you expect it:

```python
from bagof.magic import Magic, Factory, KwOnly, NoRepr

class Task(Magic):
    name: str
    tags: Factory[list]          # a fresh list per task, not one shared list
    token: NoRepr[str] = ""      # kept, but never printed
    priority: KwOnly[int] = 0    # must be passed by name
```

```pycon
>>> Task("build", ["ci"], priority=2)
Task(name='build', tags=['ci'], priority=2)
```

If you are coming from `dataclasses` or `attrs`, the spelling you already
know works too — `Field(...)` as the default value. Both produce the same
field, so use whichever reads better:

=== "In the annotation"

    ```python
    from bagof.magic import Magic, Factory, NoRepr

    class Task(Magic):
        name: str
        tags: Factory[list]
        token: NoRepr[str] = ""
    ```

=== "As the default"

    ```python
    from bagof.magic import Magic, Field

    class Task(Magic):
        name: str
        tags: list = Field(factory=list)
        token: str = Field(default="", repr=False)
    ```

The annotation form composes better — several of them stack on one field
without nesting — and the `Field(...)` form takes anything the annotations
cannot say.

### Conversion and validation come from the type

Turn them on and the type hint does the work — parsing a config file, checking
an API payload, cleaning user input:

```python
class Config(Magic, convert=True, validate=True):
    host: str
    port: int = 8080
```

```pycon
>>> Config("localhost", "9000")
Config(host='localhost', port=9000)
```

`"9000"` became `9000` because the hint said `int`. Prefer to be selective?
Mark individual fields instead:

=== "Whole class"

    ```python
    class Config(Magic, convert=True):
        host: str
        port: int = 8080
    ```

=== "One field"

    ```python
    from bagof.magic import ConvertTo

    class Config(Magic):
        host: str
        port: ConvertTo[int] = 8080
    ```

The rules come from [`bagof-converters`][converters] and
[`bagof-validators`][validators], so anything they understand — nested
containers, unions, enums, `TypedDict`, dates, paths, numpy arrays — works
here too.

---

## Also included

**Dict-like access**, when you want it:

```python
class Row(Magic, mapping=True):
    name: str
    age: int
```

```pycon
>>> dict(Row("ada", 36))
{'name': 'ada', 'age': 36}
```

**A handful of functions** that work on any Magic class, or on one of its
instances — `Point` from the top of this page, say:

```pycon
>>> from bagof.magic import replace, asdict, astuple
>>> replace(Point(1.0, 2.0), y=20.0)
Point(x=1.0, y=20.0)
>>> asdict(Point(1.0, 2.0))
{'x': 1.0, 'y': 2.0}
>>> astuple(Point(1.0, 2.0))
(1.0, 2.0)
```

`replace` builds the copy by calling the class again, so conversion,
validation and the init hooks all run on the new values — which is also why it
works on a frozen class. The other side of that: a `__post_init__` which works
one field out from another works it out again, starting from the value it
already worked out, so `replace` with no changes at all can come back
different. `asdict` hands the values back exactly as they are stored: it does
not copy them, and a field holding another object gives you that object rather
than a dict of its fields.

There is also `fields` and `fields_dict` for the fields themselves, and
`is_magic` to ask whether a class was built by `Magic` at all.

**Mutable defaults that are not shared.** In a plain class, `x: list = []`
hands every instance the *same* list. Here each one gets its own:

```pycon
>>> class Basket(Magic):
...     items: list = []
>>> first, second = Basket(), Basket()
>>> first.items.append("apple")
>>> second.items
[]
```

Set `mutable_default="raise"` to be stopped at the class definition instead,
as `dataclasses` and `attrs` do — or `"allow"` when one shared object really
is what you want.

**Hooks around construction.** Write `__pre_init__` or `__post_init__` and
it runs on the way in. Give it a parameter and it receives everything the
constructor was called with — `__pre_init__` sees the values as passed,
`__post_init__` sees them as stored:

```python
from bagof.magic import Magic, InitVar

class Circle(Magic):
    radius: float
    scale: InitVar[float] = 1.0      # passed in, used, not kept

    def __post_init__(self, arguments):
        self.radius = self.radius * arguments.scale
```

```pycon
>>> Circle(2.0, scale=3.0)
Circle(radius=6.0)
```

**Generic classes.** A `Magic` class can take a type parameter like any
other:

```python
from typing import Generic, TypeVar
from bagof.magic import Magic

T = TypeVar("T")

class Box(Magic, Generic[T]):
    item: T
```

```pycon
>>> Box(1)
Box(item=1)
>>> Box[str]("hello")
Box(item='hello')
```

The parameter is not filled in on the fields, though: a subclass written as
`class IntBox(Box[int])` still sees `item` as `T`, so conversion and
validation have nothing to go on there. Annotate the field with a real type
in the subclass if you need those.

**Documentation that writes itself.** Describe a field and it shows up in the
class docstring and in the generated `__init__`:

```python
from bagof.magic import Doc

class Retry(Magic):
    """Retry policy."""

    times: Doc[int, "how many times to try again"] = 3
    delay: Doc[float, "seconds to wait between tries"] = 0.5
```

```pycon
>>> print(Retry.__doc__)
Retry policy.
<BLANKLINE>
Attributes
----------
times : int, default=3
    how many times to try again
delay : float, default=0.5
    seconds to wait between tries
<BLANKLINE>
<BLANKLINE>
```

---

## The annotations

Each of these can be used bare (`x: Frozen[int]`) or with a value
(`x: Default[int, 5]`). Every one has an opposite.

| Annotation | What it does | Opposite |
| --- | --- | --- |
| `Default[T, v]` | give the field a default | — |
| `Factory[T]` | build the default by calling something | — |
| `ConvertTo[T]` | convert whatever comes in | — |
| `Validate[T]` | reject anything that does not fit | — |
| `Init[T]` | may be passed by name or by position | `NoInit` |
| `Kw[T]` | may be passed by name | `NotKw` |
| `Positional[T]` | may be passed by position | `NotPositional` |
| `KwOnly[T]` | by name only | `NotKwOnly` |
| `PositionalOnly[T]` | by position only | `NotPositionalOnly` |
| `Frozen[T]` | cannot be changed afterwards | `NotFrozen` |
| `Repr[T]` | show in `repr()` | `NoRepr` |
| `Eq[T]` | count towards `==` | `NoEq` |
| `Order[T]` | count towards `<` | `NoOrder` |
| `Compare[T]` | both of the above | `NoCompare` |
| `Hash[T]` | count towards `hash()` | `NoHash` |
| `Key[T]` | appear in the dict-like view | `NotKey` |
| `ClassVar[T]` | shared by every instance | — |
| `InitVar[T]` | passed in, used, not kept | — |
| `Doc[T, "..."]` | describe the field | — |

Each one sets exactly what its name mentions, and what it sets wins over
the class setting: on a `kw_only=True` class, `x: Positional[int]` can be
passed by position anyway, and `x: Init[int]` either way. What an
annotation says nothing about follows the class as usual.

A field that can be passed neither by name nor by position is no argument
at all, which is what `NoInit` says. So `NotKwOnly` means "by position as
well" and `NotPositionalOnly` means "by name as well" — they are aliases
for `Positional` and `Kw`, not opposites of `KwOnly` and
`PositionalOnly`.

One thing to know before reaching for `Positional`, `NotKwOnly` or
`Init` on a `kw_only=True` class: a field that can be passed by position
moves to the front of the signature, ahead of the keyword-only ones,
whatever order it was declared in.

```python
class Point(Magic, kw_only=True):
    a: int
    x: Init[int]
```

```pycon
>>> Point(1, a=2)
Point(a=2, x=1)
```

`x` is declared second and is the first positional argument. That is true
of `Positional` today as well; `Init` joins it.

Anything you cannot say with one of these, say with `Field(...)` inside an
`Annotated`: `x: Annotated[int, Field(alias="ex", metadata={"unit": "m"})]`.
(On Python 3.8, import `Annotated` from `typing_extensions` rather than
`typing`.)

## The class settings

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
| `factory` | `False` | build every missing default from its type |
| `mutable_default` | `"factory"` | give each instance its own copy of `x: list = []`; or `"raise"`, or `"allow"` |
| `mapping` | `False` | behave like a dictionary; a subclass cannot turn it off again |
| `reverse` | `False` | list a subclass's own fields before inherited ones |
| `doc` | `True` | add the field table to the class docstring |

Most of them also take a string instead of `True`, which writes the method
under that name — handy when you want to call the generated one from your own.
`order` gives the name to its `<` comparison; the class is then left with no
comparison operators at all, so the method is there for you to call rather
than to answer `<`.

---

## How it compares

Close to [attrs][attrs] in spirit, with [pydantic][pydantic]'s habit of doing
real work from your type hints — and inheritance where the others use
decorators.

|  | dataclasses | attrs | pydantic | magic |
| --- | --- | --- | --- | --- |
| settings inherited by subclasses | no | no | yes | **yes** |
| per-field behaviour in the annotation | no | no | partly | **yes** |
| conversion from the type hint | no | partly | yes | **yes** |
| validation from the type hint | no | partly | yes | **yes** |
| dict-like instances | no | no | partly | **yes** |
| no methods added unless asked | yes | yes | no | **yes** |

There is a fuller side-by-side in [the comparison page][comparison].

---

## Install

```sh
pip install git+https://github.com/bagofseeds/bagof-magic.git
```

Python 3.8 and later.

## Status

Early. The API is settling, and things may still move. Issues and ideas are
welcome at [bagofseeds/bagof-magic][issues].

[converters]: https://bagofseeds.github.io/bagof-converters/
[validators]: https://bagofseeds.github.io/bagof-validators/
[attrs]: https://www.attrs.org
[pydantic]: https://docs.pydantic.dev
[comparison]: https://bagofseeds.github.io/bagof-magic/comparison/
[issues]: https://github.com/bagofseeds/bagof-magic/issues
