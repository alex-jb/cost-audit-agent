"""GitHub Actions cost provider.

Public OSS repos get unlimited free Actions minutes. Private repos get
2000 free/month on the free GitHub plan, 3000 on Pro ($4/mo), more on
Team/Enterprise. Beyond the cap: $0.008/min for ubuntu-latest.

For indie founders, the typical waste pattern is:
- Private repo with heavy CI (matrix testing on push to main)
- Pushing 50+ times/month
- Each test run uses 5-10 min × 4 OS matrix × 4 Python = 160 min/push
- 50 pushes × 160 min = 8000 min/mo on a 2000-min plan = $48 overage

So the agent reads `actions/cache` + `runs` API to estimate MTD minutes
spent, then applies the formula.

Auth: GITHUB_TOKEN (a fine-grained PAT with read:actions on the repo)
      and GITHUB_REPO ("owner/repo" format).
Optional: GITHUB_PLAN ("free" / "pro" / "team" / "enterprise") for the
          baseline included minutes.
"""
from __future__ import annotations
import os
from datetime import datetime, timezone

from solo_founder_os.http import urlopen_json, with_retry, HTTPError

from .base import Provider, ProviderReport, WasteFinding


# Included minutes per plan
INCLUDED_MINUTES = {
    "free": 2000,
    "pro": 3000,
    "team": 3000,
    "enterprise": 50000,
}
OVERAGE_PRICE_PER_MIN = 0.008


class GitHubActionsProvider(Provider):
    name = "github_actions"

    @property
    def configured(self) -> bool:
        return bool(os.getenv("GITHUB_TOKEN")) and bool(os.getenv("GITHUB_REPO"))

    @with_retry(times=3, backoff_seconds=1.0)
    def _api(self, path: str) -> dict:
        token = os.getenv("GITHUB_TOKEN", "")
        return urlopen_json(
            f"https://api.github.com{path}",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        plan = (os.getenv("GITHUB_PLAN") or "free").lower()
        repo = os.getenv("GITHUB_REPO", "")
        included = INCLUDED_MINUTES.get(plan, 2000)

        report = ProviderReport(provider=self.name, fetched_at=now)
        if not self.configured:
            report.error = "missing GITHUB_TOKEN or GITHUB_REPO"
            return report

        # Pull workflow runs from start of month
        first_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        since_iso = first_of_month.isoformat()

        try:
            data = self._api(
                f"/repos/{repo}/actions/runs?per_page=100&created=>{since_iso}"
            )
            runs = data.get("workflow_runs", [])
        except HTTPError as e:
            report.error = f"GitHub HTTP {e.code}: check token + repo"
            return report
        except Exception as e:
            report.error = f"GitHub API error: {e}"
            return report

        # Estimate minutes — GitHub's billing API requires admin scope so we
        # estimate from run count × typical-test-job-minutes. Override via
        # GITHUB_AVG_MINUTES_PER_RUN if you know your real number.
        avg_per_run = float(os.getenv("GITHUB_AVG_MINUTES_PER_RUN", "8"))
        estimated_minutes = len(runs) * avg_per_run
        overage_minutes = max(0, estimated_minutes - included)
        overage_cost = overage_minutes * OVERAGE_PRICE_PER_MIN

        report.subscription_cost_usd_monthly = (
            0.0 if plan == "free" else (4.0 if plan == "pro" else 21.0))
        report.spend_usd_mtd = round(
            report.subscription_cost_usd_monthly + overage_cost, 2)
        report.usage_units = {
            "plan": plan,
            "runs_mtd": len(runs),
            "estimated_minutes_mtd": round(estimated_minutes),
            "included_minutes": included,
            "overage_minutes": round(overage_minutes),
            "overage_cost_usd": round(overage_cost, 2),
        }

        if overage_minutes > 0:
            report.waste_findings.append(WasteFinding(
                severity="alert",
                title=f"GitHub Actions overage: {overage_minutes:.0f} min over plan",
                detail=(
                    f"Estimated {estimated_minutes:.0f} min used vs {included} "
                    f"included ({plan} plan). Overage = ${overage_cost:.2f}. "
                    "Cuts: drop matrix dimensions (3 Python versions instead "
                    "of 4), gate workflows on changed paths, switch to "
                    "self-hosted runner for heavy CI."),
                estimated_monthly_savings_usd=overage_cost,
            ))
        elif estimated_minutes > 0.7 * included:
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title=f"GitHub Actions usage trending hot: {estimated_minutes:.0f}/{included}",
                detail=(
                    f"At current pace you'll hit the {plan} plan cap before "
                    "month-end. Consider reducing matrix dimensions now to "
                    "avoid overage charges later."),
                estimated_monthly_savings_usd=0.0,
            ))
        return report
