---
icon: fontawesome/solid/toolbox
---

# Extras

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

A key is present while its field holds a value. A field the constructor
does not take, and that has no default, holds nothing until something
sets it. It stays out of the view until then:

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

On a frozen class, `__post_init__` cannot set such a field by assignment.
Use `object.__setattr__`, the same approach `dataclasses` and `attrs`
require:

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

**Functions that work on any Magic class**:

```python
class Point(Magic, frozen=True):
    x: float
    y: float
```

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
validation and init hooks all run on the new values. This is also why it
works on a frozen class. The other side of that: a `__post_init__` that
derives one field from another will derive it again from the already-derived
value. `asdict` recurses into nested Magic instances. Everything else is
returned as-is. A field with no value is left out. `astuple` raises instead,
because a missing position would shift everything after it.

There is also `fields` and `fields_dict` for the fields themselves, and
`is_magic` to ask whether a class was built by `Magic`.

**A field with no value** is left out of `repr()` too, so a
partially-filled object still prints cleanly. Equality counts it: two
objects are equal when the same fields hold values and those values
match. `hash` agrees.

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
gives every instance the same list. Here each one gets its own:

```pycon
>>> class Basket(Magic):
...     items: list = []
>>> first, second = Basket(), Basket()
>>> first.items.append("apple")
>>> second.items
[]
```

Set `mutable_default="raise"` to reject mutable defaults at class
definition time, the way `dataclasses` and `attrs` do. Or `"allow"` when
one shared object is what you want.

**Hooks around construction.** Write `__pre_init__` or `__post_init__`
and it runs during construction. Give it a parameter and it receives
everything the constructor was called with. `__pre_init__` sees values as
passed. `__post_init__` sees them as stored:

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

**Generic classes.** A `Magic` class can take a type parameter, and
filling it in gives the fields that type — whether you name a subclass or
fill it in at the call site:

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
>>> Box[int]("1")
Box[int](item=1)
```

`item` is `T` on `Box` (no specific type to convert to) and `int` once the
parameter is filled in — which is why the string becomes a number. Both
spellings do the same thing: `Box[int]` is a class just as `IntBox` is,
and `Box[int]("1") == Box(1)`. This works the same way when the parameter
is nested (`List[T]`, `Optional[T]`, `Dict[str, T]`).

**Documentation that writes itself.** Describe a field and it shows up in
the class docstring and in the generated `__init__`:

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
