"""S13 — pure derive helpers behind the map datasets (normalisation, sex ratio)."""

import math

import pytest

from datavibes.processing import functions
from datavibes.processing.steps import DERIVE_FUNCTIONS


def test_scale_to_range_log_spreads_orders_of_magnitude_evenly():
    assert functions.scale_to_range([1, 10, 100]) == pytest.approx([0.1, 0.55, 1.0])


def test_scale_to_range_linear():
    result = functions.scale_to_range([0, 5, 10], method="linear", floor=0.0, ceil=1.0)
    assert result == pytest.approx([0.0, 0.5, 1.0])


def test_scale_to_range_all_equal_maps_to_midpoint():
    assert functions.scale_to_range([7, 7, 7]) == pytest.approx([0.55, 0.55, 0.55])


def test_scale_to_range_invalid_values_are_none_and_excluded_from_domain():
    result = functions.scale_to_range([None, 0, -3, 1, 100, float("nan")])
    assert result[:3] == [None, None, None]
    assert result[3:5] == pytest.approx([0.1, 1.0])
    assert result[5] is None


def test_scale_to_range_rejects_unknown_method():
    with pytest.raises(ValueError):
        functions.scale_to_range([1, 2], method="cubic")


def test_normalization_domain_and_inverse_round_trip():
    domain = functions.normalization_domain([1, 10, 100], method="log")
    assert domain == pytest.approx((0.0, 2.0))
    assert functions.value_at_unit(0.5, domain, method="log") == pytest.approx(10.0)
    assert functions.normalization_domain([None, 0], method="log") is None


def test_complement():
    result = functions.complement([49.5, None, 51.0], total=100)
    assert result[0] == pytest.approx(50.5)
    assert result[1] is None
    assert result[2] == pytest.approx(49.0)


@pytest.mark.parametrize(
    "male_share, expected",
    [(50.06, "male"), (49.94, "female"), (50.04, "equal"), (49.96, "equal"), (None, None)],
)
def test_sex_majority_respects_tolerance(male_share, expected):
    assert functions.sex_majority([male_share], tolerance=0.05) == [expected]


def test_sex_majority_boundary_is_equal():
    # Exactly at ±tolerance counts as "equal" (strict inequality for a majority).
    assert functions.sex_majority([50.5, 49.5], tolerance=0.5) == ["equal", "equal"]


def test_round_to():
    assert functions.round_to([0.6625999246306395, None, 49.400000000000006], digits=4) == [0.6626, None, 49.4]


def test_new_helpers_are_available_to_derive():
    for name in ("scale_to_range", "complement", "sex_majority", "round_to"):
        assert name in DERIVE_FUNCTIONS


def test_scale_to_range_never_returns_nan():
    result = functions.scale_to_range([1, 2, 3])
    assert all(value is not None and not math.isnan(value) for value in result)


# ------------------------------------------------- overpopulation threshold
def test_at_least_flags_values_at_or_above_threshold():
    assert functions.at_least([999.9, 1000, 1500, None], threshold=1000) == [False, True, True, None]


def test_at_least_accepts_threshold_as_string_from_env_interpolation():
    assert functions.at_least([600.0], threshold="500") == [True]


def test_unit_normalize_with_upper_pins_one_at_the_threshold_and_clamps():
    units = functions.unit_normalize([1, 10, 100, 5000], method="log", upper=100)
    assert units == pytest.approx([0.0, 0.5, 1.0, 1.0])


def test_unit_normalize_upper_above_data_max_leaves_headroom():
    units = functions.unit_normalize([1, 10], method="log", upper=100)
    assert units == pytest.approx([0.0, 0.5])


def test_unit_normalize_upper_at_or_below_data_min_is_binary():
    units = functions.unit_normalize([50, 200], method="log", upper=40)
    assert units == pytest.approx([1.0, 1.0])
    assert functions.normalization_domain([50, 200], method="log", upper=40) == pytest.approx((1.69897, 1.60206), abs=1e-5)


def test_derive_params_reach_the_helper():
    from datavibes.context import RunContext
    from datavibes.processing.steps import DeriveStep

    step = DeriveStep(column="flag", expr="at_least(value)", params={"threshold": "10"})
    rows = step.apply([{"value": 5.0}, {"value": 10.0}], RunContext(config=None, clock=None))
    assert [row["flag"] for row in rows] == [False, True]
