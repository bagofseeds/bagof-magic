# Building the right subclass

With `polymorphic=True`, calling a class can build one of its subclasses
instead, chosen from the arguments of the call:

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

`MinorChord` does not need to declare `mode` again. A subclass that matches
on one exact value receives that value as the field's default, so the
subclass can also be built on its own:

```pycon
>>> MinorChord(root="A")
MinorChord(root='A', mode='minor', variant='natural')
>>> MinorChord.mode
'minor'
```

## Saying what a subclass stands for

Each constraint in `on=` is a value to equal, a set to belong to, a pattern
to match, a type to fit, or a function to satisfy:

| Written as | Matches when |
| --- | --- |
| `"minor"` | the argument equals it |
| `{"minor", "aeolian"}` | the argument is one of them |
| `re.compile(r"m(in)?")` | the pattern matches the whole argument |
| `int`, `Literal["a", "b"]` | the argument fits the type |
| `lambda v: v > 3` | the function returns a true value |
| `...` | the argument was given at all |

A subclass is a candidate when every constraint that it declares matches.

The keys of `on=` name each field the way the constructor accepts it. A
field declared as `_mode` in the class body is passed to the constructor as
`mode`, so `on={"mode": "minor"}` refers to that field. The name written in
the class body is also accepted, and `on={"_mode": "minor"}` has the same
effect.

## Which subclass wins

A subclass with more conditions wins over one with fewer, and a narrower
condition wins over a wider one. The rules are applied in order: first the
number of fields that the subclass constrains, then how precise the
constraints are (an exact value, then a set, then a pattern, then a type), and
finally how far down the hierarchy the subclass sits.

The order in which the subclasses were imported is never considered. When
no rule separates two subclasses, the call raises `AmbiguousPolymorphError`,
and `priority=` settles the tie. A low priority is also the way to write a
subclass for when nothing else fits, since a subclass that constrains nothing
matches every call:

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

To reach `HarmonicMinor`, a call has to satisfy `MinorChord` first. A call
that asks for `variant="harmonic"` without a `mode` matches nothing at the
first step:

```pycon
>>> Chord(root="A", variant="harmonic")
Chord(root='A', mode='major', variant='harmonic')
```

### A plain class in between

A subclass written without `on=` stands for nothing, so it is never chosen
itself. It can still sit between the root and the subclasses that are
chosen:

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
what both of them stand for, without having to repeat their conditions:

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

The combined class is reached from the root and from either parent, but
only when both conditions hold. A missing argument is never guessed:

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

An `on=` written on the combined class adds to what the two parents ask
for, so it can narrow the choice but never widen it. When both parents match
a call equally well, the combined class settles the tie, because it asks for
more than either parent.

