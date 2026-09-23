---
icon: fontawesome/solid/list-ul
---

# Field annotations

Each field says what it does, right where it is declared:

```python
from bagof.magic import Magic, Factory, KwOnly, NoRepr

class Task(Magic):
    name: str
    tags: Factory[list]          # a fresh list per instance
    token: NoRepr[str] = ""      # present, but hidden from repr
    priority: KwOnly[int] = 0    # keyword-only argument
```

```pycon
>>> Task("build", ["ci"], priority=2)
Task(name='build', tags=['ci'], priority=2)
```

The `field(...)` spelling from `dataclasses` and `attrs` also works. Both
produce the same `Field`:

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
    from bagof.magic import Magic, field

    class Task(Magic):
        name: str
        tags: list = field(factory=list)
        token: str = field(default="", repr=False)
    ```

The annotation form composes naturally. Several annotations stack on one
field without nesting. The `field(...)` form covers anything the annotations
cannot say.

`Field(...)` is the same thing with a capital letter. Prefer the lowercase
`field(...)` when using it as a default value: mypy reads
`tags: list = Field(factory=list)` as assigning a `Field` to a `list` slot,
while `field(...)` says it produces whatever the annotation requires.

## The annotations

Each of these can be used bare (`x: Frozen[int]`) or with a value
(`x: Default[int, 5]`). Every one has an opposite.

| Annotation | What it does | Opposite |
| --- | --- | --- |
| `Alias[T, names]` | accept input names, preferred first | -- |
| `Property[T, names]` | expose forwarding attributes | -- |
| `ReadOnlyProperty[T, names]` | expose read-only forwarding attributes | -- |
| `Default[T, v]` | give the field a default | -- |
| `Factory[T]` | build the default by calling something | -- |
| `ConvertTo[T]` | convert whatever comes in | -- |
| `Validate[T]` | reject anything that does not fit | -- |
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
| `ClassVar[T]` | shared by every instance | -- |
| `InitVar[T]` | passed in, used, not kept | -- |
| `Doc[T, "..."]` | describe the field | -- |

Each annotation sets exactly what its name says, and that wins over the
class setting: on a `kw_only=True` class, `x: Positional[int]` can still
be passed by position, while `x: NotKw[int]` forbids the only way left and
the field takes its default instead (the same as `NoInit[int]`).

Several annotations stack on one field by nesting. When two disagree, the
outer one wins.

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

`Init` and `NoInit` say *whether* a field is an argument at all. `Kw`,
`Positional` and the `...Only` pairs say *how* it may be passed. A field
is an argument unless something says otherwise, so `Init[T]` changes
nothing. `NoInit` does the work by forbidding both ways at once.

`NotKwOnly` means "by position as well" and `NotPositionalOnly` means "by
name as well": each negates its own name and leaves the other half alone.
This makes them aliases for `Positional` and `Kw`.

One thing to know: on a `kw_only=True` class, a field that can be passed by
position moves to the front of the signature, ahead of the keyword-only
fields, regardless of its declaration order.

```python
class Point(Magic, kw_only=True):
    a: int
    x: Positional[int]
```

```pycon
>>> Point(1, a=2)
Point(a=2, x=1)
```

`x` is declared second but becomes the first positional argument.

Anything you cannot say with one of these, say with `Field(...)` inside an
`Annotated`: `x: Annotated[int, Field(alias="ex", metadata={"unit": "m"})]`.
(On Python 3.8, import `Annotated` from `typing_extensions` rather than
`typing`.)

See [Settings](settings.md) for the class-wide switches these annotations
override, [Conversion and validation](conversion.md) for `ConvertTo` and
`Validate`, and [Aliases and properties](aliases.md) for `Alias`,
`Property` and `ReadOnlyProperty`.
