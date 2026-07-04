"""S02 — registries, context/clock, and interface Liskov smoke tests."""

from datetime import datetime, timezone

import pytest

from datavibes.config.models import SourceSpec, StepSpec
from datavibes.context import (
    FetchContext,
    FixedClock,
    RunContext,
    SystemClock,
    format_timestamp,
)
from datavibes.errors import DuplicateStrategyError, UnknownStrategyError
from datavibes.interfaces import ProcessingStep, Source, Writer
from datavibes.registry import (
    register_source,
    register_step,
    resolve_source,
    resolve_step,
    resolve_writer,
)


def test_fixed_clock_returns_injected_instant():
    instant = datetime(2026, 6, 1, 6, 30, tzinfo=timezone.utc)
    assert FixedClock(instant).now() == instant


def test_timestamp_format_is_stable():
    instant = datetime(2026, 6, 1, 6, 30, tzinfo=timezone.utc)
    assert format_timestamp(instant) == "2026-06-01-06-30"


def test_system_clock_is_a_clock():
    assert isinstance(SystemClock().now(), datetime)


def test_register_and_resolve_source():
    @register_source("test-echo-source")
    class EchoSource(Source):
        def __init__(self, value=None):
            self.value = value

        def fetch(self, ctx):
            return [{"value": self.value}]

    source = resolve_source(SourceSpec(type="test-echo-source", options={"value": 7}))
    assert source.value == 7


def test_duplicate_registration_guard():
    @register_step("test-dup-step")
    class StepOne(ProcessingStep):
        def apply(self, rows, ctx):
            return rows

    with pytest.raises(DuplicateStrategyError):

        @register_step("test-dup-step")
        class StepTwo(ProcessingStep):
            def apply(self, rows, ctx):
                return rows


def test_unknown_source_names_the_key():
    with pytest.raises(UnknownStrategyError) as info:
        resolve_source(SourceSpec(type="does-not-exist"))
    assert "does-not-exist" in str(info.value)


def test_unknown_step_and_writer():
    with pytest.raises(UnknownStrategyError):
        resolve_step(StepSpec(name="nope"))
    with pytest.raises(UnknownStrategyError):
        resolve_writer("nope")


def test_writer_subtype_satisfies_contract(tmp_path):
    from datavibes.schema.field import Field, Schema

    class InMemoryWriter(Writer):
        def write(self, rows, schema, dest):
            dest.write_text(str(rows), encoding="utf-8")
            return dest

    dest = tmp_path / "out.txt"
    result = InMemoryWriter().write([{"a": 1}], Schema([Field(name="a", dtype="int")]), dest)
    assert result == dest and dest.exists()


def test_contexts_carry_injected_clock():
    clock = FixedClock(datetime(2026, 6, 1, tzinfo=timezone.utc))
    fetch = FetchContext(config=None, clock=clock, http=None)
    run = RunContext(config=None, clock=clock)
    assert fetch.clock.now() == run.clock.now()