A value that either parent pins is pinned on the combined class too. It is
stored the way that parent stores it, following that parent's
`pin_discriminant` rather than the one the combined class inherits. A field
that chooses its own mode (see [pinning one field](#pinning-one-field)) is
stored its own way everywhere:

```pycon
>>> OrientedSpatialAxis("z", direction="up").unit
'metre'
```

When the conditions of two parents cannot both hold, for example because
they ask for two different values of one field, no call could ever build the
combined class, so the class is refused when it is defined:

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

`on=None` says that a class stands for nothing, so no parent ever builds it.
It can be written on any class, and it is the way to combine two subclasses
without the combined class being chosen for them:

```pycon
>>> class SpaceTime(SpatialAxis, TimeAxis, on=None):
...     pass
...
>>> SpaceTime("t", unit="second")
SpaceTime(name='t', unit='second', direction=None)
```

A subclass of such a class can still say what it stands for, and it is then
reached through that class.

### Forgetting a field a parent chooses by

A subclass can forget a field even when one of its parents uses that
field to choose a subclass:

```python
class Voice(Magic, polymorphic=True):
    kind: str = "plain"
    grade: int = 0

class Inverted(Voice, on={"kind": "inverse"}):
    pass

class Graded(Voice):
    kind: Forget

class Third(Graded, on={"grade": 3}):
    pass
```

When a call passes a value for the forgotten field, the subclass that
forgot the field cannot accept the call, so it is passed over and the
choice is made among the remaining subclasses. When the call leaves the
field out, the subclass is chosen as usual:

```pycon
>>> Voice(grade=3)
Third(grade=3)
>>> Voice(grade=3, kind="inverse")
Inverted(kind='inverse', grade=3)
```

A class cannot be chosen for a value of a field that it does not have.
For that reason, `on={"kind": ...}` is refused on `Graded`, and on its
subclasses for as long as `kind` remains forgotten. A subclass of `Graded`
that declares `kind` again is not chosen by its value automatically. It
needs an `on=` argument of its own, or it can be registered by hand:

```python
@Voice.register_polymorph(kind="again")
class Again(Graded):
    kind: str = "again"
```

```pycon
>>> Voice(kind="again")
Again(grade=0, kind='again')
```

### Taking over a field a parent chooses by

A subclass can also [take over](fields.md#taking-over-an-inherited-field)
a field that a parent uses to choose a subclass, for example to store the
value under a private name. The parents read the arguments of a call by
the names that the constructor accepts, so the new field has to keep the
public name of the field that it takes over:

```python
class Logged(Voice):
    _kind: ... = Inherit("kind")

class Shouted(Logged, on={"kind": "shout"}):
    pass
```

```pycon
>>> Voice(kind="shout")
Shouted(kind='shout', grade=0)
>>> Voice(kind="shout")._kind
'shout'
>>> Voice(kind="shout").kind
'shout'
```

`Logged` stores the value in `_kind`, accepts it as `kind`, and reads it
back under that name. `Voice` still chooses the subclasses written below
`Logged`, because a subclass is chosen by the public name of the field
and the take-over keeps that name. A take-over that gives the field
another public name, with `alias=`, is refused as long as a parent chooses
its subclasses by that field.

## Registering a class you did not write

A class that was written without `on=`, for example in another module, can be
registered with `register_polymorph`:

```pycon
>>> class Diminished(Chord):
...     pass
...
>>> Chord.register_polymorph(Diminished, mode="dim")
<class '...Diminished'>
>>> Chord(root="B", mode="dim")
Diminished(root='B', mode='dim', variant='natural')
```

Called without a class, `register_polymorph` returns a decorator, which
reads more naturally on a class that is being written in the same place:

```pycon
>>> @Chord.register_polymorph(mode="aug")
... class Augmented(Chord):
...     pass
...
>>> Chord(root="C", mode="aug")
Augmented(root='C', mode='aug', variant='natural')
```

A registration changes only what is built after it, and existing instances
are not affected.

## A class that takes a type parameter

Choosing a subclass and filling in a type parameter work together. The
subclass is chosen from the arguments, and it comes back with its parameter
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

On `Signal`, the type of `value` is `V`, so nothing converts it.
`Signal[int]` makes `value` an `int` on the subclass that it builds.

## The two settings

`polymorphic="strict"` refuses to build the class itself when no subclass
matches, and the error names the subclasses that were considered. A missing
import therefore shows up as a missing subclass, rather than as a call that
quietly built the base class. A class that is itself registered with a parent
is exempt, because being built is the purpose of its registration, so a leaf
class with no subclasses of its own works normally.

`pin_discriminant` decides what the matched field becomes on the subclass.
`"pin"`, the default, gives the field the matched value as its default, and
the field stays in the repr, in `==` and in anything else that goes through
the fields. `"classvar"` makes the field a class attribute, stored once rather
than once per instance. The constructor still accepts the value and discards
it, so both
`Chord(root="A", mode="sus")` and `SusChord(root="A", mode="sus")` keep
working. `"keep"` leaves the field exactly as the subclass wrote it.

A pinned value is treated as a default that the class author wrote. It is
converted, validated and copied for each instance, exactly as the default in
`mode: str = "minor"` would be, and `convert_defaults` and `validate_defaults`
apply to it in the same way.

Adding `+narrow` to any of the three modes also narrows the field to what
the subclass stands for, and `"narrow"` on its own means `"pin+narrow"`. An
exact value narrows the type to `Literal["minor"]`, a set of values narrows it
to a `Literal` of those values, and a type is used as it is, while a regular
expression or a function narrows nothing. Besides the type, the field
receives a validator that turns down any other value. The validator runs
after whatever conversion or validation the field already does, so the base
class's own checks still run:

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

`"keep+narrow"` is useful when a field already has a default that the
constraint accepts, or when the constraint allows a set of values. The
field's storage is then left alone, and only the check is added.

Under `"classvar"`, the matched value is read from the class, and the repr
of an instance leaves it out:

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
    Under `"classvar"`, the matched field is no longer one of the
    instance's fields, so `asdict` leaves it out, and the resulting
    dictionary cannot choose the same subclass again. `"pin"` is the right
    mode whenever the values have to survive a round trip through a
    configuration file or a database.

The class attribute can also be written out by hand, as
`mode: ClassVar[str] = "minor"`. What happens then depends on whether the
subclass still takes the field as an argument. If it takes `mode`, the value
that the base class passes reaches a parameter that accepts it. If it does
not take `mode` but holds a value that the constraint calls for, the base
class leaves `mode` out of the call that builds the subclass. Both
`Chord(root="A", mode="minor")` and the subclass then work, and the subclass
called directly does not take `mode` at all. The subclass is refused only
when it neither takes `mode` nor holds a value that the constraint accepts,
because the base class could then only pass `mode` to a constructor that
would reject it. `pin_discriminant="classvar"` keeps the field a parameter
while storing it once, so both calls work without the attribute being written
out.

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

A subclass that declares the field again keeps the field as written. To pin
the field another way, the new annotation is given a mode of its own:

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

A default written beside a mode that pins or narrows the field has to be a
value that the subclass stands for. Any other value could never be used,
because the pin would replace it or the narrowing would turn it down, so the
class is refused. A factory beside a mode that pins one value is refused for
the same reason:

```pycon
>>> class Pentagon(Shape, on={"kind": "pentagon"}):
...     kind: Pin[str] = "square"
...
Traceback (most recent call last):
TypeError: Pentagon stands for kind='pentagon', ...
```

A mode on a field that no subclass matches on does nothing.

A linter reads the mode in `Pin[str, "classvar"]` as the name of a type and
reports it as undefined. Each mode is therefore also available as a constant,
which a linter accepts: `Pin[str, CLASSVAR]` is `Pin[str, "classvar"]`, and
`PIN`, `KEEP`, `NARROW`, `PIN_NARROW`, `CLASSVAR_NARROW` and `KEEP_NARROW`
stand for the other modes. The constants work for `pin_discriminant` too.

Pickling and copying rebuild an instance through the class that the instance
already has, and neither of them chooses a subclass again.

See [Settings](settings.md) for `polymorphic` and `pin_discriminant`
alongside every other setting.
