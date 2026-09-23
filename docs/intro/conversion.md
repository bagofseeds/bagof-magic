---
icon: fontawesome/solid/arrows-rotate
---

# Conversion and validation

Turn them on and the type hint does the work:

```python
class Config(Magic, convert=True, validate=True):
    host: str
    port: int = 8080
```

```pycon
>>> Config("localhost", "9000")
Config(host='localhost', port=9000)
```

`"9000"` became `9000` because the hint said `int`. To convert only some
fields, mark them individually:

=== "Whole class"

    ```python
    class Config(Magic, convert=True):
        host: str
        port: int = 8080
    ```

=== "One field"

    ```python
    from bagof.magic import ConvertTo

    class Config(Magic):
        host: str
        port: ConvertTo[int] = 8080
    ```

The rules come from [`bagof-converters`][converters] and
[`bagof-validators`][validators]. Anything they understand (nested
containers, unions, enums, `TypedDict`, dates, paths, numpy arrays) works
here too.

## Forward references

A type hint can name something that does not exist yet: a class that refers
to itself, a name defined later in the file, a type imported only under
`if TYPE_CHECKING`. The name is looked up the first time the field is used.
By then the module has finished loading, so forward references simply work:

```python
class Router(Magic, convert=True):
    port: "Port" = 8080

class Port(int):
    pass
```

If the name is still missing at first use, the field carries on unconverted
and unvalidated, and says so once:

```
Router.port: the name `Port` is not defined, so `port` is not being
converted.
```

A field that needs its type to build a default has nothing to fall back on,
so it raises instead.

`unresolved_hints` controls the report: `"warn"` (the default), `"raise"`,
or `"ignore"`. Setting `"raise"` is worth doing in CI, where an unresolved
hint is a mistake rather than something to tolerate:

```python
class Service(Magic, convert=True, unresolved_hints="raise"):
    port: int = 8080
```

## Leaving the defaults alone

A default is converted and validated like any other value. Sometimes only
the incoming values need the attention:

```python
class Node(Magic, convert=True, convert_defaults=False):
    name: str
    parent: "Node" = None
```

```pycon
>>> Node("root")
Node(name='root', parent=None)
```

`parent: Optional["Node"]` is the precise spelling and needs nothing turned
off. But when the defaults in a class are already exactly right,
`convert_defaults=False` and `validate_defaults=False` take them as
written. Values a caller passes are still converted and validated, as are
values assigned afterwards.

See [Field annotations](fields.md) for `ConvertTo` and `Validate`, and
[Settings](settings.md) for the full settings table.

[converters]: https://bagofseeds.github.io/bagof-converters/
[validators]: https://bagofseeds.github.io/bagof-validators/
