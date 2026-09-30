---
icon: fontawesome/solid/code-branch
---

# Building the right subclass

A class can hand back one of its subclasses, chosen from the arguments:

```python
class Chord(Magic, polymorphic=True):
    root: str
    mode: str = "major"
    variant: str = "natural"

class MinorChord(Chord, on={"mode": "minor"}):
    def thirds(self) -> int:
        return 3
```

```pycon
>>> Chord(root="A", mode="minor")
MinorChord(root='A', mode='minor', variant='natural')
>>> Chord(root="C")
Chord(root='C', mode='major', variant='natural')
```

A default counts the same as a value the caller passed, so `Chord(root="C")`
and `Chord(root="C", mode="major")` always produce the same class.

`MinorChord` does not need to write `mode` out again. Matching on one exact
value gives the field that value as its default, so the subclass can be
built on its own:

```pycon
>>> MinorChord(root="A")
MinorChord(root='A', mode='minor', variant='natural')
```

## Saying what a subclass stands for

A constraint is a value to equal, a set to belong to, a pattern to match, a
type to fit, or a question to answer:

| Written as | Matches when |
| --- | --- |
| `"minor"` | the argument equals it |
| `{"minor", "aeolian"}` | the argument is one of them |
| `re.compile(r"m(in)?")` | the pattern matches the whole argument |
| `int`, `Literal["a", "b"]` | the argument fits the type |
| `lambda v: v > 3` | the call answers yes |
| `...` | the argument was given at all |

A subclass is in the running when every constraint it declares matches.

## Which subclass wins

More conditions beats fewer. A narrower condition beats a wider one. In
order: how many fields the subclass constrains, then how precise the
constraints are (exact value, then set, then pattern, then type), then how
far down the hierarchy the subclass sits.

Import order is never considered. Two subclasses that no rule separates
raise `AmbiguousPolymorphError`. Use `priority=` to settle it. It is also
how you spell "when nothing else fits", since a subclass that constrains
nothing matches everything:

```python
class Note(Magic, polymorphic=True):
    name: str

class Sharp(Note, on={"name": lambda name: name.endswith("#")}):
    pass

class Natural(Note, on={}, priority=-1):
    pass
```

```pycon
>>> Note("C#")
Sharp(name='C#')
>>> Note("C")
Natural(name='C')
```

## Narrowing more than once

A subclass of a subclass registers with its parent, so each step narrows
the choice:

```python
class HarmonicMinor(MinorChord, on={"variant": "harmonic"}):
    pass
```

```pycon
>>> Chord(root="A", mode="minor", variant="harmonic")
HarmonicMinor(root='A', mode='minor', variant='harmonic')
```

Reaching `HarmonicMinor` means satisfying `MinorChord` first. Ask for
`variant="harmonic"` without a `mode` and the first step matches nothing:

```pycon
>>> Chord(root="A", variant="harmonic")
Chord(root='A', mode='major', variant='harmonic')
```

### A plain class in between

A subclass written without `on=` stands for nothing, so it is never chosen.
It can still sit between the root and the subclasses that are:

```python
class Seventh(Chord):
    def notes(self) -> int:
        return 4

class DominantSeventh(Seventh, on={"variant": "dominant"}):
    pass
```

```pycon
>>> Chord(root="G", variant="dominant")
DominantSeventh(root='G', mode='major', variant='dominant')
>>> Seventh(root="G", variant="dominant")
DominantSeventh(root='G', mode='major', variant='dominant')
```

### Combining two subclasses

A class that inherits from two subclasses on different branches stands for
what both of them stand for. It does not have to say it again:

```python
from typing import Optional

class Axis(Magic, polymorphic=True):
    name: str
    unit: Optional[str] = None
    direction: Optional[str] = None

class SpatialAxis(Axis, on={"unit": "metre"}):
    pass

class OrientedAxis(Axis, on={"direction": {"up", "down"}}):
    pass

class OrientedSpatialAxis(SpatialAxis, OrientedAxis):
    pass
```

It is reached from the root and from either parent, but only when both
conditions hold. A missing argument is never guessed:

