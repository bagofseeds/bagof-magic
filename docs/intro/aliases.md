---
icon: fontawesome/solid/link
---

# Input aliases and forwarding properties

Give a field several input names with `Alias`. The first name is the
one shown in the signature, repr and dict-like view. The stored attribute
keeps the name written in the class body:

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

A single string replaces the input name as before. A tuple or list accepts
all its names, in order. Include the stored name explicitly if callers
should be able to use it too. Supplying two names for the same field is
an error, even with equal values. A positional value and an alias keyword
also count as two values. Aliases do not enable keyword arguments for a
positional-only field.

`Property` exposes additional attributes backed by that same field:

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

A string or sequence of names creates read/write properties. A mapping
chooses access for each name: `True` and `"readwrite"` are equivalent,
`"readonly"` forbids assignment, and `False` disables the property.
Deletion through a property is unsupported. Writes use the target field's
conversion, validation and frozen rules. Read-only access does not freeze
an object returned by the property.

`ReadOnlyProperty` is `Property` with every name read-only, so you can
skip the mapping when none of them should be writable:

```python
class Named(Magic, alias=True):
    name: ReadOnlyProperty[str, ("label", "title")]
```

Stacked `Property` (or `ReadOnlyProperty`) hints accumulate: the outer
adds its names to the inner rather than replacing them, and a name given
on both takes the outer access mode. `Alias` hints stack the same way --
they concatenate, keeping the first spelling of a repeated name -- and so
does field `metadata`. Stacked `ConvertTo` or `Validate` callables chain,
the inner running first. Everything else -- a default, a factory, a
whole-field toggle like `property="all"` -- is last-wins, the outer
replacing the inner.

The equivalent field declaration is:

```python
class Named(Magic):
    name: str = field(
        alias=True,
        property={"label": True, "title": "readonly"},
    )
```

`alias=True` keeps the default public name first and adds enabled property
names in declaration order. With no properties it keeps the default name.
`alias=False` preserves leading underscores. `Field.aliases` always returns
a tuple, and `Field.public_name` is its first element.

`property=True` exposes the preferred public name as a read/write property;
`property="readonly"` exposes it read-only. If that name is already the
stored name, no extra property is needed. `property="all"` exposes every
input name the field accepts instead: the stored name is left out (it is
already the attribute), and any name already used for a field, method or
other attribute is skipped rather than clashing. To expose an attribute
literally called `readonly`, `readwrite` or `all`, use a sequence or
mapping. Explicit properties (a name, sequence or mapping) cannot target
themselves, other fields, or existing methods. Properties are for stored
instance fields, not ClassVars or InitVars.

Both options can be class settings. Inherited fields keep their settings
unless `override=True` (or `override="alias"` / `override="property"`) asks
them to resolve again. Explicit field settings still win. Redeclaring a
field can replace its names and remove its old properties without changing
the base class. Different fields cannot share an alias or property name,
including across bases; remove the old declaration before reusing a name.

Properties add no fields or storage. Mapping access and serialization use
only the preferred public key. Constructor hooks receive preferred names;
polymorphic selection and `replace` accept alternate input names too.
Hand-written constructors remain responsible for their own arguments;
calling `self.__magic_init__` uses the generated alias handling.

Signatures show the preferred name, and constructor documentation lists
alternatives. Static type checkers do not infer all accepted synonyms or
generated properties from these annotations.

See [Settings](settings.md) for the `alias` and `property` class settings,
and [Extras](extras.md) for `mapping`, which these aliases also feed into.
