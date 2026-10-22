"""Anomaly scanner: finds the metric movements worth explaining and names the slice behind each.

Deterministic, no model calls. See docs/architecture.md §6a and docs/sprints/12-anomaly-scanner.md.
"""

from app.scanner.attribution import SliceValues, attribute
from app.scanner.models import AnomalyCard, ScanReport
from app.scanner.scan import scan

__all__ = ["AnomalyCard", "ScanReport", "SliceValues", "attribute", "scan"]
