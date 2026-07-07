"""S02–S05 — DatasetSDK facade + CLI shell (scaffold, validate, run, determinism)."""

from datetime import datetime, timezone

import pytest

from datavibes import DatasetSDK
from datavibes.cli import main
from datavibes.context import FixedClock
from datavibes.store.filestore import FileStore

FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))


def _sdk(tmp_path):
    root = tmp_path / "datasets"
    root.mkdir()
    return DatasetSDK(root=root, clock=FIXED, store=FileStore(tmp_path))


def test_new_scaffold_then_validate_round_trip(tmp_path):
    sdk = _sdk(tmp_path)
    sdk.scaffold("demo", "test")
    config = sdk.validate("demo")
    assert config.slug == "demo"


def test_run_writes_contract_path_and_is_byte_stable(tmp_path):
    sdk = _sdk(tmp_path)
    sdk.scaffold("demo", "test")
    first = sdk.run("demo")
    first_bytes = first.read_bytes()
    second = sdk.run("demo")
    assert first == second
    assert second.read_bytes() == first_bytes
    parts = first.parts
    assert parts[-1] == "2026-06-01-00-00.csv"
    assert parts[-2] == "demo"  # output/<slug>/<ts>.csv (slug layout)
    assert parts[-3] == "output"
    assert first.read_text(encoding="utf-8") == "city,value\nDemo,1\n"


def test_dataset_handle_latest(tmp_path):
    sdk = _sdk(tmp_path)
    sdk.scaffold("demo", "test")
    sdk.run("demo")
    rows = sdk.dataset("demo").latest()
    assert rows == [{"city": "Demo", "value": "1"}]


def test_list_reports_scaffolded_dataset(tmp_path):
    sdk = _sdk(tmp_path)
    sdk.scaffold("demo", "test")
    infos = sdk.list()
    assert [info.slug for info in infos] == ["demo"]


def test_cli_help_exits_zero(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--help"])
    assert info.value.code == 0


def test_cli_new_validate_run_flow(tmp_path, monkeypatch, capsys):
    root = str(tmp_path / "datasets")
    assert main(["--root", root, "new", "demo", "--category", "test"]) == 0
    assert main(["--root", root, "validate", "demo"]) == 0
    # run uses SystemClock by default but must still succeed and write a file.
    monkeypatch.chdir(tmp_path)
    assert main(["--root", root, "run", "demo"]) == 0
    out = capsys.readouterr().out
    assert "snapshot:" in out


def test_cli_unknown_dataset_returns_error(tmp_path, capsys):
    root = str(tmp_path / "datasets")
    (tmp_path / "datasets").mkdir()
    assert main(["--root", root, "validate", "ghost"]) == 1
