"""LLM-authored per-dataset reports (analytics.md + statistics.md + report.pdf).

The report layer is optional: it depends on the ``anthropic`` SDK (LLM) and
``fpdf2`` (PDF), both imported lazily so the core SDK works without them.
"""

from datavibes.report.reporter import ReportArtifacts, Reporter

__all__ = ["Reporter", "ReportArtifacts"]
