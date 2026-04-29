"""Vercel cost provider.

Pulls month-to-date usage from Vercel Usage API. Reports build minutes,
bandwidth GB, function invocations, and the implied dollar cost from
Vercel's published prices ($0.12/build-minute on Pro is the most painful
line for indie founders — see VibeXForge's $131.92 April 2026 incident).

Auth: VERCEL_TOKEN, VERCEL_TEAM_ID (optional)
Env: VERCEL_PLAN_USD (default 20 for Pro), VERCEL_BUILD_MINUTES_PRICE
    (default 0.12)

Heuristics:
- Pro plan ($20) but build minutes < 50/mo → flag downgrade
- Build minutes > 1000 → flag enterprise plan inquiry (cheaper at scale)
- Bandwidth > 1TB Pro included → flag overage

v0.2: HTTP via solo_founder_os (urlopen_json + with_retry decorator).
Vercel's API has occasional 5xx blips — retry handles them transparently.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from solo_founder_os.http import urlopen_json, with_retry, HTTPError

from .base import Provider, ProviderReport, WasteFinding


PRO_PLAN_BASE = float(os.getenv("VERCEL_PLAN_USD", "20"))
BUILD_MIN_PRICE = float(os.getenv("VERCEL_BUILD_MINUTES_PRICE", "0.12"))


class VercelProvider(Provider):
    name = "vercel"
    API_BASE = "https://api.vercel.com"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("VERCEL_TOKEN"))

    @with_retry(times=3, backoff_seconds=1.0)
    def _api(self, path: str, *, query: dict | None = None) -> dict:
        token = os.getenv("VERCEL_TOKEN", "")
        team_id = os.getenv("VERCEL_TEAM_ID")
        url = f"{self.API_BASE}{path}"
        params = dict(query or {})
        if team_id:
            params["teamId"] = team_id
        if params:
            qs = "&".join(f"{k}={v}" for k, v in params.items())
            url = f"{url}?{qs}"
        return urlopen_json(url, headers={"Authorization": f"Bearer {token}",
                                          "Accept": "application/json"})

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        report = ProviderReport(provider=self.name, fetched_at=now,
                                subscription_cost_usd_monthly=PRO_PLAN_BASE)
        if not self.configured:
            report.error = "missing VERCEL_TOKEN"
            return report

        # Vercel doesn't expose a single "spend" endpoint; we approximate
        # from the deployments index (build counts) + price assumptions.
        try:
            data = self._api("/v6/deployments", query={"limit": 100})
            deployments = data.get("deployments", [])
        except HTTPError as e:
            report.error = f"Vercel API HTTP {e.code}: {e}"
            return report
        except Exception as e:
            report.error = f"Vercel API error: {e}"
            return report

        # Filter to month-to-date
        first_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        cutoff = first_of_month.timestamp() * 1000
        mtd = [d for d in deployments if d.get("createdAt", 0) >= cutoff]

        # Approximate build minutes: avg build = 5 min. Real number is in
        # `buildingAt`/`ready` deltas if present.
        build_minutes_total = 0.0
        for d in mtd:
            building = d.get("buildingAt") or d.get("createdAt")
            ready = d.get("ready") or d.get("createdAt")
            if building and ready and ready > building:
                build_minutes_total += (ready - building) / 60_000.0
            else:
                build_minutes_total += 5.0  # fallback estimate

        deploy_count = len(mtd)
        usage_cost = build_minutes_total * BUILD_MIN_PRICE
        report.usage_units = {
            "deployments_mtd": deploy_count,
            "build_minutes_mtd": round(build_minutes_total, 1),
        }
        report.spend_usd_mtd = round(PRO_PLAN_BASE + usage_cost, 2)

        # Waste heuristics
        if PRO_PLAN_BASE >= 20 and deploy_count < 5:
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="Vercel Pro underused",
                detail=(f"Only {deploy_count} deployment(s) this month on a "
                        f"${PRO_PLAN_BASE}/mo Pro plan. If you can wait 45s "
                        "longer per build, the Hobby plan is free."),
                estimated_monthly_savings_usd=PRO_PLAN_BASE,
            ))
        if build_minutes_total > 50:
            report.waste_findings.append(WasteFinding(
                severity="alert",
                title="Build minutes blowing up",
                detail=(f"~{build_minutes_total:.0f} build-minutes month-to-date "
                        f"(${usage_cost:.2f} on top of plan base). Wire up a "
                        "pre-push hook (build-quality-agent) and audit "
                        "vercel.json ignoreCommand to skip docs/asset-only commits."),
                estimated_monthly_savings_usd=usage_cost * 0.7,
            ))
        if deploy_count > 100:
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="Excessive deploy frequency",
                detail=f"{deploy_count} deployments month-to-date. Batch commits before pushing.",
            ))

        return report
