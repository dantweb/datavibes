"""HTML-template → PDF rendering (WeasyPrint) for the professional report.

The report's prose (LLM Markdown) and charts (PNG data URIs) are slotted into
an HTML template — the default ships in ``datavibes/report/templates/report.html``
and is rendered to a PDF with WeasyPrint. Both ``markdown`` and ``weasyprint`` are optional; if
either is unavailable the reporter falls back to the plain fpdf2 renderer.
Charts are inlined as ``data:`` URIs so the PDF is self-contained.
"""

from __future__ import annotations

import base64
from pathlib import Path

from datavibes.report.charts import ChartImage


class HtmlPdfUnavailable(RuntimeError):
    """Raised when WeasyPrint (or its system libraries) can't render — triggers fallback."""


def markdown_to_html(text: str) -> str:
    """Render Markdown to HTML (tables + fenced code); plain-ish fallback if absent."""
    try:
        import markdown
    except ImportError:  # pragma: no cover - optional dependency
        escaped = text.replace("&", "&amp;").replace("<", "&lt;")
        return "<p>" + escaped.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    return markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])


def charts_to_html(images: list[ChartImage]) -> str:
    """Build the charts <section> with each PNG inlined as a data: URI."""
    if not images:
        return ""
    figures = []
    for image in images:
        data = base64.b64encode(Path(image.path).read_bytes()).decode("ascii")
        figures.append(
            f'<figure class="figure"><img src="data:image/png;base64,{data}" '
            f'alt="{_escape(image.title)}"><figcaption>{_escape(image.title)}'
            f"</figcaption></figure>"
        )
    return (
        '<section><h2>Charts</h2><hr class="rule">' + "".join(figures) + "</section>"
    )


def render_html_report(template_text: str, context: dict[str, str]) -> bytes:
    """Fill ``template_text`` placeholders and render to PDF bytes via WeasyPrint."""
    try:
        from weasyprint import HTML
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise HtmlPdfUnavailable("weasyprint not installed") from exc

    html = template_text
    for key, value in context.items():
        html = html.replace("{{" + key + "}}", value)
    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:  # missing pango/cairo etc. → let the caller fall back
        raise HtmlPdfUnavailable(str(exc)) from exc


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )
