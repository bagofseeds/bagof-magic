# bagof-magic

`Magic` is a `dataclass`-like base built on hint-based *magic*: field
behaviour is driven by type hints and resolved through the sibling
[`bagof-validators`](https://github.com/bagofseeds/bagof-validators) and
[`bagof-converters`](https://github.com/bagofseeds/bagof-converters)
packages.

Unlike a `dataclass`, options are given as class keyword arguments and are
inherited (though an equivalent `@magic` decorator is also provided):

```python
from bagof.magic import Magic

class Point(Magic, frozen=True):
    x: float
    y: float

# --- or ---

from bagof.magic import magic

@magic(frozen=True)
class Point:
    x: float
    y: float
```

Per-field behaviour is expressed through annotations rather than a `field()`
function -- including automatic conversion and validation:

```python
from bagof.magic import Magic, ConvertTo, Validate

class Config(Magic):
    port: ConvertTo[int]     # "8080" -> 8080, via bagof-converters
    name: Validate[str]      # rejected unless already a str, via bagof-validators
```

Most `dataclass` options are supported (`init`, `repr`, `eq`, `order`,
`frozen`, `slots`, `kw_only`, `match_args`, ...), plus `convert`, `validate`
and `factory`.
