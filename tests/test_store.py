"""S02 — FileStore path builders match the delivery contract + latest selection."""

from datetime import datetime, timezone

from datavibes.store.filestore import FileStore, slug_hash


def test_output_path_slug_layout_is_default(tmp_path):
    store = FileStore(tmp_path)  # default layout = "slug"
    instant = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    path = store.output_path("environment", "air-quality", instant)
    # output/<slug>/<YYYY-MM-DD-HH-MM>.csv — profile stays separate from output
    assert path.relative_to(tmp_path).parts == (
        "output",
        "air-quality",
        "2026-06-01-00-00.csv",
    )


def test_output_path_category_layout_matches_legacy_plugin_contract(tmp_path):
    store = FileStore(tmp_path, output_layout="category")
    instant = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    path = store.output_path("environment", "air-quality", instant)
    parts = path.relative_to(tmp_path).parts
    # output/<category>/<slug>-<hash>/<YYYY-MM-DD-HH-MM>.csv
    assert parts[0] == "output"
    assert parts[1] == "environment"
    assert parts[2].startswith("air-quality-")
    assert len(parts[2].split("-")[-1]) == 8
    assert parts[3] == "2026-06-01-00-00.csv"


def test_latest_output_ignores_report_artifacts(tmp_path):
    store = FileStore(tmp_path)
    instant = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    snapshot = store.output_path("env", "demo", instant)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_text("x", encoding="utf-8")
    # Reports share the output folder but must not be picked as "latest snapshot".
    for report in ("analytics.md", "statistics.md", "report.pdf"):
        (snapshot.parent / report).write_text("x", encoding="utf-8")
    assert store.latest_output("env", "demo").name == "2026-06-01-00-00.csv"


def test_slug_hash_is_stable():
    assert slug_hash("air-quality") == slug_hash("air-quality")
    assert slug_hash("air-quality") != slug_hash("hosting-benchmarks")


def test_raw_path_shape(tmp_path):
    store = FileStore(tmp_path)
    instant = datetime(2026, 6, 1, 12, 5, tzinfo=timezone.utc)
    path = store.raw_path("demo", instant)
    assert path.relative_to(tmp_path).parts == (
        "store",
        "raw",
        "demo",
        "2026-06-01-12-05.jsonl",
    )


def test_write_and_read_raw_round_trip(tmp_path):
    store = FileStore(tmp_path)
    instant = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    records = [{"b": 2, "a": 1}, {"a": 3, "b": 4}]
    path = store.write_raw("demo", instant, records)
    assert store.read_raw(path) == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]


def test_write_raw_is_byte_stable(tmp_path):
    store = FileStore(tmp_path)
    instant = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    records = [{"b": 2, "a": 1}]
    first = store.write_raw("demo", instant, records).read_bytes()
    second = store.write_raw("demo", instant, records).read_bytes()
    assert first == second


def test_latest_output_selection(tmp_path):
    store = FileStore(tmp_path)
    early = datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc)
    late = datetime(2026, 6, 2, 0, 0, tzinfo=timezone.utc)
    for instant in (early, late):
        path = store.output_path("test", "demo", instant)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("x", encoding="utf-8")
    assert store.latest_output("test", "demo").name == "2026-06-02-00-00.csv"
