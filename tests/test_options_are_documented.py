"""Every class option must be written down everywhere it belongs.

An option lives in six places: the slot list and the defaults in
`bagof.magic.options`, three docstrings, and the settings table in the
README. Adding one and forgetting a couple of them is easy, and the
result is a documented API that quietly disagrees with the code -- so
this checks rather than trusts.
"""

import re
from pathlib import Path

import pytest
import typing_extensions as tx

import bagof.magic as magic
from bagof.magic.options import Options

#: Every option, taken from the one place that decides what exists.
OPTIONS = sorted(Options._DEFAULTS)


def _root() -> tx.Optional[Path]:
    """The repository root, or `None` when running from an installed copy."""
    root = Path(magic.__file__).resolve().parents[3]
    return root if (root / "README.md").is_file() else None


def _documented(text: str) -> tx.Set[str]:
    """The option names a numpydoc parameter block describes."""
    return set(re.findall(r"^\s*(\w+) : ", text, re.MULTILINE))


@pytest.mark.parametrize("option", OPTIONS)
def test_option_has_a_slot(option: str) -> None:
    assert option in Options._slots()


@pytest.mark.parametrize("option", OPTIONS)
def test_option_is_in_the_module_docstring(option: str) -> None:
    assert option in _documented(magic.__doc__)


@pytest.mark.parametrize("option", OPTIONS)
def test_option_is_in_the_metaclass_docstring(option: str) -> None:
    assert option in _documented(magic.MetaMagic.__doc__)


@pytest.mark.parametrize("option", OPTIONS)
def test_option_is_in_the_base_class_docstring(option: str) -> None:
    assert option in _documented(magic.Magic.__doc__)


@pytest.mark.parametrize("option", OPTIONS)
def test_option_is_in_the_readme_table(option: str) -> None:
    root = _root()
    if root is None:
        pytest.skip("running from an installed copy, with no README")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert f"| `{option}` |" in readme
