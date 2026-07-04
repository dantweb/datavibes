"""Processor + pure, individually testable processing steps."""

from datavibes.processing.processor import Processor

# Importing the steps module registers every built-in step (side effect).
from datavibes.processing import steps as _steps

_ = _steps

__all__ = ["Processor"]
