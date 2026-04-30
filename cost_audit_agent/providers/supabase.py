"""Supabase cost provider.

Supabase has a real billing API at api.supabase.com but it's gated behind
a personal access token + organization scope. Most indie founders don't
generate it. So this provider is hybrid:

- If SUPABASE_PERSONAL_ACCESS_TOKEN + SUPABASE_PROJECT_REF are set, hit
  /v1/projects/<ref>/billing for actual MTD spend.
- Otherwise: SUPABASE_PLAN env ("free" / "pro" / "team" / "enterprise")
  sets the subscription baseline.

Bonus signal — security advisor count. We hit the same advisors endpoint
the funnel-analytics-agent uses. CRITICAL advisors don't directly cost
money, but they're "tech debt that's about to cost money" — surface them
in the cost report so the founder sees a complete cost-of-ownership
picture.

Auth: SUPABASE_PERSONAL_ACCESS_TOKEN + SUPABASE_PROJECT_REF (full mode)
      or just SUPABASE_PLAN (heuristic mode).
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from solo_founder_os.http import urlopen_json, with_retry, HTTPError

from .base import Provider, ProviderReport, WasteFinding


PLAN_PRICES = {
    "free": 0.0,
    "pro": 25.0,
    "team": 599.0,
    "enterprise": 0.0,  # custom quote
}


class SupabaseProvider(Provider):
    name = "supabase"
    API_BASE = "https://api.supabase.com"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("SUPABASE_PLAN")) \
            or (bool(os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN"))
                and bool(os.getenv("SUPABASE_PROJECT_REF")))

    @with_retry(times=3, backoff_seconds=1.0)
    def _api(self, path: str) -> dict:
        token = os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "")
        return urlopen_json(
            f"{self.API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}",
                     "Accept": "application/json"},
        )

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        plan = (os.getenv("SUPABASE_PLAN") or "free").lower()
        if plan not in PLAN_PRICES:
            r = ProviderReport(provider=self.name, fetched_at=now)
            r.error = (f"unknown SUPABASE_PLAN={plan!r} "
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

        # Try to enrich with advisor count if creds present
        if (os.getenv("SUPABASE_PERSONAL_ACCESS_TOKEN")
                and os.getenv("SUPABASE_PROJECT_REF")):
            ref = os.getenv("SUPABASE_PROJECT_REF", "")
            try:
                data = self._api(f"/v1/projects/{ref}/advisors/security")
                lints = (data or {}).get("lints") or []
                if isinstance(lints, list):
                    crit = [l for l in lints if (l.get("level") or "").upper() == "ERROR"]
                    report.usage_units["advisor_critical_count"] = len(crit)
                    if crit:
                        report.waste_findings.append(WasteFinding(
                            severity="alert",
                            title=f"{len(crit)} CRITICAL Supabase advisor(s)",
                            detail=(
                                "Security advisors flag debt that becomes "
                                "expensive when exploited. Visit dashboard "
                                f"→ Advisors and resolve before launch. "
                                "Examples this incident: "
                                + ", ".join(l.get("name", "?") for l in crit[:3])),
                            estimated_monthly_savings_usd=0.0,
                        ))
            except (HTTPError, Exception):
                # Advisor enrichment is best-effort — don't fail the whole
                # provider if the advisor endpoint times out
                pass

        # Plan downgrade heuristic
        if plan == "pro":
            report.waste_findings.append(WasteFinding(
                severity="info",
                title="Supabase Pro — verify usage justifies it",
                detail=(
                    "Pro tier is $25/mo (8 GB DB, 250 GB egress, daily backups). "
                    "Free tier (500 MB / 5 GB / no backups) covers most "
                    "pre-traction apps. If your DB < 500 MB and you have "
                    "Vercel-side backups, drop to free — saves $25/mo."),
                estimated_monthly_savings_usd=25.0,
            ))
        elif plan == "team":
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="Supabase Team — only justified by SOC2 / point-in-time recovery",
                detail=(
                    "Team tier is $599/mo. Unless you NEED SOC2 certification "
                    "or point-in-time recovery for compliance, drop to Pro "
                    "saves $574/mo."),
                estimated_monthly_savings_usd=574.0,
            ))
        return report
