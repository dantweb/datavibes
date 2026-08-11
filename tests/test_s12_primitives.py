"""S12 primitive library — the adapters/steps/helpers the 2026-08 catalog batch needs.

Closes the remaining gap named in
``docs/dev_log_day/20260704/reports/r01-dataset-catalog-coverage.md``:

* sources — ``paged_http_json``, ``multi_http_json``, ``columnar_http_json``,
  ``jsonstat``, plus ``worldbank-indicator`` promoted from a dataset-local
  adapter into the shared SDK.
* steps — ``flag``, ``classify``, ``forecast``.
* helpers — ``gini``, ``hhi``, ``zscore``, ``seasonal_index``, ``linear_forecast``.

Every test is offline: HTTP is a recorded fake session, every helper is pure.
"""

import math

import pytest

from datavibes.config.models import (
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
    StepSpec,
)
from datavibes.context import FetchContext
from datavibes.errors import ConfigError
from datavibes.processing import functions
from datavibes.processing.processor import Processor
from datavibes.schema.field import Field, Schema
from datavibes.sources.columnar_http_json import ColumnarHttpJsonSource
from datavibes.sources.jsonstat import JsonStatSource
from datavibes.sources.multi_http_json import MultiHttpJsonSource
from datavibes.sources.paged_http_json import PagedHttpJsonSource
from datavibes.sources.worldbank import WorldBankIndicatorSource
from tests.conftest import FakeResponse


def _ctx(session=None):
    return FetchContext(config=None, clock=None, http=session)


def _config(fields, steps):
    return DatasetConfig(
        metadata=DatasetMetadata(slug="s12", title="S12", category="test"),
        schema=Schema(fields=fields),
        sources=[SourceSpec(type="static", options={"records": []})],
        processing=steps,
    )


def _run(fields, steps, rows):
    processor = Processor(clock=None)
    return processor.process(_config(fields, steps), rows)


# --------------------------------------------------------------------- helpers
def test_gini_of_perfect_equality_is_zero():
    assert functions.gini([10.0, 10.0, 10.0]) == [0.0, 0.0, 0.0]


def test_gini_rises_with_inequality():
    equal = functions.gini([5.0, 5.0, 5.0, 5.0])[0]
    skewed = functions.gini([0.0, 0.0, 0.0, 20.0])[0]
    assert skewed > equal
    assert 0.0 <= skewed <= 1.0


def test_gini_is_broadcast_to_every_row():
    result = functions.gini([1.0, 2.0, 7.0])
    assert len(set(result)) == 1


def test_gini_of_empty_or_zero_total_is_none():
    assert functions.gini([None, None]) == [None, None]
    assert functions.gini([0.0, 0.0]) == [None, None]


def test_hhi_of_a_monopoly_is_one():
    assert functions.hhi([100.0, 0.0, 0.0]) == [1.0, 1.0, 1.0]


def test_hhi_of_four_equal_players_is_one_quarter():
    result = functions.hhi([25.0, 25.0, 25.0, 25.0])
    assert all(math.isclose(value, 0.25) for value in result)


def test_hhi_ignores_nulls_and_needs_a_positive_total():
    assert functions.hhi([None, 0.0]) == [None, None]


def test_zscore_standardizes_each_element():
    result = functions.zscore([2.0, 4.0, 6.0])
    assert math.isclose(result[0], -1.0)
    assert math.isclose(result[1], 0.0)
    assert math.isclose(result[2], 1.0)


def test_zscore_of_zero_variance_is_none():
    assert functions.zscore([3.0, 3.0]) == [None, None]


def test_seasonal_index_is_phase_mean_over_grand_mean():
    # period 2: phase 0 mean = 10, phase 1 mean = 30, grand mean = 20.
    result = functions.seasonal_index([10.0, 30.0, 10.0, 30.0], period=2)
    assert [round(value, 6) for value in result] == [0.5, 1.5, 0.5, 1.5]


def test_seasonal_index_requires_a_period_above_one():
    with pytest.raises(ValueError):
        functions.seasonal_index([1.0, 2.0], period=1)


