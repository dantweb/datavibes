"""The three extension registries (OCP seam).

New sources, steps, and writers register here via decorators. The pipeline
resolves a config's ``type``/``name`` string to a registered class — you never
edit the SDK to add a dataset.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Type, TypeVar

from datavibes.errors import DuplicateStrategyError, UnknownStrategyError
from datavibes.interfaces import ProcessingStep, Source, Writer

if TYPE_CHECKING:
    from datavibes.config.models import SourceSpec, StepSpec

SOURCE_REGISTRY: dict[str, Type[Source]] = {}
STEP_REGISTRY: dict[str, Type[ProcessingStep]] = {}
WRITER_REGISTRY: dict[str, Type[Writer]] = {}

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


def resolve_writer(name: str) -> Writer:
    """Construct the writer registered under ``name``."""
    cls = WRITER_REGISTRY.get(name)
    if cls is None:
        raise UnknownStrategyError(
            f"unknown writer '{name}' "
            f"(known: {', '.join(sorted(WRITER_REGISTRY)) or 'none'})"
        )
    return cls()
