"""OpenPanel cost provider.

OpenPanel's free tier covers up to 10k events/month per project. Beyond
that you're on Hobby ($9/mo, 100k events) or Pro ($29/mo, 500k events).

This provider is heuristic: OpenPanel does not (as of 2026-04) expose a
public REST API for project-level event counts. We can:
  - Hit the public SDK endpoint with the client ID to confirm the project
    exists and is "live" (no spend signal, just liveness).
  - If you provide an OPENPANEL_PLAN env var ("free" / "hobby" / "pro"),
    we use the published plan price as the monthly subscription.
  - Heuristic: if you've been on Hobby/Pro for 3 months but emit < 10k
    events/month (we can't measure this directly), flag it manually.

Auth (optional): OPENPANEL_CLIENT_ID. Plan: OPENPANEL_PLAN.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from .base import Provider, ProviderReport, WasteFinding


PLAN_PRICES = {
    "free": 0.0,
    "hobby": 9.0,
    "pro": 29.0,
}


class OpenPanelProvider(Provider):
    name = "openpanel"

    @property
    def configured(self) -> bool:
        # OPENPANEL_PLAN is enough to compute spend; client ID is optional.
        return bool(os.getenv("OPENPANEL_PLAN")) \
            or bool(os.getenv("OPENPANEL_CLIENT_ID"))

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        plan = (os.getenv("OPENPANEL_PLAN") or "free").lower()
        if plan not in PLAN_PRICES:
            report = ProviderReport(provider=self.name, fetched_at=now)
            report.error = (f"unknown OPENPANEL_PLAN={plan!r} "
                            f"(expected one of {list(PLAN_PRICES.keys())})")
            return report

        monthly = PLAN_PRICES[plan]
        report = ProviderReport(
            provider=self.name,
            fetched_at=now,
            subscription_cost_usd_monthly=monthly,
            spend_usd_mtd=monthly,  # SaaS subscriptions are MTD = full plan cost
            usage_units={"plan": plan},
        )

        if plan in ("hobby", "pro"):
            report.waste_findings.append(WasteFinding(
                severity="info",
                title="OpenPanel paid plan — verify event volume justifies it",
                detail=(
                    f"You're on {plan} (${monthly:.2f}/mo). Free tier covers "
                    "10k events/month. If your event count is below that "
                    "threshold (check at dashboard.openpanel.dev), drop to "
                    f"free — saves ${monthly:.2f}/mo."),
                estimated_monthly_savings_usd=monthly,
            ))
        return report