def test_linear_forecast_projects_a_perfect_trend():
    # y = 2x over a 3-point window, projected 2 steps beyond each row.
    result = functions.linear_forecast([0.0, 2.0, 4.0, 6.0], horizon=2, window=3)
    assert result[0] is None and result[1] is None
    assert math.isclose(result[2], 8.0)
    assert math.isclose(result[3], 10.0)


def test_linear_forecast_needs_two_present_points():
    assert functions.linear_forecast([None, None, 5.0], horizon=1, window=3) == [
        None,
        None,
        None,
    ]


# ----------------------------------------------------------------------- steps
def test_flag_marks_rows_matching_a_single_condition():
    rows = [{"name": "a", "days": 400}, {"name": "b", "days": 10}]
    fields = [
        Field(name="name", dtype="str"),
        Field(name="days", dtype="int"),
        Field(name="stale", dtype="bool", nullable=True),
    ]
    steps = [StepSpec("flag", {"column": "stale", "when": {"column": "days", "gt": 365}})]
    result = _run(fields, steps, rows)
    assert [row["stale"] for row in result] == [True, False]


def test_flag_any_is_a_logical_or():
    rows = [{"a": 1, "b": 9}, {"a": 1, "b": 1}]
    fields = [
        Field(name="a", dtype="int"),
        Field(name="b", dtype="int"),
        Field(name="hit", dtype="bool", nullable=True),
    ]
    steps = [
        StepSpec(
            "flag",
            {
                "column": "hit",
                "any": [{"column": "a", "gte": 5}, {"column": "b", "gte": 5}],
            },
        )
    ]
    assert [row["hit"] for row in _run(fields, steps, rows)] == [True, False]


def test_flag_all_is_a_logical_and():
    rows = [{"a": 9, "b": 9}, {"a": 9, "b": 1}]
    fields = [
        Field(name="a", dtype="int"),
        Field(name="b", dtype="int"),
        Field(name="hit", dtype="bool", nullable=True),
    ]
    steps = [
        StepSpec(
            "flag",
            {
                "column": "hit",
                "all": [{"column": "a", "gte": 5}, {"column": "b", "gte": 5}],
            },
        )
    ]
    assert [row["hit"] for row in _run(fields, steps, rows)] == [True, False]


def test_flag_supports_membership_and_null_predicates():
    rows = [{"tier": "gold", "score": None}, {"tier": "tin", "score": 1}]
    fields = [
        Field(name="tier", dtype="str"),
        Field(name="score", dtype="int", nullable=True),
        Field(name="premium", dtype="bool", nullable=True),
        Field(name="unscored", dtype="bool", nullable=True),
    ]
    steps = [
        StepSpec("flag", {"column": "premium", "when": {"column": "tier", "in": ["gold", "silver"]}}),
        StepSpec("flag", {"column": "unscored", "when": {"column": "score", "is_null": True}}),
    ]
    result = _run(fields, steps, rows)
    assert [row["premium"] for row in result] == [True, False]
    assert [row["unscored"] for row in result] == [True, False]


def test_flag_requires_a_column_and_a_condition():
    with pytest.raises(ConfigError):
        _run([Field(name="a", dtype="int")], [StepSpec("flag", {"column": "x"})], [])


def test_classify_buckets_a_numeric_column():
    rows = [{"score": 10}, {"score": 50}, {"score": 95}, {"score": None}]
    fields = [
        Field(name="score", dtype="int", nullable=True),
        Field(name="tier", dtype="str", nullable=True),
    ]
    steps = [
        StepSpec(
            "classify",
            {
                "column": "tier",
                "value": "score",
                "bins": [
                    {"max": 30, "label": "at-risk"},
                    {"max": 70, "label": "watch"},
                    {"label": "healthy"},
                ],
                "default": "unknown",
            },
        )
    ]
    assert [row["tier"] for row in _run(fields, steps, rows)] == [
        "at-risk",
        "watch",
        "healthy",
        "unknown",
    ]


