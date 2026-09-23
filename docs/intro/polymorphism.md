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

Writing the class attribute yourself, `mode: ClassVar[str] = "minor"`, is
refused. The error explains why: the base passes `mode` on to whatever it
builds, so a subclass whose constructor does not take it would break.
`pin_discriminant="classvar"` is that spelling, done so that both calls
keep working.

Pickling and copying rebuild through the class an instance already has.
Neither goes back through the dispatch.

See [Settings](settings.md) for `polymorphic` and `pin_discriminant`
alongside every other setting.
