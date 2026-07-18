"""Smoke tests for the bagof.magic package."""

import importlib


def test_package_is_importable() -> None:
    """The package should be importable after installation."""
    module = importlib.import_module("bagof.magic")
    assert module is not None


def test_public_api_is_exported() -> None:
    """The headline names are exported."""
    import bagof.magic as magic

    for name in ("Magic", "magic", "Field"):
        assert name in magic.__all__
        assert hasattr(magic, name)