def test_classify_honours_an_explicit_lower_bound():
    rows = [{"v": 5}, {"v": 15}]
    fields = [
        Field(name="v", dtype="int"),
        Field(name="band", dtype="str", nullable=True),
    ]
    steps = [
        StepSpec(
            "classify",
            {
                "column": "band",
                "value": "v",
                "bins": [{"min": 10, "label": "high"}],
                "default": "low",
            },
        )
    ]
    assert [row["band"] for row in _run(fields, steps, rows)] == ["low", "high"]


def test_classify_requires_bins():
    with pytest.raises(ConfigError):
        _run(
            [Field(name="v", dtype="int")],
            [StepSpec("classify", {"column": "b", "value": "v"})],
            [],
        )


def test_forecast_projects_a_trend_within_each_group():
    rows = [
        {"iso3": "AAA", "year": 2020, "value": 10.0},
        {"iso3": "AAA", "year": 2021, "value": 20.0},
        {"iso3": "AAA", "year": 2022, "value": 30.0},
        {"iso3": "BBB", "year": 2020, "value": 100.0},
        {"iso3": "BBB", "year": 2021, "value": 90.0},
        {"iso3": "BBB", "year": 2022, "value": 80.0},
    ]
    fields = [
        Field(name="iso3", dtype="str"),
        Field(name="year", dtype="int"),
        Field(name="value", dtype="float"),
        Field(name="projected", dtype="float", nullable=True),
    ]
    steps = [
        StepSpec(
            "forecast",
            {
                "column": "projected",
                "value": "value",
                "by": ["iso3"],
                "horizon": 2,
                "window": 3,
            },
        )
    ]
    result = _run(fields, steps, rows)
    assert math.isclose(result[2]["projected"], 50.0)
    assert math.isclose(result[5]["projected"], 60.0)
    assert result[0]["projected"] is None


def test_forecast_requires_a_positive_horizon():
    with pytest.raises(ConfigError):
        _run(
            [Field(name="v", dtype="float")],
            [StepSpec("forecast", {"column": "p", "value": "v", "horizon": 0})],
            [],
        )


# --------------------------------------------------------------------- sources
def test_paged_http_json_walks_pages_until_short_page(make_session):
    pages = {
        1: [{"id": 1}, {"id": 2}],
        2: [{"id": 3}],
    }

    def responder(url, params, headers):
        return FakeResponse(json_body=pages.get(int(params["page"]), []))

    session = make_session(responder)
    source = PagedHttpJsonSource(
        url="https://x/api",
        select="$[*]",
        page_size=2,
        max_pages=5,
    )
    assert list(source.fetch(_ctx(session))) == [{"id": 1}, {"id": 2}, {"id": 3}]
    assert len(session.calls) == 2


def test_paged_http_json_stops_at_max_pages(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(json_body=[{"id": 1}, {"id": 2}])
    )
    source = PagedHttpJsonSource(url="https://x/api", page_size=2, max_pages=3)
    assert len(list(source.fetch(_ctx(session)))) == 6
    assert len(session.calls) == 3


def test_paged_http_json_supports_offset_paging(make_session):
    def responder(url, params, headers):
        offset = int(params["offset"])
        return FakeResponse(json_body=[{"n": offset}] if offset < 4 else [])

    session = make_session(responder)
    source = PagedHttpJsonSource(
        url="https://x/api", paging="offset", page_size=1, max_pages=9
    )
    assert list(source.fetch(_ctx(session))) == [{"n": 0}, {"n": 1}, {"n": 2}, {"n": 3}]


def test_paged_http_json_sends_a_bearer_token_from_the_environment(
    make_session, monkeypatch
):
    monkeypatch.setenv("DV_TEST_TOKEN", "s3cret")
    session = make_session(lambda url, params, headers: FakeResponse(json_body=[]))
    source = PagedHttpJsonSource(url="https://x/api", token_env="DV_TEST_TOKEN")
    list(source.fetch(_ctx(session)))
    assert session.calls[0]["headers"]["Authorization"] == "Bearer s3cret"


