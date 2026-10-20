"""Platform implementations and the registry that discovers them.

Every module in this package is imported on first use of ``registry()``, so a new
platform only needs a module containing a class decorated with ``@register``.
"""

import importlib
import pkgutil
from functools import cache
from typing import Any

from patchy.platforms.base import Platform, Release, Update

__all__: list[str] = ["Platform", "Release", "Update", "register", "registry"]

_REGISTRY: dict[str, type[Platform[Any]]] = {}


def register[P: type[Platform[Any]]](cls: P) -> P:
    """Make a platform class available under its ``key``.

    Args:
        cls: The platform class.

    Returns:
        The class, unchanged.

    Raises:
        ValueError: Another platform already uses the same key.
    """
    key: str = cls.key

    if key != key.lower():
        msg: str = f"Platform key {key!r} must be lowercase"

        raise ValueError(msg)

    if (existing := _REGISTRY.get(key)) is not None and existing is not cls:
        msg = f"Platform key {key!r} is used by {existing.__name__} and {cls.__name__}"

        raise ValueError(msg)

    _REGISTRY[key] = cls

    return cls


@cache
def _discover() -> None:
    """Import every platform module once so their ``@register`` decorators run."""
    for module in pkgutil.iter_modules(__path__, f"{__name__}."):
        if module.name != f"{__name__}.base":
            importlib.import_module(module.name)


def registry() -> dict[str, type[Platform[Any]]]:
    """Return every available platform class, keyed by platform key."""
    _discover()

    return dict(sorted(_REGISTRY.items()))
