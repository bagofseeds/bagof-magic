# Input aliases and forwarding properties

`Alias` gives a field several input names. The first name is the one shown
in the signature, in the repr and in the dict-like view, while the stored
attribute keeps the name written in the class body:

```python
from bagof.magic import Magic, Alias, Property, ReadOnlyProperty, field, replace

class Person(Magic):
    name: Alias[str, ("label", "name", "title")]
```

```pycon
>>> Person(title="Ada")
Person(label='Ada')
>>> Person(name="Ada").name
'Ada'
>>> replace(Person("Ada"), title="Grace")
Person(label='Grace')
```

A single string replaces the field's input name. A tuple or a list makes the
field accept every name in it, in order of preference, and the stored name is
accepted only when it is in the list. Passing a value for the same field under
two names is an error, even when the two values are equal, and a positional
value together with an alias keyword counts as two values. Aliases do not let
a positional-only field be passed by keyword.

`Property` adds further attributes that read and write the same field:

```python
class Named(Magic, alias=True):
    name: Property[str, {"label": "readwrite", "title": "readonly"}]
```

```pycon
>>> named = Named(title="Ada")
>>> named.label
'Ada'
>>> named.label = "Grace"
>>> named.name, named.title
('Grace', 'Grace')
>>> named.title = "Ada"
Traceback (most recent call last):
AttributeError: ...
```

A string or a sequence of names creates properties that can be read and
written. A mapping chooses the access for each name: `True` and `"readwrite"`
mean the same thing, `"readonly"` forbids assignment, and `False` turns the
property off. A field cannot be deleted through a property. An assignment
through a property follows the target field's conversion, validation and
frozen rules. A read-only property does not freeze the object it returns.

`ReadOnlyProperty` is `Property` with every name read-only, which saves
writing a mapping when none of the names should be writable:

```python
class Named(Magic, alias=True):
    name: ReadOnlyProperty[str, ("label", "title")]
```

When `Property` or `ReadOnlyProperty` hints are nested, their names
accumulate. The outer hint adds its names to those of the inner one rather
than replacing them, and a name given in both takes the outer hint's access
mode. Nested `Alias` hints combine in the same way: their names are joined,
and a name that appears twice keeps its first position. Field `metadata` is
combined too. Nested `ConvertTo` or `Validate` callables are chained, with the
inner one running first. Every other setting, such as a default, a factory or
a whole-field setting like `property="all"`, is taken from the outer hint,
which replaces the inner one.

The same field can be declared with `field()`:

```python
class Named(Magic):
    name: str = field(
        alias=True,
        property={"label": True, "title": "readonly"},
    )
```

`alias=True` keeps the default public name first and adds the names of the
enabled properties after it, in the order they are declared. A field with no
properties keeps only its default name. `alias=False` keeps a leading
underscore in the input name. `Field.aliases` is always a tuple, and
`Field.public_name` is its first element.

`property=True` exposes the preferred public name as a property that can be
read and written, and `property="readonly"` exposes it read-only. When the
preferred name is already the stored name, no property is added.
`property="all"` exposes every input name the field accepts instead. The
stored name is left out, because it is already the attribute, and a name
already used by a field, a method or another attribute is skipped rather than
causing a clash. A property literally called `readonly`, `readwrite` or `all`
is written as a sequence or a mapping. A property named explicitly, by a name,
a sequence or a mapping, cannot have the name of its own field, of another
field or of an existing method. Properties apply only to stored instance
fields, not to `ClassVar` or `InitVar` fields.

`alias` and `property` can also be set for a whole class. Inherited fields
keep their settings unless `override=True`, `override="alias"` or
`override="property"` asks for them to be resolved again, and a setting
written on a field still wins over the class setting. Declaring a field again
in a subclass can replace its names and remove its old properties without
changing the base class. Two different fields cannot share an alias or a
property name, even when they come from different bases, so the old
declaration has to be removed before its name is reused.

Properties add no fields and no storage. Mapping access and serialization
use only the preferred public name as the key. Constructor hooks receive the
arguments under their preferred names, while polymorphic selection and
`replace` accept the alternate input names as well. A hand-written `__init__`
handles its own arguments, but calling `self.__magic_init__` from it applies
the generated alias handling.

The signature shows the preferred name, and the constructor's documentation
lists the alternatives. Static type checkers do not infer every accepted name,
or the generated properties, from these annotations.

## Fields that start with an underscore

A field written as `_size` is passed to the constructor as `size`. The
leading underscore is dropped from the input name, and the stored attribute
keeps the underscore:

```pycon
>>> class Cached(Magic):
...     _size: int
>>> Cached(size=3)
Cached(size=3)
>>> Cached(_size=3)
Traceback (most recent call last):
TypeError: ...
```

Static type checkers do not know this rule. They follow the
dataclass-transform convention, which takes each constructor parameter
name from the attribute name, so pyright and mypy both expect
`Cached.__init__` to accept `_size`. As a result, both checkers report an
error on the correct call `Cached(size=3)`, and neither reports anything on
`Cached(_size=3)`, even though that call raises a `TypeError` at runtime.

Declaring the input name explicitly makes the checkers agree with the
constructor. Both pyright and mypy honour the `alias` argument of `field`:

```python
from bagof.magic import Magic, field

class Cached(Magic):
    _size: int = field(alias="size")
```

With this declaration, both checkers show the constructor as taking `size`
and report `Cached(_size=3)` as an unexpected keyword argument. At runtime
nothing changes, because `size` was already the preferred input name.

A class that should use the same name for the attribute and for the
constructor argument can set `alias=False` on the class statement. The
underscore is then kept in the input name, and both checkers agree with the
constructor without further help:

```pycon
>>> class Kept(Magic, alias=False):
...     _size: int
>>> Kept(_size=3)
Kept(_size=3)
```

Writing `alias=False` on a single field, as in `field(alias=False)`, has the
same effect at runtime, but mypy rejects it because it expects the `alias`
argument of a field to be a string.

See [Settings](settings.md) for the `alias` and `property` class settings,
and [Extras](extras.md) for `mapping`, which these aliases also feed into.