def test_paged_http_json_without_a_token_sends_no_auth_header(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body=[]))
    source = PagedHttpJsonSource(url="https://x/api", token_env="DV_ABSENT_TOKEN")
    list(source.fetch(_ctx(session)))
    assert "Authorization" not in session.calls[0]["headers"]


def test_multi_http_json_fans_out_over_items_and_maps_fields(make_session):
    bodies = {
        "https://x/repos/a": {"stargazers_count": 10, "owner": {"login": "aa"}},
        "https://x/repos/b": {"stargazers_count": 20, "owner": {"login": "bb"}},
    }
    session = make_session(lambda url, params, headers: FakeResponse(json_body=bodies[url]))
    source = MultiHttpJsonSource(
        url="https://x/repos/{repo}",
        items=[
            {"repo": "a", "project": "Alpha"},
            {"repo": "b", "project": "Beta"},
        ],
        fields={"stars": "stargazers_count", "owner": "owner.login"},
        carry=["project"],
    )
    assert list(source.fetch(_ctx(session))) == [
        {"project": "Alpha", "stars": 10, "owner": "aa"},
        {"project": "Beta", "stars": 20, "owner": "bb"},
    ]


def test_multi_http_json_carries_every_item_key_by_default(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body={"v": 1}))
    source = MultiHttpJsonSource(
        url="https://x/{slug}", items=[{"slug": "s", "label": "L"}], fields={"v": "v"}
    )
    assert list(source.fetch(_ctx(session))) == [{"slug": "s", "label": "L", "v": 1}]


def test_multi_http_json_skips_a_failing_item_and_keeps_going(make_session):
    def responder(url, params, headers):
        if url.endswith("bad"):
            return FakeResponse(status_code=404, json_body={})
        return FakeResponse(json_body={"v": 7})

    session = make_session(responder)
    source = MultiHttpJsonSource(
        url="https://x/{slug}",
        items=[{"slug": "bad"}, {"slug": "good"}],
        fields={"v": "v"},
    )
    assert list(source.fetch(_ctx(session))) == [{"slug": "good", "v": 7}]


def test_multi_http_json_interpolates_items_into_params(make_session):
    session = make_session(lambda url, params, headers: FakeResponse(json_body={"v": 1}))
    source = MultiHttpJsonSource(
        url="https://x/api",
        items=[{"lang": "python"}],
        params={"q": "language:{lang}"},
        fields={"v": "v"},
    )
    list(source.fetch(_ctx(session)))
    assert session.calls[0]["params"]["q"] == "language:python"


def test_columnar_http_json_zips_parallel_arrays_into_rows(make_session):
    body = {
        "hourly": {
            "time": ["2026-01-01T00:00", "2026-01-01T01:00"],
            "pm10": [10.0, 12.0],
        }
    }
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = ColumnarHttpJsonSource(
        url="https://x/aq",
        items=[{"city": "Berlin"}],
        select="$.hourly",
        index="time",
        index_column="observed_at",
        fields={"pm10": "pm10"},
    )
    assert list(source.fetch(_ctx(session))) == [
        {"city": "Berlin", "observed_at": "2026-01-01T00:00", "pm10": 10.0},
        {"city": "Berlin", "observed_at": "2026-01-01T01:00", "pm10": 12.0},
    ]


def test_columnar_http_json_tolerates_a_short_value_array(make_session):
    body = {"unix_seconds": [1, 2, 3], "price": [5.0, 6.0]}
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = ColumnarHttpJsonSource(
        url="https://x/price",
        items=[{"zone": "DE"}],
        index="unix_seconds",
        index_column="ts",
        fields={"price": "price"},
    )
    rows = list(source.fetch(_ctx(session)))
    assert [row["price"] for row in rows] == [5.0, 6.0, None]


