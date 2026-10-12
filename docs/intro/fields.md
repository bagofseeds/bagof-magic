# Field annotations

A field's annotation says what the field does, where the field is declared:

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

The `field(...)` spelling from `dataclasses` and `attrs` also works, and
both spellings produce the same `Field`:

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

The annotation form combines easily, because several annotations can be
stacked on one field. The `field(...)` form covers anything that the
annotations cannot express.

`field(...)` also takes the `dataclasses` spellings `kw_only=` and
`default_factory=`, which mypy and pyright read the same way:

```python
from bagof.magic import Magic, field

class Job(Magic):
    command: str
    env: dict = field(default_factory=dict)
    retries: int = field(default=0, kw_only=True)
```

```pycon
>>> Job("make", retries=2)
Job(command='make', env={}, retries=2)
>>> Job("make", {}, 2)
Traceback (most recent call last):
  ...
TypeError: Job.__init__() takes from 2 to 3 positional arguments but 4 were given
```

A keyword that `field(...)` does not recognise is refused rather than
ignored:

```pycon
>>> field(defaults=0)
Traceback (most recent call last):
  ...
TypeError: field() got an unexpected keyword argument 'defaults'. Did you mean 'default'? ...
```

`Field(...)` is the same thing with a capital letter. Prefer the lowercase
`field(...)` when using it as a default value: mypy reads
`tags: list = Field(factory=list)` as assigning a `Field` to a `list` slot,
while `field(...)` says it produces whatever the annotation requires.

## What a type checker can see

Type checkers such as mypy and pyright work out the constructor of a
`Magic` class the way they do for `dataclasses`. They read a field's
default, the name it is passed by, and whether it is keyword-only or left
out of the constructor, but they read these only from a call written as
the field's value. An annotation such as `KwOnly[int]` changes nothing that
a checker can see.

Every annotation in the table below can therefore also be written as the
value, and a checker reads it there as declaring the field. Written there,
each one takes the keywords that a checker reads: `alias=`, `default=`,
`factory=`, `kw_only=`, `init=` and, for pyright, `converter=`.

=== "In the annotation"

    ```python
    from bagof.magic import Magic, Alias, Factory, KwOnly, NoInit

    class Job(Magic):
        _command: Alias[str, "command"]
        env: Factory[dict]
        retries: KwOnly[int] = 0
        attempts: NoInit[int] = 0
    ```

=== "As the value"

    ```python
    from bagof.magic import Magic, Alias, Factory, KwOnly, NoInit

    class Job(Magic):
        _command: str = Alias(alias="command")
        env: dict = Factory(factory=dict)
        retries: int = KwOnly(kw_only=True, default=0)
        attempts: int = NoInit(init=False, default=0)
    ```

=== "With field()"

    ```python
    from bagof.magic import Magic, field

    class Job(Magic):
        _command: str = field(alias="command")
        env: dict = field(factory=dict)
        retries: int = field(kw_only=True, default=0)
        attempts: int = field(init=False, default=0)
    ```

The three spellings build the same class, and each one refuses `retries`
by position:

```pycon
>>> Job("make", retries=2)
Job(command='make', env={}, retries=2, attempts=0)
>>> Job("make", {}, 2)
Traceback (most recent call last):
  ...
TypeError: __init__() takes from 2 to 3 positional arguments but 4 were given
```

A checker reads the keyword and never the annotation's own meaning, so
`KwOnly()` without `kw_only=True` looks to a checker like a field that may
be passed by position. For the same reason, a keyword that contradicts the
annotation is refused rather than letting the checker and the class
disagree:

```pycon
>>> KwOnly(kw_only=False)
Traceback (most recent call last):
  ...
TypeError: KwOnly(kw_only=False) says two different things: ...
```

An annotation that does not shape the constructor, such as `Frozen()` or
`Repr(False)`, is read the same way: the field is required unless the call
also gives `default=` or `factory=`. So `x: int = Frozen()` is a required
field to a checker, as it is to the class, and `x: int = Frozen(default=0)`
is an optional one. The annotations that take an argument of their own,
such as `Doc("...")`, `ShowIf(test)` and `HideIfNone()`, take the same
keywords after it, as in `nickname: Optional[str] = HideIfNone(default=None)`.

