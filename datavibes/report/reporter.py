"""``Reporter`` — turn a finished dataset into analytics.md + statistics.md +
charts/ + a professional report.pdf.

The reporter grounds the LLM in a deterministic :class:`DatasetProfile` (real
row counts and column stats), asks it for two prose sections — an *analytics*
read and a description of the *statistical works* — renders the dataset's
declared charts to ``charts/``, then composes a PDF from the HTML template
(WeasyPrint) with those charts embedded. If WeasyPrint/its libraries or the
template are unavailable it falls back to a plain fpdf2 PDF.

It depends only on the :class:`~datavibes.report.llm.LlmClient` protocol, so
tests inject a fake and touch no network.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from datavibes.config.models import DatasetConfig
from datavibes.report.charts import ChartImage, render_charts
from datavibes.report.html_pdf import (
    HtmlPdfUnavailable,
    charts_to_html,
    markdown_to_html,
    render_html_report,
)
from datavibes.report.llm import LlmClient
from datavibes.report.pdf import render_markdown_pdf
from datavibes.report.profile import DatasetProfile, build_profile

ANALYTICS_FILENAME = "analytics.md"
STATISTICS_FILENAME = "statistics.md"
REPORT_FILENAME = "report.pdf"
CHARTS_DIRNAME = "charts"
DEFAULT_TEMPLATE = "datasets/var/pdf/templates/report.html"

_ANALYTICS_SYSTEM = (
    "You are a data analyst. Given a factual profile of a generated dataset, "
    "write a concise analytics brief in Markdown: what the dataset covers, the "
    "most notable patterns and outliers in the numbers provided, and who would "
    "find it valuable. Use only the figures given — never invent values. "
    "Start with a top-level '# Analytics' heading."
)
_STATISTICS_SYSTEM = (
    "You are a data scientist documenting methodology. Given a dataset profile "
    "and its processing steps, describe the statistical work applied — the "
    "derivations, aggregations and metrics — in Markdown, and note the "
    "limitations of the approach. Use only what is provided. Start with a "
    "top-level '# Statistical Works' heading."
)
_META = (
    "Write for an audience deciding whether to buy or use this dataset. Keep it "
    "under ~400 words."
)


@dataclass
class ReportArtifacts:
    """Paths a report run writes."""

    analytics_md: Path
    statistics_md: Path
    report_pdf: Path
    charts: list[Path] = field(default_factory=list)


class Reporter:
    """Author per-dataset reports from a finished snapshot."""

    def __init__(
        self,
        llm: LlmClient,
        template: str = DEFAULT_TEMPLATE,
        charts_enabled: bool = True,
    ):
        self.llm = llm
        self.template = template
        self.charts_enabled = charts_enabled

    def generate(
        self,
        config: DatasetConfig,
        rows: list[dict],
        output_dir: Path,
        generated_at: datetime,
    ) -> ReportArtifacts:
        profile = build_profile(config, rows)
        profile_text = _render_profile(profile)
        steps_text = _render_steps(config)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Charts first — deterministic and LLM-independent, so they render even
        # when the model is unavailable.
        images: list[ChartImage] = []
        if self.charts_enabled and config.charts:
            images = render_charts(config.charts, rows, output_dir / CHARTS_DIRNAME)

        # Prose via the LLM, with a factual (profile-based) fallback so a model
        # outage still yields a complete report rather than nothing.
        analytics, statistics = self._author_prose(profile_text, steps_text)

        analytics_path = output_dir / ANALYTICS_FILENAME
        statistics_path = output_dir / STATISTICS_FILENAME
        report_path = output_dir / REPORT_FILENAME
        analytics_path.write_text(analytics + "\n", encoding="utf-8")
        statistics_path.write_text(statistics + "\n", encoding="utf-8")

        self._write_pdf(
            config, profile, generated_at, analytics, statistics, images, report_path
        )

        return ReportArtifacts(
            analytics_md=analytics_path,
            statistics_md=statistics_path,
            report_pdf=report_path,
            charts=[image.path for image in images],
        )

    def _author_prose(self, profile_text: str, steps_text: str) -> tuple[str, str]:
        try:
            analytics = self.llm.complete(_ANALYTICS_SYSTEM, f"{profile_text}\n\n{_META}\n")
            statistics = self.llm.complete(_STATISTICS_SYSTEM, f"{profile_text}\n\n{steps_text}\n")
            return analytics, statistics
        except Exception as error:  # model outage / no credits → factual fallback
            print(
                f"warning: LLM prose unavailable ({error}); writing a factual "
                "profile-only report instead",
                file=sys.stderr,
            )
            return (
                _fallback_prose("Analytics", profile_text),
                _fallback_prose("Statistical Works", f"{profile_text}\n\n{steps_text}"),
            )

    def _write_pdf(
        self, config, profile, generated_at, analytics, statistics, images, report_path
    ) -> None:
        sources_md = _render_sources(config)
        context = {
            "title": config.metadata.title,
            "category": config.category,
            "update_frequency": config.metadata.update_frequency or "n/a",
            "generated_at": generated_at.date().isoformat(),
            "rows": f"{profile.row_count:,}",
            "analytics_html": markdown_to_html(_strip_leading_h1(analytics)),
            "statistics_html": markdown_to_html(_strip_leading_h1(statistics)),
            "sources_html": markdown_to_html(sources_md),
            "charts_section": charts_to_html(images),
        }
        template_text = _read_template(self.template)
        if template_text is not None:
            try:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_bytes(render_html_report(template_text, context))
                return
            except HtmlPdfUnavailable as error:
                print(
                    f"warning: HTML/PDF renderer unavailable ({error}); "
                    "falling back to plain PDF",
                    file=sys.stderr,
                )
        # Fallback: plain fpdf2 PDF with charts appended.
        combined = _combine(config, generated_at, analytics, statistics, sources_md)
        render_markdown_pdf(
            f"{config.metadata.title} — Report",
            combined,
            report_path,
            images=[image.path for image in images],
        )


def _fallback_prose(heading: str, facts: str) -> str:
    """A deterministic, honest stand-in used when the LLM can't be reached."""
    bullets = "\n".join(line for line in facts.splitlines() if line.startswith("-"))
    return (
        f"# {heading}\n\n"
        "> _LLM narrative unavailable (model outage or missing credits). "
        "Re-run `datavibes report <slug>` to replace this with the "
        "model-authored brief._\n\n"
        "The dataset's computed profile:\n\n"
        f"{bullets}\n"
    )