def test_jsonstat_expands_the_value_cube_into_tidy_rows(make_session):
    body = {
        "id": ["geo", "time"],
        "size": [2, 2],
        "dimension": {
            "geo": {
                "category": {
                    "index": {"DE": 0, "FR": 1},
                    "label": {"DE": "Germany", "FR": "France"},
                }
            },
            "time": {"category": {"index": {"2023": 0, "2024": 1}}},
        },
        "value": {"0": 1.0, "1": 2.0, "3": 4.0},
    }
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = JsonStatSource(
        url="https://x/estat",
        value_column="rate",
        dimensions={"geo": "geo_code", "time": "year"},
        label_columns={"geo": "country"},
    )
    rows = list(source.fetch(_ctx(session)))
    assert rows == [
        {"geo_code": "DE", "country": "Germany", "year": "2023", "rate": 1.0},
        {"geo_code": "DE", "country": "Germany", "year": "2024", "rate": 2.0},
        {"geo_code": "FR", "country": "France", "year": "2024", "rate": 4.0},
    ]


def test_jsonstat_skips_dimensions_not_requested(make_session):
    body = {
        "id": ["unit", "geo"],
        "size": [1, 1],
        "dimension": {
            "unit": {"category": {"index": {"PC": 0}}},
            "geo": {"category": {"index": {"DE": 0}}},
        },
        "value": {"0": 9.0},
    }
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = JsonStatSource(
        url="https://x/estat", value_column="v", dimensions={"geo": "geo"}
    )
    assert list(source.fetch(_ctx(session))) == [{"geo": "DE", "v": 9.0}]


def test_jsonstat_accepts_a_list_shaped_value_array(make_session):
    body = {
        "id": ["geo"],
        "size": [2],
        "dimension": {"geo": {"category": {"index": {"DE": 0, "FR": 1}}}},
        "value": [3.0, None],
    }
    session = make_session(lambda url, params, headers: FakeResponse(json_body=body))
    source = JsonStatSource(url="https://x/e", value_column="v", dimensions={"geo": "geo"})
    assert list(source.fetch(_ctx(session))) == [{"geo": "DE", "v": 3.0}]


def test_worldbank_indicator_is_registered_in_the_sdk(make_session):
    envelope = [
        {"page": 1, "pages": 1},
        [
            {
                "countryiso3code": "DEU",
                "country": {"value": "Germany"},
                "date": "2023",
                "value": 42.0,
            }
        ],
    ]
    session = make_session(lambda url, params, headers: FakeResponse(json_body=envelope))
    source = WorldBankIndicatorSource(indicators={"IND.X": "metric"})
    assert list(source.fetch(_ctx(session))) == [
        {"country": "Germany", "iso3": "DEU", "year": "2023", "metric": 42.0}
    ]


def test_rate_limited_response_is_retried_then_succeeds(make_session):
    from datavibes.sources.http_client import request_with_retry

    statuses = [429, 200]
    session = make_session(
        lambda url, params, headers: FakeResponse(
            status_code=statuses.pop(0), json_body={"ok": True}
        )
    )
    response = request_with_retry(
        session, "https://x/api", sleep=lambda seconds: None
    )
    assert response.status_code == 200
    assert len(session.calls) == 2


def test_rename_maps_publisher_headers_onto_schema_columns():
    rows = [{"Entity": "Germany", "Annual CO2 emissions": 600.0}]
    fields = [
        Field(name="country", dtype="str"),
        Field(name="co2_tonnes", dtype="float"),
    ]
    steps = [
        StepSpec(
            "rename",
            {"columns": {"Entity": "country", "Annual CO2 emissions": "co2_tonnes"}},
        )
    ]
    assert _run(fields, steps, rows) == [{"country": "Germany", "co2_tonnes": 600.0}]


def test_rename_requires_a_columns_mapping():
    with pytest.raises(ConfigError):
        _run([Field(name="a", dtype="str")], [StepSpec("rename", {})], [])


def test_age_days_counts_whole_days_against_the_injected_clock():
    from datetime import datetime, timezone

    from datavibes.context import FixedClock

    rows = [
        {"pushed_at": "2026-05-01T00:00:00Z"},
        {"pushed_at": "2026-06-01"},
        {"pushed_at": None},
        {"pushed_at": "not-a-date"},
    ]
    fields = [
        Field(name="pushed_at", dtype="str", nullable=True),
        Field(name="days_since_push", dtype="int", nullable=True),
    ]
    steps = [StepSpec("age_days", {"column": "days_since_push", "value": "pushed_at"})]
    config = _config(fields, steps)
    clock = FixedClock(datetime(2026, 6, 11, tzinfo=timezone.utc))
    result = Processor(clock=clock).process(config, rows)
    assert [row["days_since_push"] for row in result] == [41, 10, None, None]


