"""Abstract base for SaaS billing providers.

Each provider returns a ProviderReport with:
- spend_usd_mtd: month-to-date dollar spend
- usage_units: dict of provider-specific usage metrics
- subscription_cost_usd_monthly: flat monthly subscription baseline (if any)
- waste_findings: list of human-readable waste recommendations

Same graceful-degrade contract as funnel-analytics-agent: missing creds =
configured=False, network failure = ProviderReport with error set, never raises.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class WasteFinding:
    """One specific recommendation. Severity drives report ordering."""
    severity: str           # "info" | "warn" | "alert"
    title: str              # one-line headline
    detail: str             # 1-3 sentences with the why and the fix
    estimated_monthly_savings_usd: float = 0.0


@dataclass
class ProviderReport:
    """Output from one Provider.fetch() call."""
    provider: str
    fetched_at: datetime
    spend_usd_mtd: float = 0.0                      # month-to-date dollars
    subscription_cost_usd_monthly: float = 0.0      # flat plan cost (if any)
    usage_units: dict[str, float] = field(default_factory=dict)
                                                    # provider-specific metrics
    waste_findings: list[WasteFinding] = field(default_factory=list)
    error: Optional[str] = None
    raw: dict = field(default_factory=dict)         # for audit/debug


class Provider:
    """Subclass per SaaS. Implement fetch() to return a ProviderReport."""
    name: str = "base"

    @property
    def configured(self) -> bool:
        return True

    def fetch(self) -> ProviderReport:
        raise NotImplementedError