def _read_template(template: str) -> str | None:
    path = Path(template)
    if path.is_file():
        return path.read_text(encoding="utf-8")
    print(f"warning: report template not found at {template}; using plain PDF", file=sys.stderr)
    return None


def _strip_leading_h1(markdown: str) -> str:
    lines = markdown.splitlines()
    if lines and lines[0].lstrip().startswith("# "):
        return "\n".join(lines[1:]).lstrip("\n")
    return markdown


def _render_profile(profile: DatasetProfile) -> str:
    lines = [
        f"Dataset: {profile.title} (slug: {profile.slug}, category: {profile.category})",
        f"Rows: {profile.row_count}",
        "Columns:",
    ]
    for column in profile.columns:
        unit = f" [{column.unit}]" if column.unit else ""
        head = f"- {column.name} ({column.dtype}){unit}: {column.non_null}/{column.count} non-null"
        if column.mean is not None:
            head += (
                f"; min={_fmt(column.minimum)} max={_fmt(column.maximum)} "
                f"mean={_fmt(column.mean)} median={_fmt(column.median)} "
                f"stdev={_fmt(column.stdev)}"
            )
        elif column.distinct is not None:
            top = ", ".join(f"{value} ({count})" for value, count in column.top_values)
            head += f"; distinct={column.distinct}; top: {top}"
        lines.append(head)
    return "\n".join(lines)


def _render_steps(config: DatasetConfig) -> str:
    if not config.processing:
        return "Processing steps: none."
    lines = ["Processing steps (in order):"]
    for spec in config.processing:
        options = f" {spec.options}" if spec.options else ""
        lines.append(f"- {spec.name}{options}")
    return "\n".join(lines)


def _render_sources(config: DatasetConfig) -> str:
    lines: list[str] = []
    if config.metadata.attribution:
        lines.append(f"- Attribution: {config.metadata.attribution}")
    if config.metadata.license:
        lines.append(f"- License: {config.metadata.license}")
    for spec in config.sources:
        lines.append(f"- Source adapter: `{spec.type}`")
    return "\n".join(lines) or "- (no sources declared)"


def _combine(config, generated_at, analytics, statistics, sources_md) -> str:
    header = (
        f"Dataset: {config.metadata.title}\n"
        f"Category: {config.category}  |  Update frequency: "
        f"{config.metadata.update_frequency or 'n/a'}\n"
        f"Generated: {generated_at.isoformat()}\n"
    )
    return "\n\n".join([header, analytics, statistics, "# Sources\n\n" + sources_md])


def _fmt(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{value:.4g}"