def test_paged_http_json_maps_fields_through_dotted_paths(make_session):
    session = make_session(
        lambda url, params, headers: FakeResponse(
            json_body=[{"id": "org/model", "cfg": {"downloads": 5}}]
        )
    )
    source = PagedHttpJsonSource(
        url="https://x/api",
        page_size=100,
        fields={"model_id": "id", "downloads": "cfg.downloads"},
    )
    assert list(source.fetch(_ctx(session))) == [
        {"model_id": "org/model", "downloads": 5}
    ]


def test_share_of_total_is_percent_of_the_column_sum():
    result = functions.share_of_total([25.0, 75.0])
    assert [round(value, 6) for value in result] == [25.0, 75.0]


def test_share_of_total_of_a_zero_total_is_none():
    assert functions.share_of_total([0.0, None]) == [None, None]


def test_filter_keeps_only_matching_rows():
    rows = [{"v": 1.0}, {"v": None}, {"v": 5.0}]
    fields = [Field(name="v", dtype="float", nullable=True)]
    steps = [StepSpec("filter", {"when": {"column": "v", "not_null": True}})]
    assert _run(fields, steps, rows) == [{"v": 1.0}, {"v": 5.0}]


def test_filter_any_keeps_rows_matching_either_condition():
    rows = [{"a": None, "b": 2.0}, {"a": None, "b": None}]
    fields = [
        Field(name="a", dtype="float", nullable=True),
        Field(name="b", dtype="float", nullable=True),
    ]
    steps = [
        StepSpec(
            "filter",
            {"any": [{"column": "a", "not_null": True}, {"column": "b", "not_null": True}]},
        )
    ]
    assert _run(fields, steps, rows) == [{"a": None, "b": 2.0}]


def test_filter_requires_exactly_one_condition_block():
    with pytest.raises(ConfigError):
        _run([Field(name="a", dtype="int")], [StepSpec("filter", {})], [])


def test_add_sums_two_series_elementwise():
    assert functions.add([1.0, 2.0, None], [10.0, None, 5.0]) == [11.0, None, None]


def test_add_requires_equal_length_series():
    with pytest.raises(ValueError):
        functions.add([1.0], [1.0, 2.0])


def test_subtract_differences_two_series_elementwise():
    assert functions.subtract([10.0, 2.0, None], [4.0, None, 1.0]) == [6.0, None, None]


def test_run_reports_a_failed_source_instead_of_shipping_an_empty_snapshot(
    tmp_path, capsys
):
    """A throttled API must not look like a green run — `run` names the failure."""
    from datetime import datetime, timezone

    from datavibes import DatasetSDK
    from datavibes.context import FixedClock
    from datavibes.store.filestore import FileStore

    dataset_dir = tmp_path / "datasets" / "flaky"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "dataset.yaml").write_text(
        "metadata:\n"
        "  slug: flaky\n"
        "  title: Flaky\n"
        "  category: test\n"
        "schema:\n"
        "  - { name: value, dtype: int, nullable: true }\n"
        "sources:\n"
        "  - type: http_json\n"
        "    url: https://example.invalid/api\n"
        "processing:\n"
        "  - normalize\n",
        encoding="utf-8",
    )

    class ThrottledSession:
        def get(self, url, params=None, headers=None, timeout=None):
            return FakeResponse(status_code=429, json_body={})

    sdk = DatasetSDK(
        root=dataset_dir.parent,
        clock=FixedClock(datetime(2026, 8, 11, tzinfo=timezone.utc)),
        store=FileStore(tmp_path / "out", store_root=tmp_path / "store"),
        env_file=tmp_path / "absent.env",
        config_file=tmp_path / "absent.yaml",
    )
    sdk.run("flaky", http=ThrottledSession())

    assert "source failed" in capsys.readouterr().err
