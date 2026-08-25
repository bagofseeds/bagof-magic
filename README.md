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
frozen=False)`. That reaches the fields the subclass declares itself; add
`override=True` for it to reach the inherited ones as well:

```python
class Draft(Record, frozen=False, override=True):
    note: str = ""
```

```pycon
>>> draft = Draft(id=1)
>>> draft.id = 2
>>> draft
Draft(id=2, note='')
```

A field that asked for something in its own annotation — `Frozen[int]`,
`KwOnly[int]` — keeps it either way.

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

A hint may name something that does not exist yet when the class is
written: a class that refers to itself, a name defined further down the
file, a type imported only for type checking. It is looked up the first
time the field is actually used instead, by which point the module has
finished loading — so an ordinary forward reference simply works, and
`Router("9000").port` below is a `Port`.

```python
class Router(Magic, convert=True):
    port: "Port" = 8080

class Port(int):
    pass
```

If the name is still not there by then, the field carries on unconverted
and unvalidated, and says so once:

```
Router.port: the name `Port` is not defined, so `port` is not being
converted.
```

A field whose default was to be built from its type has nothing to carry
on with, so that one raises instead.

`unresolved_hints` decides what that report is. Turning it into an error
is worth doing in CI, where a hint that never resolves is a mistake
rather than something to live with:

```python
class Service(Magic, convert=True, unresolved_hints="raise"):
    port: int = 8080
```

The third choice, `"ignore"`, says nothing at all — for a hint you know
will not resolve and do not want to hear about again.

### Leaving the defaults alone

A default is converted and validated like anything else, so a class is as
strict about the values it was written with as about the ones it is handed.
Sometimes only the incoming values need the attention:

```python
class Node(Magic, convert=True, convert_defaults=False):
    name: str
    parent: "Node" = None
```

```pycon
>>> Node("root")
Node(name='root', parent=None)
```

`parent: Optional["Node"]` is the precise spelling and needs nothing turned
off. But when the defaults in a class are already exactly what you meant,
`convert_defaults=False` and `validate_defaults=False` say to take them as
written. Anything a caller passes is still converted and validated, as is
anything assigned afterwards.

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

A key is there while its field is holding a value. A field the constructor
does not take, and that has no default, holds none until something sets it —
so it stays out of the view until then, and joins it the moment it is given
one:

```pycon
>>> class Draft(Magic, mapping=True):
...     title: str
...     slug: NoInit[str]
>>> draft = Draft("Ada")
>>> dict(draft)
{'title': 'Ada'}
>>> draft["slug"] = "ada"
>>> dict(draft)
{'title': 'Ada', 'slug': 'ada'}
```

On a frozen class, `__post_init__` cannot set such a field by assignment —
refusing one after construction is what `frozen` is for. Reach past it with
`object.__setattr__`, the same thing `dataclasses` and `attrs` ask for here:

```pycon
>>> class Slug(Magic, frozen=True):
...     title: str
...     slug: NoInit[str]
...
...     def __post_init__(self, arguments):
...         object.__setattr__(self, "slug", self.title.lower())
>>> Slug("Hello World")
Slug(title='Hello World', slug='hello world')
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
than a dict of its fields. Like the dict-like view, it leaves out a field that
is holding no value; `astuple` says so instead, because a position only means
anything while every field is in the tuple.

There is also `fields` and `fields_dict` for the fields themselves, and
`is_magic` to ask whether a class was built by `Magic` at all.

**A field with no value** is left out of `repr()` as well, so an object you
are half-way through filling in still prints. Equality counts it rather than
skipping it: two objects are equal when the same fields are holding values and
those values match — one that has been given a value is never equal to one
that is still without, and `hash` agrees. Ordering is the one that refuses,
for the same reason `astuple` does: a comparison reads the fields in turn, so
it needs all of them.

```pycon
>>> class Draft(Magic):
...     title: str
...     slug: NoInit[str]
>>> Draft("Ada")
Draft(title='Ada')
>>> Draft("Ada") == Draft("Ada")
True
>>> ada = Draft("Ada")
>>> ada.slug = "ada"
>>> ada
Draft(title='Ada', slug='ada')
>>> ada == Draft("Ada")
False
```

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
other, and a subclass that says what it stands for gets fields of that
type:

```python
from typing import Generic, TypeVar
from bagof.magic import Magic

T = TypeVar("T")

class Box(Magic, Generic[T], convert=True):
    item: T

class IntBox(Box[int]):
    pass
```

```pycon
>>> Box("1")
Box(item='1')
>>> IntBox("1")
IntBox(item=1)
```

`item` is `T` on `Box`, which is no type to convert to and nothing to
validate against, and `int` on `IntBox` -- which is why one of them turns
the string into a number and the other does not. It works the same way
when the parameter is buried in the annotation (`List[T]`, `Optional[T]`,
`Dict[str, T]`), and a class that fills in one parameter of two leaves the
other standing for its own subclasses to fill in.

Writing the parameter where the object is built -- `Box[int]("1")` -- is a
different thing. That is a `typing` alias rather than a class, so it builds
a plain `Box` and `item` stays as it was; give the subclass a name when you
want the fields to follow.

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
| `Init[T]` | say it is an argument, which it is anyway | `NoInit` |
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
passed by position anyway, while `x: NotKw[int]` forbids the one way in
that was left and so has no parameter at all — it takes its default,
exactly like `NoInit[int]`. What an annotation says nothing about follows
the class as usual.

Several of them go on one field by nesting, and when two disagree the outer
one has the last word.

```pycon
>>> class ByName(Magic):
...     x: Kw[NotKw[int]] = 0
...
>>> ByName(x=1)
ByName(x=1)
>>> class ByPosition(Magic):
...     x: NotKw[Kw[int]] = 0
...
>>> ByPosition(1)
ByPosition(x=1)
```

`Init` and `NoInit` say *whether* a field is an argument at all; `Kw`,
`Positional` and the two `...Only` pairs say *how* it may be passed. A
field is an argument unless something says otherwise, so `Init[T]` is
there to say that out loud and changes nothing — it is `NoInit` that
does the work, by forbidding both ways at once.

That is also why `NotKwOnly` means "by position as well" and
`NotPositionalOnly` means "by name as well": each negates its own name
and leaves the other half alone, which makes them aliases for
`Positional` and `Kw` rather than opposites of `KwOnly` and
`PositionalOnly`.

One thing to know before reaching for `Positional` or `NotKwOnly` on a
`kw_only=True` class: a field that can be passed by position moves to the
front of the signature, ahead of the keyword-only ones, whatever order it
was declared in.

```python
class Point(Magic, kw_only=True):
    a: int
    x: Positional[int]
```

```pycon
>>> Point(1, a=2)
Point(a=2, x=1)
```

`x` is declared second and is the first positional argument.

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
| `convert_defaults` | `True` | convert a value that came from a default, too |
| `validate_defaults` | `True` | check a value that came from a default, too |
| `unresolved_hints` | `"warn"` | what to do when a type hint still names something undefined the first time a field needs it; or `"raise"`, or `"ignore"` |
| `factory` | `False` | build every missing default from its type |
| `mutable_default` | `"factory"` | give each instance its own copy of `x: list = []`; or `"raise"`, or `"allow"` |
| `mapping` | `False` | behave like a dictionary; a subclass inherits the methods and cannot turn them off |
| `override` | `False` | apply this class's settings to inherited fields too |
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
