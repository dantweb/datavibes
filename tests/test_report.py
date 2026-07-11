"""LLM-authored reports — deterministic profiling, report writing, SDK wiring.

The LLM is always a fake here (no network); the PDF is real (fpdf2). Tests write
only into tmp_path, never the tracked dataset tree.
"""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from datavibes import DatasetSDK
from datavibes.config.app_config import AppConfig, LlmConfig
from datavibes.config.loader import load_config
from datavibes.config.models import (
    ChartSpec,
    DatasetConfig,
    DatasetMetadata,
    SourceSpec,
    StepSpec,
)
from datavibes.context import FixedClock
from datavibes.report.charts import render_charts
from datavibes.report.html_pdf import charts_to_html, markdown_to_html
from datavibes.report.profile import build_profile
from datavibes.report.reporter import Reporter
from datavibes.schema.field import Field, Schema
from datavibes.store.filestore import FileStore

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = str(REPO_ROOT / "datasets" / "var" / "pdf" / "templates" / "report.html")

FIXED = FixedClock(datetime(2026, 6, 1, 0, 0, tzinfo=timezone.utc))


class FakeLlm:
    """A deterministic `LlmClient` — records prompts, returns canned Markdown."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, prompt: str) -> str:
        self.calls.append((system, prompt))
        kind = "Analytics" if "analyst" in system else "Statistical Works"
        return f"# {kind}\n\nMocked {kind.lower()} grounded in {prompt.count(chr(10))} lines."


def _config():
    schema = Schema(
        fields=[
            Field("region", "str"),
            Field("temp_c", "float", unit="C"),
        ]
    )
    return DatasetConfig(
        metadata=DatasetMetadata(
            slug="demo-weather",
            title="Demo Weather",
            category="environment",
            license="NOAA public domain",
            attribution="NOAA NCEI",
            update_frequency="daily",
        ),
        schema=schema,
        sources=[SourceSpec(type="static", options={})],
        processing=[
            StepSpec(name="normalize", options={}),
            StepSpec(name="aggregate", options={"by": ["region"], "metrics": {"temp_c": "mean"}}),
            StepSpec(name="validate", options={}),
        ],
    )


def _rows():
    return [
        {"region": "north", "temp_c": 10.0},
        {"region": "north", "temp_c": 20.0},
        {"region": "south", "temp_c": 30.0},
    ]


# ------------------------------------------------------------------- profiling
def test_profile_numeric_and_categorical():
    profile = build_profile(_config(), _rows())
    assert profile.row_count == 3
    by_name = {column.name: column for column in profile.columns}
    temp = by_name["temp_c"]
    assert temp.minimum == 10.0 and temp.maximum == 30.0
    assert temp.mean == pytest.approx(20.0)
    region = by_name["region"]
    assert region.distinct == 2
    assert region.top_values[0] == ("north", 2)


# --------------------------------------------------------------------- reporter
def test_reporter_writes_three_grounded_files(tmp_path):
    llm = FakeLlm()
    dataset_dir = tmp_path / "demo-weather"
    dataset_dir.mkdir()
    artifacts = Reporter(llm).generate(_config(), _rows(), dataset_dir, FIXED.now())

    assert artifacts.analytics_md == dataset_dir / "analytics.md"
    assert artifacts.statistics_md == dataset_dir / "statistics.md"
    assert artifacts.report_pdf == dataset_dir / "report.pdf"

    analytics = artifacts.analytics_md.read_text(encoding="utf-8")
    statistics = artifacts.statistics_md.read_text(encoding="utf-8")
    assert analytics.startswith("# Analytics")
    assert statistics.startswith("# Statistical Works")
    assert analytics != statistics

    # PDF is real (fpdf2), non-empty, and a valid PDF document.
    pdf_bytes = artifacts.report_pdf.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


def test_reporter_grounds_llm_in_real_numbers():
    llm = FakeLlm()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        Reporter(llm).generate(_config(), _rows(), Path(tmp), FIXED.now())
    # Both prompts must carry the computed profile (row count + a real stat).
    analytics_prompt = llm.calls[0][1]
    assert "Rows: 3" in analytics_prompt
    assert "mean=20" in analytics_prompt
    # The statistics prompt must also describe the processing steps.
    statistics_prompt = llm.calls[1][1]
    assert "aggregate" in statistics_prompt


# ------------------------------------------------------------------ sdk wiring
def _sdk(tmp_path, *, enabled: bool, llm):
    app_config = AppConfig(llm=LlmConfig(enabled=enabled))
    datasets_root = tmp_path / "datasets"
    datasets_root.mkdir()
    return DatasetSDK(
        root=datasets_root,
        clock=FIXED,
        store=FileStore(tmp_path),
        app_config=app_config,
        llm_factory=lambda _config: llm,
    )


def _scaffold_static(sdk):
    sdk.scaffold("demo", "test")  # a static-source dataset that runs offline


def test_run_generates_reports_into_output_dir_when_enabled(tmp_path):
    llm = FakeLlm()
    sdk = _sdk(tmp_path, enabled=True, llm=llm)
    _scaffold_static(sdk)
    sdk.run("demo")
    # Reports land in the OUTPUT folder (output/<slug>/), not the profile folder.
    output_dir = tmp_path / "output" / "demo"
    profile_dir = tmp_path / "datasets" / "demo"
    assert (output_dir / "analytics.md").is_file()
    assert (output_dir / "statistics.md").is_file()
    assert (output_dir / "report.pdf").read_bytes().startswith(b"%PDF")
    # The authored profile folder stays clean — no generated artifacts.
    assert not (profile_dir / "analytics.md").exists()
    assert llm.calls  # the LLM was actually consulted


def test_run_skips_reports_when_disabled(tmp_path):
    llm = FakeLlm()
    sdk = _sdk(tmp_path, enabled=False, llm=llm)
    _scaffold_static(sdk)
    sdk.run("demo")
    assert not (tmp_path / "output" / "demo" / "analytics.md").exists()
    assert llm.calls == []


def test_report_command_generates_regardless_of_flag(tmp_path):
    llm = FakeLlm()
    sdk = _sdk(tmp_path, enabled=False, llm=llm)  # disabled...
    _scaffold_static(sdk)
    sdk.run("demo")  # produces a raw snapshot to profile
    artifacts = sdk.report("demo")  # ...explicit command still generates
    assert artifacts.analytics_md.is_file()
    assert artifacts.report_pdf.read_bytes().startswith(b"%PDF")


# -------------------------------------------------------------- llm providers
def test_provider_dispatch_selects_client():
    from datavibes.config.app_config import LlmConfig
    from datavibes.report.llm import (
        AnthropicLlmClient,
        OpenAiLlmClient,
        default_llm_client,
    )

    assert isinstance(default_llm_client(LlmConfig(provider="anthropic")), AnthropicLlmClient)
    assert isinstance(default_llm_client(LlmConfig(provider="openai")), OpenAiLlmClient)


def test_unknown_provider_errors():
    from datavibes.config.app_config import LlmConfig
    from datavibes.errors import DatavibesError
    from datavibes.report.llm import default_llm_client

    with pytest.raises(DatavibesError):
        default_llm_client(LlmConfig(provider="cohere"))


def test_openai_client_calls_chat_completions(monkeypatch):
    from datavibes.config.app_config import LlmConfig
    from datavibes.report.llm import OpenAiLlmClient

    captured = {}

    class _Msg:
        content = "# Analytics\n\nDeepSeek says hi."

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _Resp()

    class FakeOpenAI:
        chat = type("chat", (), {"completions": FakeCompletions()})()

    config = LlmConfig(
        provider="openai",
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key_env="DEEPSEEK_API_KEY",
        max_tokens=1234,
    )
    client = OpenAiLlmClient(config)
    monkeypatch.setattr(client, "_ensure_client", lambda: FakeOpenAI())

    out = client.complete("SYS", "USER")
    assert out.startswith("# Analytics")
    assert captured["model"] == "deepseek-chat"
    assert captured["max_tokens"] == 1234
    roles = [m["role"] for m in captured["messages"]]
    assert roles == ["system", "user"]
    assert captured["messages"][0]["content"] == "SYS"


def test_reporter_works_with_any_llm_provider(tmp_path):
    # The reporter only sees the LlmClient protocol — provider is transparent.
    from datavibes.report.llm import OpenAiLlmClient

    assert hasattr(OpenAiLlmClient, "complete")
    artifacts = Reporter(FakeLlm(), template=TEMPLATE).generate(
        _config(), _rows(), tmp_path / "out", FIXED.now()
    )
    assert artifacts.report_pdf.read_bytes().startswith(b"%PDF")


# --------------------------------------------------------------------- charts
def test_chart_config_parses_from_dataset_yaml(tmp_path):
    (tmp_path / "dataset.yaml").write_text(
        """
