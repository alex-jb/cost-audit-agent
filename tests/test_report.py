"""Tests for report.compose_report — markdown rendering."""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cost_audit_agent.providers.base import ProviderReport, WasteFinding
from cost_audit_agent.report import compose_report


def _r(provider="x", spend=0.0, subs=0.0, units=None, findings=None, error=None):
    return ProviderReport(
        provider=provider,
        fetched_at=datetime.now(timezone.utc),
        spend_usd_mtd=spend,
        subscription_cost_usd_monthly=subs,
        usage_units=units or {},
        waste_findings=findings or [],
        error=error,
    )


def test_empty_renders_skeleton():
    text = compose_report([])
    assert "Cost Audit" in text
    assert "Total spend" in text
    assert "$0.00" in text


def test_findings_sorted_by_savings_desc():
    findings_a = [WasteFinding("warn", "Cheaper finding", "x", 5)]
    findings_b = [WasteFinding("warn", "Bigger finding", "y", 50)]
    text = compose_report([_r("a", findings=findings_a),
                            _r("b", findings=findings_b)])
    # Bigger appears before cheaper
    assert text.index("Bigger finding") < text.index("Cheaper finding")


def test_total_savings_summed():
    findings = [WasteFinding("warn", "f1", "x", 10),
                WasteFinding("info", "f2", "x", 20)]
    text = compose_report([_r("v", findings=findings)])
    assert "$30.00/mo" in text


def test_provider_breakdown_sorted_by_spend_desc():
    text = compose_report([_r("low", spend=5.0),
                            _r("high", spend=50.0),
                            _r("mid", spend=20.0)])
    assert text.index("### high") < text.index("### mid")
    assert text.index("### mid") < text.index("### low")


def test_failed_provider_listed_at_bottom():
    text = compose_report([_r("vercel", error="API down"),
                            _r("anthropic", spend=2.0)])
    assert "Providers unavailable" in text
    assert "API down" in text
    assert "vercel" in text


def test_total_spend_excludes_failed():
    text = compose_report([_r("a", spend=10.0),
                            _r("b", spend=999.0, error="missing key")])
    # Only $10 counted
    assert "**MTD spend across stack:** $10.00" in text
