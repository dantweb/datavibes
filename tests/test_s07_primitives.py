"""S07 primitive library — pure helpers + join/score steps + grouped derive.

These are the shared primitives datasets #2–#30 are authored on (s09–s11 are the
first consumers). Each helper is proven in isolation; each step through the
processor with a real schema.
"""

import math

import pytest

from datavibes.config.models import (
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
    StepSpec,
)
from datavibes.errors import ConfigError
from datavibes.processing import functions
from datavibes.processing.processor import Processor
from datavibes.schema.field import Field, Schema


# --------------------------------------------------------------------- helpers
def test_ratio_and_zero_divisor():
    assert functions.ratio([10.0, 5.0, 3.0], [2.0, 0.0, None]) == [5.0, None, None]


def test_share_is_percent_of_whole():
    assert functions.share([1.0, 3.0], [4.0, 4.0]) == [25.0, 75.0]


def test_penetration_is_share_alias():
    assert functions.penetration([1.0], [5.0]) == functions.share([1.0], [5.0])


def test_cagr_doubling_over_one_year_is_100pct():
    result = functions.cagr([100.0, 200.0], years=1)
    assert result[0] is None
    assert math.isclose(result[1], 100.0)


def test_cagr_four_x_over_two_years_is_100pct():
    result = functions.cagr([100.0, 0.0, 400.0], years=2)
    assert math.isclose(result[2], 100.0)  # (400/100)**(1/2)-1 = 1.0 → 100%


def test_cagr_non_positive_start_is_none():
    assert functions.cagr([0.0, 50.0], years=1) == [None, None]


def test_corr_is_broadcast_constant():
    result = functions.corr([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
    assert all(math.isclose(value, 1.0) for value in result)


def test_corr_zero_variance_is_none_everywhere():
    assert functions.corr([5.0, 5.0], [1.0, 2.0]) == [None, None]


def test_minmax_normalize_scales_and_inverts():
    assert functions.minmax_normalize([10.0, 20.0, 30.0]) == [0.0, 0.5, 1.0]
    assert functions.minmax_normalize([10.0, 20.0, 30.0], invert=True) == [1.0, 0.5, 0.0]


def test_minmax_all_equal_is_midpoint():
    assert functions.minmax_normalize([7.0, 7.0]) == [0.5, 0.5]


def test_volatility_rolling_stddev():
    result = functions.volatility([1.0, 1.0, 4.0], window=2)
    assert result[0] is None
    assert math.isclose(result[1], 0.0)
    assert math.isclose(result[2], math.sqrt(4.5))  # stdev([1,4]) sample


def test_volatility_window_below_two_rejected():
    with pytest.raises(ValueError):
        functions.volatility([1.0, 2.0], window=1)


# ------------------------------------------------------------------- processor
def _config(schema_fields, steps):
    return DatasetConfig(
        metadata=DatasetMetadata(slug="t", title="T", category="c"),
        schema=Schema(fields=schema_fields),
        sources=[SourceSpec(type="static", options={})],
        processing=[StepSpec(name=name, options=opts) for name, opts in steps],
    )


def _run(config, rows, clock):
    return Processor(clock).process(config, rows)


def test_join_coalesces_rows_by_key(fixed_clock):
    schema = [
        Field("iso3", "str"),
        Field("year", "int"),
        Field("a", "float", nullable=True),
        Field("b", "float", nullable=True),
    ]
    config = _config(schema, [("join", {"on": ["iso3", "year"]}), ("validate", {})])
    rows = [
        {"iso3": "DEU", "year": 2023, "a": 1.0, "b": None},
        {"iso3": "DEU", "year": 2023, "a": None, "b": 2.0},
        {"iso3": "FRA", "year": 2023, "a": 3.0, "b": None},
    ]
    out = _run(config, rows, fixed_clock)
    assert out == [
        {"iso3": "DEU", "year": 2023, "a": 1.0, "b": 2.0},
        {"iso3": "FRA", "year": 2023, "a": 3.0, "b": None},
    ]


def test_join_rejects_non_outer():
    with pytest.raises(ConfigError):
        StepSpec(name="join", options={"on": ["k"], "how": "inner"})
        from datavibes.registry import resolve_step

        resolve_step(StepSpec(name="join", options={"on": ["k"], "how": "inner"}))


def test_grouped_derive_respects_entity_boundary(fixed_clock):
    schema = [
        Field("iso3", "str"),
        Field("year", "int"),
        Field("v", "float"),
        Field("g", "float", nullable=True),
    ]
    config = _config(
        schema,
        [
            (
                "derive",
                {"column": "g", "expr": "cagr(v, years=1)", "by": ["iso3"]},
            ),
            ("validate", {}),
        ],
    )
    rows = [
        {"iso3": "DEU", "year": 2022, "v": 100.0},
        {"iso3": "DEU", "year": 2023, "v": 200.0},
        {"iso3": "FRA", "year": 2022, "v": 50.0},  # first FRA row → no cross-country lag
        {"iso3": "FRA", "year": 2023, "v": 100.0},
    ]
    out = _run(config, rows, fixed_clock)
    by_key = {(r["iso3"], r["year"]): r["g"] for r in out}
    assert by_key[("DEU", 2022)] is None
    assert math.isclose(by_key[("DEU", 2023)], 100.0)
    assert by_key[("FRA", 2022)] is None  # NOT derived from the preceding DEU row
    assert math.isclose(by_key[("FRA", 2023)], 100.0)


def test_score_weighted_composite(fixed_clock):
    schema = [
        Field("k", "str"),
        Field("x", "float"),
        Field("y", "float"),
        Field("s", "float", nullable=True),
    ]
    config = _config(
        schema,
        [
            (
                "score",
                {"column": "s", "weights": {"x": 1.0, "y": 1.0}, "scale": 100.0},
            ),
            ("validate", {}),
        ],
    )
    rows = [
        {"k": "lo", "x": 0.0, "y": 0.0},
        {"k": "hi", "x": 10.0, "y": 10.0},
        {"k": "mid", "x": 5.0, "y": 5.0},
    ]
    out = _run(config, rows, fixed_clock)
    scores = {r["k"]: r["s"] for r in out}
    assert math.isclose(scores["lo"], 0.0)
    assert math.isclose(scores["hi"], 100.0)
    assert math.isclose(scores["mid"], 50.0)