metadata: { slug: c, title: C, category: x }
schema:
  - { name: country, dtype: str }
  - { name: value, dtype: float }
sources:
  - { type: static, records: [] }
charts:
  - { type: bar, title: "Top", x: country, y: value, sort: { by: value, desc: true }, limit: 5 }
  - { type: scatter, title: "Corr", x: value, y: value }
""",
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert len(config.charts) == 2
    assert config.charts[0].type == "bar" and config.charts[0].limit == 5
    assert config.charts[0].sort == {"by": "value", "desc": True}


def test_render_charts_writes_pngs(tmp_path):
    rows = [
        {"country": "north", "value": 10.0, "year": 2022},
        {"country": "north", "value": 30.0, "year": 2022},
        {"country": "south", "value": 20.0, "year": 2022},
    ]
    specs = [
        ChartSpec(type="bar", title="Top values", x="country", y="value",
                  sort={"by": "value", "desc": True}, limit=5),
        ChartSpec(type="scatter", title="Scatter", x="value", y="value"),
    ]
    images = render_charts(specs, rows, tmp_path / "charts")
    assert len(images) == 2
    for image in images:
        assert image.path.is_file()
        assert image.path.read_bytes()[:8].startswith(b"\x89PNG")


def test_bad_chart_is_skipped_not_fatal(tmp_path):
    specs = [ChartSpec(type="bar", title="Missing col", x="nope", y="alsonope")]
    images = render_charts(specs, [{"a": 1}], tmp_path / "charts")
    assert images == []  # skipped, no exception


def test_html_helpers():
    assert "<strong>" in markdown_to_html("**bold** text")
    assert charts_to_html([]) == ""


def test_reporter_embeds_charts_and_uses_html_template(tmp_path):
    config = _config()
    config.charts = [
        ChartSpec(type="bar", title="Mean temp by region", x="region", y="temp_c"),
    ]
    artifacts = Reporter(FakeLlm(), template=TEMPLATE).generate(
        config, _rows(), tmp_path / "out", FIXED.now()
    )
    # A chart PNG was rendered into charts/ and recorded on the artifacts.
    assert artifacts.charts and artifacts.charts[0].parent.name == "charts"
    assert artifacts.charts[0].read_bytes()[:8].startswith(b"\x89PNG")
    # The PDF is a real PDF (WeasyPrint template path).
    assert artifacts.report_pdf.read_bytes().startswith(b"%PDF")


def test_packaged_template_is_importable_resource():
    """The default template ships inside the package (so a pip-only install works)."""
    from importlib.resources import files

    resource = files("datavibes.report").joinpath("templates", "report.html")
    assert resource.is_file()
    assert "Dataset Intelligence Brief" in resource.read_text(encoding="utf-8")


def test_reporter_uses_packaged_template_by_default(tmp_path, monkeypatch):
    # Run from a directory with no working tree / no datasets/ folder at all.
    monkeypatch.chdir(tmp_path)
    # template="" => resolve the packaged default, not a filesystem path.
    artifacts = Reporter(FakeLlm(), template="").generate(
        _config(), _rows(), tmp_path / "out", FIXED.now()
    )
    pdf = artifacts.report_pdf.read_bytes()
    assert pdf.startswith(b"%PDF")
    # WeasyPrint (template) output is materially larger than the fpdf2 fallback.
    assert len(pdf) > 5000


def test_reporter_falls_back_when_template_missing(tmp_path):
    artifacts = Reporter(FakeLlm(), template=str(tmp_path / "nope.html")).generate(
        _config(), _rows(), tmp_path / "out", FIXED.now()
    )
    # Missing template → plain fpdf2 fallback still produces a valid PDF.
    assert artifacts.report_pdf.read_bytes().startswith(b"%PDF")


def test_run_survives_report_failure(tmp_path):
    class Boom:
        def complete(self, system, prompt):
            raise RuntimeError("llm down")

    sdk = _sdk(tmp_path, enabled=True, llm=Boom())
    _scaffold_static(sdk)
    # The data run must still succeed and return the snapshot path.
    path = sdk.run("demo")
    assert path.suffix == ".csv" and path.is_file()
