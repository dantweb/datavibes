"""The three extension registries (OCP seam).

New sources, steps, and writers register here via decorators. The pipeline
resolves a config's ``type``/``name`` string to a registered class — you never
edit the SDK to add a dataset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Type, TypeVar

from datavibes.errors import DuplicateStrategyError, UnknownStrategyError
from datavibes.interfaces import ColorScale, ProcessingStep, Source, Writer

if TYPE_CHECKING:
    from datavibes.config.models import SourceSpec, StepSpec

SOURCE_REGISTRY: dict[str, Type[Source]] = {}
STEP_REGISTRY: dict[str, Type[ProcessingStep]] = {}
WRITER_REGISTRY: dict[str, Type[Writer]] = {}
COLOR_SCALE_REGISTRY: dict[str, Type[ColorScale]] = {}

_RegisteredType = TypeVar("_RegisteredType")


def _register(
    registry: dict[str, type], kind: str, name: str
) -> Callable[[Type[_RegisteredType]], Type[_RegisteredType]]:
    def decorator(cls: Type[_RegisteredType]) -> Type[_RegisteredType]:
        existing = registry.get(name)
        if existing is not None and existing is not cls:
            raise DuplicateStrategyError(
                f"{kind} '{name}' already registered as {existing.__name__}"
            )
        registry[name] = cls  # type: ignore[assignment]
        return cls

    return decorator


def register_source(name: str) -> Callable[[Type[Source]], Type[Source]]:
    """Register a :class:`Source` subclass under ``name``."""
    return _register(SOURCE_REGISTRY, "source", name)


def register_step(name: str) -> Callable[[Type[ProcessingStep]], Type[ProcessingStep]]:
    """Register a :class:`ProcessingStep` subclass under ``name``."""
    return _register(STEP_REGISTRY, "step", name)


def register_writer(name: str) -> Callable[[Type[Writer]], Type[Writer]]:
    """Register a :class:`Writer` subclass under ``name``."""
    return _register(WRITER_REGISTRY, "writer", name)


def register_color_scale(
    name: str,
) -> Callable[[Type[ColorScale]], Type[ColorScale]]:
    """Register a :class:`ColorScale` subclass under ``name``."""
    return _register(COLOR_SCALE_REGISTRY, "color scale", name)


def resolve_source(spec: "SourceSpec") -> Source:
    """Construct the source for ``spec`` from its options."""
    cls = SOURCE_REGISTRY.get(spec.type)
    if cls is None:
        raise UnknownStrategyError(
            f"unknown source type '{spec.type}' "
            f"(known: {', '.join(sorted(SOURCE_REGISTRY)) or 'none'})"
        )
    return cls(**spec.options)


def resolve_step(spec: "StepSpec") -> ProcessingStep:
    """Construct the processing step for ``spec`` from its options."""
    cls = STEP_REGISTRY.get(spec.name)
    if cls is None:
        raise UnknownStrategyError(
            f"unknown step '{spec.name}' "
            f"(known: {', '.join(sorted(STEP_REGISTRY)) or 'none'})"
        )
    return cls(**spec.options)


def resolve_writer(name: str, options: dict | None = None) -> Writer:
    """Construct the writer registered under ``name`` from its ``options``."""
    cls = WRITER_REGISTRY.get(name)
    if cls is None:
        raise UnknownStrategyError(
            f"unknown writer '{name}' "
            f"(known: {', '.join(sorted(WRITER_REGISTRY)) or 'none'})"
        )
    return cls(**(options or {}))


def resolve_color_scale(spec: dict) -> ColorScale:
    """Construct the colour scale for ``spec`` (its ``type`` + options)."""
    options = dict(spec or {})
    name = options.pop("type", None)
    cls = COLOR_SCALE_REGISTRY.get(name or "")
    if cls is None:
        raise UnknownStrategyError(
            f"unknown color scale '{name}' "
            f"(known: {', '.join(sorted(COLOR_SCALE_REGISTRY)) or 'none'})"
        )
    return cls(**options)
