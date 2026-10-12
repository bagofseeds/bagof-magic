# Conversion and validation

When conversion and validation are turned on, each field's type hint decides
how its values are converted and checked:

```python
class Config(Magic, convert=True, validate=True):
    host: str
    port: int = 8080
```

```pycon
>>> Config("localhost", "9000")
Config(host='localhost', port=9000)
```

The string `"9000"` became the integer `9000` because the hint says `int`.
To convert only some of the fields, mark each of them in its annotation:

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
[`bagof-validators`][validators], so anything those packages understand works
here too: nested containers, unions, enums, `TypedDict`, dates, paths and
numpy arrays.

## Forward references

A type hint can name something that does not exist yet, such as a class that
refers to itself, a name defined later in the file, or a type imported only
under `if TYPE_CHECKING`. The name is looked up the first time the field is
used. By then the module has finished loading, so the name is found:

```python
class Router(Magic, convert=True):
    port: "Port" = 8080

class Port(int):
    pass
```

If the name is still undefined when the field is first used, the field
passes its values through unconverted and unvalidated, and a warning says so
once:

```
Router.port: the name `Port` is not defined, so `port` is not being
converted.
```

A field that needs its type to build a default has nothing to fall back on,
so it raises an error instead.

The `unresolved_hints` setting chooses how an undefined name is reported:
`"warn"` (the default), `"raise"`, or `"ignore"`. `"raise"` is worth setting
in CI, where an unresolved hint is a mistake rather than something to
tolerate:

```python
class Service(Magic, convert=True, unresolved_hints="raise"):
    port: int = 8080
```

## Leaving the defaults alone

A default is converted and validated like any other value. When only the
values a caller passes need that attention, the defaults can be left alone:

```python
class Node(Magic, convert=True, convert_defaults=False):
    name: str
    parent: "Node" = None
```

```pycon
>>> Node("root")
Node(name='root', parent=None)
```

Here `parent: Optional["Node"]` would be the precise spelling, and it would
need nothing turned off. When the defaults in a class are already exactly
right, however, `convert_defaults=False` and `validate_defaults=False` take
them as written. Values that a caller passes are still converted and
validated, and so are values assigned afterwards.

See [Field annotations](fields.md) for `ConvertTo` and `Validate`, and
[Settings](settings.md) for the full settings table.

[converters]: https://bagofseeds.github.io/bagof-converters/
[validators]: https://bagofseeds.github.io/bagof-validators/
