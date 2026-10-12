# Settings

Settings are keyword arguments to the class statement, rather than arguments
to a decorator.

## Settings are inherited

An option set on a base class is kept by every subclass.

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

A subclass can change any setting. The change applies to the fields the
subclass declares, and with `override=True` it applies to the inherited fields
as well:

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

A field that states its own preference in its annotation, such as
`Frozen[int]` or `KwOnly[int]`, keeps that preference whatever the class
settings say. The [field annotations](fields.md) page lists them.

## Every setting

<!-- --8<-- [start:settings] -->
```python
class Thing(Magic, frozen=True, kw_only=True, slots=True):
    ...
```

| Setting | Default | What it does |
| --- | --- | --- |
| `init` | `True` | generate `__init__` |
| `repr` | `True` | generate `__repr__`; a test such as `HideIfNone()` applies to every field |
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
| `alias` | default public name | input names; `True` includes enabled property names, `False` keeps underscores |
| `property` | `False` | forwarding attributes; `True` or `"readonly"` exposes the public name, `"all"` every input alias |
| `mapping` | `False` | behave like a dictionary; a subclass inherits the methods and cannot turn them off |
| `override` | `False` | apply this class's settings to inherited fields too |
| `polymorphic` | `False` | build one of this class's subclasses, chosen from the arguments; or `"strict"`, which refuses to build this class when none of them matches |
| `pin_discriminant` | `"pin"` | what a subclass does with the field it matches on; also `"classvar"`, `"keep"`, or any of those with `+narrow` (and `"narrow"` = `"pin+narrow"`) to narrow its type and reject other values; a field's own `Pin[T, mode]` wins over it |
| `reverse` | `False` | list a subclass's own fields before inherited ones |
| `doc` | `True` | add the field table to the class docstring |

Most of the settings that generate a method also accept a string in place
of `True`. The generated method is then bound under that name, so that a
hand-written method can call it.
<!-- --8<-- [end:settings] -->

`convert` and `validate` are described in
[Conversion and validation](conversion.md), and `polymorphic` in
[Building the right subclass](polymorphism.md). `alias` and `property` are
covered in [Aliases and properties](aliases.md), and `mapping` in
[Extras](extras.md).