When the annotation and the value both say something about the same field,
the value is read second. A setting that both of them give takes the
value's answer, and the names given to `Alias` in each place are all
accepted.

pyright accepts the annotations as values. mypy reads the constructor from
them correctly but still reports each one as assigning, say, a `KwOnly` to
an `int`, as it does for `Field(...)`. The `field(...)` spelling takes the
same keywords and is accepted by both checkers without an error.

## The annotations

Each of these can be used bare (`x: Frozen[int]`) or with a value
(`x: Default[int, 5]`). Most of them have an opposite, listed in the last
column.

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
| `Repr[T, fn]` | show `fn(value)` in `repr()` | -- |
| `ShowIf[T, test]` | show in `repr()` while `test(value)` is true | `HideIf` |
| `HideIfNone[T]` | hide from `repr()` while it is `None` | -- |
| `HideIfDefault[T]` | hide from `repr()` while it holds its default | -- |
| `Eq[T]` | count towards `==` | `NoEq` |
| `Order[T]` | count towards `<` | `NoOrder` |
| `Compare[T]` | both of the above | `NoCompare` |
| `Hash[T]` | count towards `hash()` | `NoHash` |
| `Key[T]` | appear in the dict-like view | `NotKey` |
| `ClassVar[T]` | shared by every instance | -- |
| `InitVar[T]` | passed in, used, not kept | -- |
| `Doc[T, "..."]` | describe the field | -- |
| `Pin[T, mode]` | how a subclass that matches on it keeps it (see [polymorphism](polymorphism.md#pinning-one-field)) | `NoPin` |
| `Narrow[T]` | `Pin[T, "narrow"]`: pinned, and narrowed to what the subclass stands for | `NoPin` |
| `Forget` | remove a field the class inherits (see [below](#forgetting-an-inherited-field)) | -- |
| `Inherit[T]` | change a field the class inherits, keeping the rest of it (see [below](#changing-an-inherited-field)) | -- |
| `Inherit[T, "x"]` | take over the inherited field `x` under this field's name (see [below](#taking-over-an-inherited-field)) | -- |

Each annotation sets exactly what its name says, and the annotation wins
over the class setting. On a `kw_only=True` class, `x: Positional[int]` can
still be passed by position. On the same class, `x: NotKw[int]` forbids
passing the field by name, which was the only way left, so the field takes
its default instead, as it does with `NoInit[int]`.

Several annotations are combined on one field by nesting them. When two of
them disagree, the outer one wins:

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

`Init` and `NoInit` say whether a field is an argument at all, while `Kw`,
`Positional` and the `...Only` pairs say how the field may be passed. A field
is an argument unless something says otherwise, so `Init[T]` changes nothing,
and `NoInit` works by forbidding both ways of passing the field.

`NotKwOnly` means that the field may be passed by position as well, and
`NotPositionalOnly` means that it may be passed by name as well. Each of them
negates only its own name and leaves the other way of passing alone, which
makes them aliases for `Positional` and `Kw`.

On a `kw_only=True` class, a field that can be passed by position moves to
the front of the signature, ahead of the keyword-only fields, whatever its
place in the class body:

```python
class Point(Magic, kw_only=True):
    a: int
    x: Positional[int]
```

```pycon
>>> Point(1, a=2)
Point(a=2, x=1)
```

`x` is declared second, but it becomes the first positional argument.

## Choosing what `repr()` shows

A field's repr setting can be a function of the field's value. When the
function returns a string, the string is shown in place of the value, and
when it returns `None` or `False`, the field is hidden. Any other result shows
`repr(value)` if the result is true and hides the field if it is false.

```pycon
>>> money = "${:,.2f}".format
>>> class Invoice(Magic):
...     total: Repr[float, money]
...     note: ShowIf[str, bool] = ""
...     paid_by: HideIfNone[tx.Optional[str]] = None
...     currency: HideIfDefault[str] = "USD"
...
>>> Invoice(1234.5)
Invoice(total=$1,234.50)
>>> Invoice(10.0, "rush", "ada", "EUR")
Invoice(total=$10.00, note='rush', paid_by='ada', currency='EUR')
```

A test given as a class setting, as in
`class Invoice(Magic, repr=HideIfNone())`, applies to every field. On a
dict-like class, a test also works as a key setting, either alone or together
with a new name: `Key("labels", ShowIf(bool))` keeps the key only while the
value is true. A key setting accepts only a test, because a key is either kept
or left out and is never reformatted.

## Forgetting an inherited field

A subclass can remove a field that it inherits by annotating the field's
name with `Forget`:

```python
from bagof.magic import Forget

class Pixel(Magic):
    x: int
    y: int = 0

class Column(Pixel):
    y: Forget
```

```pycon
>>> Column(3)
Column(x=3)
>>> Column(3, y=4)
Traceback (most recent call last):
TypeError: Column() got an argument 'y', but Column removed that field with Forget, so Column does not take it.
```

Once forgotten, the field no longer appears in the constructor, in
`repr()`, in comparisons, in the dict-like view or in `fields()`. The
subclasses of `Column` do not have the field either, unless one of them
declares `y` again.

A field is usually forgotten so that its value can be stored under another
name. Forgetting the field frees the name that the constructor accepted,
and a new field can then take that name:

```python
class Shape(Magic):
    size: int

class Cached(Shape):
    size: Forget
    _size: int

    @property
    def size(self) -> int:
        return self._size
```

```pycon
>>> Cached(3)
Cached(size=3)
>>> Cached(3).size
3
```

The constructor accepts `_size` under the name `size`, because the
constructor drops a leading underscore from a field's name. Type checkers
do not apply that rule, so they expect the parameter to be called `_size`.
[Aliases and properties](aliases.md#fields-that-start-with-an-underscore)
shows how to make the checkers agree with the constructor.

A forgotten name is no longer a field, but it can still be an ordinary
class attribute, and reading it follows the usual Python lookup through the
base classes. `Column.y` therefore still returns `Pixel`'s default, `0`.
Writing a value beside the annotation, as in `y: Forget = 1`, sets a plain
class attribute in the same way. On a class built with `slots=True`, each
instance still carries the base class's slot for `y`, so reading `y` on an
instance raises `AttributeError` until a value is assigned.

Forgetting a field affects only the class that forgets it and the
subclasses of that class. When a class also inherits the same field
through another base, the field from the other base is kept:

```python
class Plain(Pixel):
    pass

class Mixed(Column, Plain):
    pass
```

```pycon
>>> Mixed(1, 2)
Mixed(x=1, y=2)
```

A value written beside `Forget` changes only what is read from the class
itself. Each instance still holds its own value for the field that the
other base provides:

```python
class Flat(Pixel):
    y: Forget = 9

class Both(Flat, Plain):
    pass
```

```pycon
>>> Both.y
9
>>> Both(1).y
0
```

!!! warning "Type checkers still see the field"
    Type checkers such as mypy and pyright have no way of knowing that a
    field was forgotten, so they still show the field in the constructor's
    signature.

## Changing an inherited field

When a subclass declares a field again, the new declaration replaces the
inherited field completely, and the default, the aliases and every other
setting written in the base class are lost. `dataclasses`, `attrs` and
`pydantic` behave in the same way. A subclass that wants to change only
part of an inherited field writes `...` in place of the type and gives the
changes to `Inherit` as its value. The field then keeps everything that
the base class declared for it, except what `Inherit` says again:

```python
class Reading(Magic):
    value: float = 0.0
    unit: Doc[str, "The unit the value is measured in."] = "m"

class Locked(Reading):
    value: ... = Inherit(frozen=True)
    unit: ... = "cm"
```

```pycon
>>> Locked()
Locked(value=0.0, unit='cm')
>>> Locked().value = 1.0
Traceback (most recent call last):
AttributeError: Cannot set frozen field 'value'
>>> fields_dict(Locked)["unit"].doc
'The unit the value is measured in.'
```

In `Locked`, the field `value` becomes frozen and keeps its type and its
default, while the field `unit` receives a new default and keeps its type
and its documentation. A plain value after `...` changes nothing but the
default, and a default of `REQUIRED` removes the inherited default, so
that the field has to be passed.

`Inherit` accepts every keyword that `Field` accepts. Every annotation in
the family also accepts `...` as its type, which gives a second way of
writing the same change. The three classes below are equivalent:

=== "`Inherit` as the value"

    ```python
    class LockedA(Reading):
        value: ... = Inherit(frozen=True)
    ```

=== "An annotation of the family"

    ```python
    class LockedB(Reading):
        value: Frozen[...]
    ```

=== "`Inherit` with metadata"

    ```python
    class LockedC(Reading):
        value: Inherit[..., Field(frozen=True)]
    ```

From Python 3.12, `value: Annotated[..., Frozen()]` is a fourth equivalent
spelling. Older versions of `Annotated` refuse `...` as a type, so code
that has to run on those versions uses one of the spellings above.

A type other than `...` replaces the inherited type, as in
`amount: Inherit[float]`. A converter, a validator or a factory that the
base class asked to work out from the type, for example with `ConvertTo`
or `Validate`, is then worked out again from the new type. A converter or
a validator that was written as a function is kept unchanged:

```python
class Measure(Magic):
    amount: ConvertTo[int] = 0

class Precise(Measure):
    amount: Inherit[float]
```

```pycon
>>> Precise("2.5")
Precise(amount=2.5)
```

As for every annotation in the family, the first argument in the brackets
is the type, so `Inherit["Node"]` is read as a forward reference to a
class named `Node`, which is looked up when the field is first used.

A setting that the new annotation gives replaces the inherited setting, and
this applies to a converter or a validator as well, which is replaced
rather than run after the inherited one. Any setting that neither the base
class nor the new annotation gives is taken from the subclass, so a field
changed in `class Sub(Base, convert=True)` is converted even though the
fields that `Sub` does not mention keep the behaviour they had in `Base`.

## Taking over an inherited field

A subclass sometimes needs to store an inherited field under a private name.
`Inherit` takes over the inherited field when it is given the name of that
field:

```python
class Tile(Magic):
    size: int = 1
    colour: str = "grey"

class CachedTile(Tile):
    _size: ... = Inherit("size")
```

```pycon
>>> CachedTile(3)
CachedTile(size=3, colour='grey')
>>> CachedTile(3).size
3
>>> [f.name for f in fields(CachedTile)]
['_size', 'colour']
```

The inherited field `size` leaves the class in the same way as a forgotten
field does, and the field `_size` starts from the declaration of `size`.
The new field therefore keeps the type, the default, the public name and
the place in the constructor of the field that it takes over, so
`CachedTile(3)` means what `Tile(3)` means. Because the public name is
kept, the class also receives a property under that name, which reads and
assigns `_size`. A property or any other attribute that the class body
defines under the same name is kept instead, which is how the class can
decide what reading `size` does:

```python
class LoudTile(Tile):
    _size: ... = Inherit("size")

    @property
    def size(self) -> str:
        return f"{self._size} tiles"
```

```pycon
>>> LoudTile(3).size
'3 tiles'
```

Any setting of the field can be changed in the same call. `alias=` gives
the field another public name, in which case no property is made, and
`position=False` places the field where it is written in the class body
instead of where the inherited field was:

```python
class Hidden(Tile):
    _size: ... = Inherit("size", alias=False, position=False)
```

```pycon
>>> Hidden(colour="red", _size=2)
Hidden(colour='red', _size=2)
>>> Hidden(size=2)
Traceback (most recent call last):
TypeError: Hidden() got an argument 'size', but Hidden took that field over as '_size', so Hidden does not take it.
```

The take-over can also be written in the brackets, as
`_size: Inherit[..., "size"]`, where the name follows the type. Linters
such as Ruff and Pyflakes read every string inside an annotation as a
forward reference to a type, so they report `"size"` there as an
undefined name (F821). Code that a linter checks either adds
`# noqa: F821` to that line or uses the spelling with `Inherit` as the
value; turning F821 off for a whole project would hide genuine mistakes.
`_size: Annotated[int, Inherit("size")]` is also accepted by linters, at
the cost of writing the type again.

!!! warning "Type checkers still see the old field"
    Type checkers have no way of knowing that a field was changed or taken
    over. They read each annotation as a new field of its own, so they do
    not understand `...` as the inherited type, and they show a field that
    was taken over in the constructor next to the field that replaced it.

## A required field after one with a default

A field without a default can follow one that has a default:

```python
class Server(Magic):
    host: str = "localhost"
    port: int
```

```pycon
>>> Server(port=8080)
Server(host='localhost', port=8080)
>>> Server("example.org", 443)
Server(host='example.org', port=443)
>>> Server(8080)
Traceback (most recent call last):
TypeError: Server() missing a required argument: 'port'
```

Positional arguments fill the fields from the left, as in any function
call. `Server(8080)` sets `host`, so `port` is still missing.

This matters most when a subclass adds a required field to a base whose
fields all have defaults:

```python
class Job(Magic):
    retries: int = 3

class Backup(Job):
    target: str
```

```pycon
>>> Backup(target="/srv")
Backup(retries=3, target='/srv')
```

`dataclasses` and `attrs` refuse both classes.

!!! warning "Type checkers apply the stricter rule"
    mypy and pyright check a `Magic` class by the `dataclasses` rules, so
    they still report this order as an error, although the class works.
    To write code that a checker accepts, make the later fields
    keyword-only with `kw_only=True` on the class that declares them:

    ```python
    class Backup(Job, kw_only=True):
        target: str
    ```

    ```pycon
    >>> Backup(target="/srv")
    Backup(retries=3, target='/srv')
    ```

A setting that none of these annotations expresses can be given with
`Field(...)` inside `Annotated`, as in
`x: Annotated[int, Field(alias="ex", metadata={"unit": "m"})]`. On Python 3.8,
`Annotated` is imported from `typing_extensions` rather than from `typing`.

See [Settings](settings.md) for the class-wide switches these annotations
override, [Conversion and validation](conversion.md) for `ConvertTo` and
`Validate`, and [Aliases and properties](aliases.md) for `Alias`,
`Property` and `ReadOnlyProperty`.

## Type checkers

Type checkers such as mypy and pyright read the code without running it.
The annotations in this family are classes, and writing one with a type
in brackets, as in `Frozen[int]`, only becomes `Annotated[int, Frozen()]`
when the code runs. A checker therefore reports `Frozen[int]` as a class
that takes no type arguments, although the class works as described above.

Each setting has a spelling that both checkers accept. For most settings,
write the marker with parentheses inside `Annotated`, as in
`Annotated[int, Frozen()]`, importing `Annotated` from `typing_extensions`
on Python 3.8. For the others, pass the setting to `field(...)`, as the
table shows:

| Reported by a checker | Accepted by both |
| --- | --- |
| `x: Frozen[int] = 0`, and any other annotation with a type in brackets | `x: Annotated[int, Frozen()] = 0` |
| `n: Alias[int, "why"] = 0` | `n: int = field(alias="why", default=0)` |
| `n: Default[int, 3]` | `n: int = 3` |
| `n: Pin[str, "classvar"]`, `n: Doc[int, "..."]` | `n: Annotated[str, Pin("classvar")]`, `n: Annotated[int, Doc("...")]` |
| `items: Factory[list]`, read as having no default | `items: list = field(factory=list)` |
| `n: KwOnly[int]`, read as positional | `n: int = field(kw_only=True)` |
| `n: ClassVar[int] = 0`, with `ClassVar` from `bagof.magic` | `n: typing.ClassVar[int] = 0` |

The class treats `typing.ClassVar` exactly as it treats the `ClassVar` of
this family, so the last row changes nothing when the code runs.

`Annotated` does not help with every setting, because a checker accepts
the annotation but does not know what it does. A checker reads
`items: Annotated[list, Factory()]` as a field with no default, and reads
`n: Annotated[int, KwOnly()]` as a parameter that can be passed by
position. A checker also reads `_n: Annotated[int, Alias("why")]` as a
parameter named `_n`, so an input name has to be given with
`field(alias=...)` for a checker to know it. The same applies to a field
whose name starts with an underscore, which is described under
[Aliases and properties](aliases.md#fields-that-start-with-an-underscore).

A checker reads a setting given in `Annotated` as the type alone, so the
constructor still takes an `int` for `x: Annotated[int, ConvertTo()]`,
although the class converts any value that `int()` accepts.

A field that is built from an inherited one, such as
`x: ... = Inherit(frozen=True)`, cannot be typed. mypy reports `...` as a
type, here and in `x: Frozen[...]`. pyright accepts the first spelling, but
it reads the type of `x` as `...`, so the constructor checks nothing for
that argument.