```pycon
>>> Axis("z", unit="metre", direction="up")
OrientedSpatialAxis(name='z', unit='metre', direction='up')
>>> SpatialAxis("z", direction="up")
OrientedSpatialAxis(name='z', unit='metre', direction='up')
>>> SpatialAxis("z")
SpatialAxis(name='z', unit='metre', direction=None)
>>> Axis("z", direction="up")
OrientedAxis(name='z', unit=None, direction='up')
```

An `on=` of its own adds to what the two parents ask for; it can narrow the
choice, never widen it. When both parents match equally well, the class
below them settles it, because it asks for more than either.

A value either parent pins is pinned on the combined class too, and stored
the way that parent stores it -- its `pin_discriminant`, not the one the
combined class inherits. A field that says for itself (see
[pinning one field](#pinning-one-field)) is stored its own way everywhere:

```pycon
>>> OrientedSpatialAxis("z", direction="up").unit
'metre'
```

Two parents that cannot both hold, such as two different values for one
field, make a class nothing could ever build. It is refused when it is
written:

```pycon
>>> class TimeAxis(Axis, on={"unit": "second"}):
...     pass
...
>>> class SpaceTime(SpatialAxis, TimeAxis):
...     pass
...
Traceback (most recent call last):
TypeError: Nothing can build SpaceTime: ...
```

### Leaving a class out

`on=None` says a class stands for nothing, so no parent ever builds it. It
works anywhere, and it is how to write a class that combines two subclasses
without being chosen for them:

```pycon
>>> class SpaceTime(SpatialAxis, TimeAxis, on=None):
...     pass
...
>>> SpaceTime("t", unit="second")
SpaceTime(name='t', unit='second', direction=None)
```

A subclass of it can still say what it stands for, and is reached through it.

## Registering a class you did not write

```pycon
>>> class Diminished(Chord):
...     pass
...
>>> Chord.register_polymorph(Diminished, mode="dim")
<class '...Diminished'>
>>> Chord(root="B", mode="dim")
Diminished(root='B', mode='dim', variant='natural')
```

When you are writing the class yourself, leave the class out of the call
and it reads as a decorator:

```pycon
>>> @Chord.register_polymorph(mode="aug")
... class Augmented(Chord):
...     pass
...
>>> Chord(root="C", mode="aug")
Augmented(root='C', mode='aug', variant='natural')
```

Registering later only changes what is built later. Existing instances are
untouched.

## A class that takes a type parameter

Choosing a subclass and filling a type parameter in work together. The
subclass is chosen from the arguments, and comes back with the parameter
filled in the same way:

```python
from typing import Generic, TypeVar
from bagof.magic import Magic

V = TypeVar("V")

class Signal(Magic, Generic[V], polymorphic=True, convert=True):
    kind: str
    value: V

class Inverse(Signal[V], on={"kind": "inverse"}):
    pass
```

```pycon
>>> Signal[int](kind="inverse", value="7")
Inverse[int](kind='inverse', value=7)
>>> Signal(kind="inverse", value="7")
Inverse(kind='inverse', value='7')
```

`value` is `V` on `Signal`, so nothing converts it; `Signal[int]` makes it
an `int` on the subclass it builds.

## The two settings

`polymorphic="strict"` refuses to build the class itself. It names the
subclasses it considered. This is how a missing import shows up as a missing
import, rather than as a dispatch that quietly did nothing. A class that is
itself registered somewhere is exempt: building it is the whole point of
having registered, so a leaf with no subclasses of its own works normally.

`pin_discriminant` decides what the matched field becomes on the subclass.
`"pin"` (the default) gives it that value as a default. It stays in repr,
in `==`, and in anything that walks the fields. `"classvar"` makes it a
class attribute, stored once rather than once per instance. The constructor
still accepts and discards the value, so both
`Chord(root="A", mode="sus")` and `SusChord(root="A", mode="sus")` keep
working. `"keep"` leaves the field exactly as the subclass wrote it.

A pinned value is a default the class author wrote. It is converted,
validated and copied per instance, exactly as `mode: str = "minor"` would
be. `convert_defaults` and `validate_defaults` apply to it the same way.

Add `+narrow` to any of the three (or write `"narrow"` on its own, which
means `"pin+narrow"`) to also narrow the field to what the subclass stands
for. An exact value becomes `Literal["minor"]`, a set of values becomes a
`Literal` of them, and a type is used as it is; a regular expression or a
callable narrows nothing. On top of the type, a validator is added that
turns down any other value, chained after whatever converting or validating
the field already does, so the base's own checks still run:

```python
class LocrianChord(Chord, on={"mode": "locrian"}, pin_discriminant="narrow"):
    pass
```

```pycon
>>> LocrianChord(root="A").mode
'locrian'
>>> LocrianChord(root="A", mode="dorian")
Traceback (most recent call last):
ValueValidationError: ...
```

`"keep+narrow"` is the useful combination when a field already has a
default the constraint accepts, or a set of values it may take: the storage
is left alone and only the check is added.

```python
class SusChord(Chord, on={"mode": "sus"}, pin_discriminant="classvar"):
    pass
```

```pycon
>>> SusChord.mode
'sus'
>>> SusChord(root="B")
SusChord(root='B', variant='natural')
```

!!! warning "`classvar` and round trips"
    Under `"classvar"` the discriminant is no longer one of the instance's
    fields, so `asdict` leaves it out. A dictionary without it cannot be
    dispatched back to the same subclass. Use `"pin"` whenever the values
    have to survive a round trip through a config file or a database.

You can also write the class attribute yourself, `mode: ClassVar[str] =
"minor"`. What happens then depends on whether the subclass still takes the
field. If it takes `mode`, the value it is handed reaches a parameter that
accepts it. If it does not take `mode` but holds a value the constraint
calls for, the base leaves `mode` out of the call that builds it -- so both
`Chord(root="A", mode="minor")` and the subclass work, and the subclass
called directly does not take `mode` at all. Only when the subclass neither
takes `mode` nor holds a value the constraint accepts is it refused, since
then the base could only pass `mode` to a constructor that would reject it.
`pin_discriminant="classvar"` is the spelling that keeps the field a
parameter while storing it once, so both calls keep working without writing
the attribute out.

### Pinning one field

A field can say for itself what a subclass that matches on it does with it.
`Pin[T, mode]` takes the same values as `pin_discriminant`, and also `True`
for `"pin"` and `False` for `"keep"`. `Pin[T]` is `Pin[T, "pin"]`,
`Narrow[T]` is `Pin[T, "narrow"]`, and `NoPin[T]` is `Pin[T, False]`.

```python
class Shape(Magic, polymorphic=True):
    kind: Pin[str, "classvar"] = ""
    size: float = 1.0

class Circle(Shape, on={"kind": "circle"}):
    pass
```

```pycon
>>> Circle.kind
'circle'
>>> Shape(kind="circle", size=2.0)
Circle(size=2.0)
```

The field's own mode wins over `pin_discriminant`, on every subclass that
matches on it, however far down:

```python
class Square(Shape, on={"kind": "square"}, pin_discriminant="narrow"):
    pass
```

```pycon
>>> Square.kind
'square'
>>> Square()
Square(size=1.0)
```

A subclass that writes the field out again keeps it as written, as before.
To pin it another way, give the new annotation a mode of its own:

```python
class Hexagon(Shape, on={"kind": "hexagon"}):
    kind: Narrow[str]
```

```pycon
>>> Hexagon().kind
'hexagon'
>>> Hexagon(kind="square")
Traceback (most recent call last):
ValueValidationError: ...
```

A default written beside a mode that pins or narrows the field has to be
one the subclass stands for. Any other value could never be used, since the
pin replaces it or the narrowing turns it down, so the class is refused:

```pycon
>>> class Pentagon(Shape, on={"kind": "pentagon"}):
...     kind: Pin[str] = "square"
...
Traceback (most recent call last):
TypeError: Pentagon stands for kind='pentagon', ...
```

A mode on a field that no subclass matches on does nothing.

Pickling and copying rebuild through the class an instance already has.
Neither goes back through the dispatch.

See [Settings](settings.md) for `polymorphic` and `pin_discriminant`
alongside every other setting.
