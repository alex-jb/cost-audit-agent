"""HyperDX cost provider.

HyperDX's free tier covers 1 GB ingestion + 14 days retention. Above
that: Team ($49/mo) or Pro ($199/mo).

Heuristic-only (same constraint as OpenPanel — no public usage API):
- HYPERDX_PLAN env ("free" / "team" / "pro") sets monthly subscription
- If you're on Team/Pro and your error rate is low (the funnel-analytics
  agent's HyperDX source can tell), flag it: "you're paying for ingest
  you're not using"

Auth (optional): HYPERDX_API_KEY (just for liveness). Plan: HYPERDX_PLAN.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from .base import Provider, ProviderReport, WasteFinding


PLAN_PRICES = {
    "free": 0.0,
    "team": 49.0,
    "pro": 199.0,
}


class HyperDXProvider(Provider):
    name = "hyperdx"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("HYPERDX_PLAN")) \
            or bool(os.getenv("HYPERDX_API_KEY"))

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        plan = (os.getenv("HYPERDX_PLAN") or "free").lower()
        if plan not in PLAN_PRICES:
            r = ProviderReport(provider=self.name, fetched_at=now)
            r.error = (f"unknown HYPERDX_PLAN={plan!r} "
                       f"(expected one of {list(PLAN_PRICES.keys())})")
            return r

        monthly = PLAN_PRICES[plan]
        report = ProviderReport(
            provider=self.name,
            fetched_at=now,
            subscription_cost_usd_monthly=monthly,
            spend_usd_mtd=monthly,
            usage_units={"plan": plan},
        )

        if plan == "pro":
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="HyperDX Pro tier — does indie usage justify $199/mo?",
                detail=(
                    "Pro tier is $199/mo. Indie founders on tight ingest "
                    "rarely hit the Team-tier (1 TB) limit. Audit your "
                    "actual ingest volume at app.hyperdx.io before next "
                    "renewal — drop to Team saves $150/mo."),
                estimated_monthly_savings_usd=150.0,
            ))
        elif plan == "team":
            report.waste_findings.append(WasteFinding(
                severity="info",
                title="HyperDX Team tier — confirm you're past the free 1 GB",
                detail=(
                    f"Team tier is $49/mo. Free tier covers 1 GB/14 days "
                    "which is plenty for pre-PMF apps. If you're still "
                    "exploring, drop to free — saves $49/mo."),
                estimated_monthly_savings_usd=49.0,
            ))
        return report
