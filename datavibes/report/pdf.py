"""Minimal Markdown-to-PDF rendering via ``fpdf2`` (optional dependency).

Not a full Markdown engine — it handles the subset the reports use: ATX
headings (``#``/``##``/``###``), ``-`` bullets, fenced code, and paragraphs.
``fpdf2`` core fonts are Latin-1, so text is transliterated to Latin-1 with a
few common Unicode punctuation replacements (em dash, curly quotes, arrows).
"""

from __future__ import annotations

from pathlib import Path

from datavibes.errors import DatavibesError

_REPLACEMENTS = {
    "—": "-", "–": "-", "‘": "'", "’": "'",
    "“": '"', "”": '"', "→": "->", "≥": ">=",
    "≤": "<=", "•": "-", "°": " deg", "€": "EUR",
}


def render_markdown_pdf(
    title: str, markdown: str, dest: Path, images: list[Path] | None = None
) -> Path:
    """Render ``markdown`` (+ optional chart ``images``) to a PDF at ``dest``.

    The dependency-free fallback used when the HTML/WeasyPrint path is
    unavailable — plainer than the template, but self-contained.
    """
    try:
        from fpdf import FPDF
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise DatavibesError(
            "PDF reports require the optional 'fpdf2' dependency; "
            "install it with: pip install 'datavibes[report]'"
        ) from exc

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_title(title)

    pdf.set_font("Helvetica", "B", 18)
    _write(pdf, _latin1(title), height=10)
    pdf.ln(2)

    for line in markdown.splitlines():
        _render_line(pdf, line)

    for image in images or []:
        pdf.ln(4)
        pdf.image(str(image), w=pdf.epw)

    dest.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(dest))
    return dest


def _render_line(pdf, line: str) -> None:
    stripped = line.rstrip()
    if not stripped:
        pdf.ln(3)
        return
    if stripped.startswith("### "):
        _heading(pdf, stripped[4:], size=12)
    elif stripped.startswith("## "):
        _heading(pdf, stripped[3:], size=14)
    elif stripped.startswith("# "):
        _heading(pdf, stripped[2:], size=16)
    elif stripped.lstrip().startswith(("- ", "* ")):
        pdf.set_font("Helvetica", "", 11)
        _write(pdf, _latin1(f"  - {stripped.lstrip()[2:]}"), height=6)
    else:
        pdf.set_font("Helvetica", "", 11)
        _write(pdf, _latin1(stripped), height=6)


def _heading(pdf, text: str, size: int) -> None:
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", size)
    _write(pdf, _latin1(text), height=8)


def _write(pdf, text: str, height: float) -> None:
    # Always start at the left margin and span the full text width, so a prior
    # cell that ended near the right edge can't starve the next line of space.
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(pdf.epw, height, text if text else " ")


def _latin1(text: str) -> str:
    for source, target in _REPLACEMENTS.items():
        text = text.replace(source, target)
    return text.encode("latin-1", "replace").decode("latin-1")
