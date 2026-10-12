# Extras

## Dict-like access

With `mapping=True`, an instance can be read like a dictionary:

```python
class Row(Magic, mapping=True):
    name: str
    age: int
```

```pycon
>>> dict(Row("ada", 36))
{'name': 'ada', 'age': 36}
```

A key is present while its field holds a value. A field that the
constructor does not take, and that has no default, holds nothing until
something sets it, so the field stays out of the view until then:

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
A `__post_init__` that needs to set it calls `object.__setattr__` instead,
which is the same approach that `dataclasses` and `attrs` require:

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

## Functions that work on any Magic class

`replace`, `asdict` and `astuple` work on an instance of any Magic class:

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
validation and the init hooks all run on the new values, and that is also why
`replace` works on a frozen class. One consequence is that a `__post_init__`
which derives one field from another derives it again from the value it
already derived.

`asdict` recurses into nested Magic instances, including those inside lists,
tuples and dicts, and returns every other value as it is. A field with no
value is left out of the dictionary. `astuple` raises an error for such a
field instead, because a missing position would shift every value after it.

`fields` and `fields_dict` return the fields themselves, and `is_magic` tells
whether a class was built by `Magic`.

## Fields with no value

A field with no value is left out of `repr()` too, so a partly filled object
still prints cleanly. Equality takes the missing value into account: two
objects are equal when the same fields hold values and those values match.
`hash` follows the same rule.

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

## Mutable defaults that are not shared

In a plain class, `x: list = []` gives every instance the same list. In a
Magic class, each instance gets a list of its own:

```pycon
>>> class Basket(Magic):
...     items: list = []
>>> first, second = Basket(), Basket()
>>> first.items.append("apple")
>>> second.items
[]
```

`mutable_default="raise"` rejects a mutable default when the class is
defined, the way `dataclasses` and `attrs` do, and `mutable_default="allow"`
shares one object between the instances when that is what the class needs.

## Hooks around construction

A class can define `__pre_init__` or `__post_init__`, and the method then runs
during construction. A hook that takes a parameter receives everything the
constructor was called with. `__pre_init__` sees the values as they were
passed, and `__post_init__` sees them as they were stored:

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

## Generic classes

A `Magic` class can take a type parameter. When the parameter is given a
type, every field written with the parameter takes that type, whether the
type is given by a named subclass or at the call site:

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

On `Box`, the type of `item` is `T`, which gives no specific type to
convert to. Once the parameter is filled in, the type of `item` is `int`, and
the string therefore becomes a number. The two spellings do the same thing:
`Box[int]` is a class just as `IntBox` is, and `Box[int]("1") == Box(1)`. A
parameter nested inside another type, as in `List[T]`, `Optional[T]` or
`Dict[str, T]`, is filled in the same way.

## Generated documentation

A field described with `Doc` appears in the class docstring and in the
docstring of the generated `__init__`:

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
