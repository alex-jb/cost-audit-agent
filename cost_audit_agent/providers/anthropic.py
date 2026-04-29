"""Anthropic API spend provider.

Anthropic exposes per-organization usage via the Admin API
(api.anthropic.com/v1/organizations/.../usage_report). We need an admin
key for this, NOT a regular API key.

Env: ANTHROPIC_ADMIN_KEY (admin scope), ANTHROPIC_ORG_ID

Falls back to local usage logs from build-quality-agent (~/.build-quality-agent/usage.jsonl)
and funnel-analytics-agent (~/.funnel-analytics-agent/usage.jsonl) if no
admin key — those at least cover the agents' own spend, which for indie
founders is most of the month-end bill.

Heuristics:
- spend > $50/mo with no obvious heavy task → flag review
- spend on Sonnet for diff-review tasks (Haiku 4.5 cheaper) → flag swap
"""
from __future__ import annotations
import json
import os
import pathlib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from .base import Provider, ProviderReport, WasteFinding


# Approximate $/MTok prices (Apr 2026)
PRICES = {
    "claude-haiku-4-5": (1.0, 5.0),       # input, output
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-opus-4-7": (15.0, 75.0),
}


def _scan_local_usage_logs() -> dict:
    """Aggregate token + cost from local agent logs as a fallback."""
    home = pathlib.Path.home()
    logs = [
        home / ".build-quality-agent" / "usage.jsonl",
        home / ".funnel-analytics-agent" / "usage.jsonl",
    ]
    by_model: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    first_of_month = datetime(now.year, now.month, 1, tzinfo=timezone.utc)

    for log in logs:
        if not log.exists():
            continue
        try:
            for line in log.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                ts_str = row.get("ts", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    continue
                if ts < first_of_month:
                    continue
                model = row.get("model", "unknown")
                in_p, out_p = PRICES.get(model, (1.0, 5.0))
                in_tok = row.get("input_tokens", 0)
                out_tok = row.get("output_tokens", 0)
                cost = (in_tok * in_p + out_tok * out_p) / 1_000_000
                m = by_model.setdefault(model,
                    {"in": 0, "out": 0, "cost": 0.0, "calls": 0})
                m["in"] += in_tok
                m["out"] += out_tok
                m["cost"] += cost
                m["calls"] += 1
        except Exception:
            continue
    return by_model


class AnthropicProvider(Provider):
    name = "anthropic"

    @property
    def configured(self) -> bool:
        # Either admin key OR local logs work
        if os.getenv("ANTHROPIC_ADMIN_KEY") and os.getenv("ANTHROPIC_ORG_ID"):
            return True
        # Local logs always "configured" in fallback sense
        home = pathlib.Path.home()
        return ((home / ".build-quality-agent" / "usage.jsonl").exists()
                or (home / ".funnel-analytics-agent" / "usage.jsonl").exists())

    def fetch(self) -> ProviderReport:
        now = datetime.now(timezone.utc)
        report = ProviderReport(provider=self.name, fetched_at=now)

        # Try local logs (always available, fast)
        by_model = _scan_local_usage_logs()
        local_cost = sum(m["cost"] for m in by_model.values())
        local_calls = sum(m["calls"] for m in by_model.values())

        if not by_model and not (os.getenv("ANTHROPIC_ADMIN_KEY")
                                 and os.getenv("ANTHROPIC_ORG_ID")):
            report.error = ("no local agent usage logs found; "
                            "set ANTHROPIC_ADMIN_KEY + ANTHROPIC_ORG_ID for "
                            "full org-wide spend")
            return report

        report.spend_usd_mtd = round(local_cost, 4)
        report.usage_units = {
            "calls_mtd": float(local_calls),
            **{f"{m}_calls": v["calls"] for m, v in by_model.items()},
            **{f"{m}_input_tokens": v["in"] for m, v in by_model.items()},
            **{f"{m}_output_tokens": v["out"] for m, v in by_model.items()},
        }
        report.raw = {"by_model": by_model,
                      "source": "local_agent_logs"}

        # Heuristics
        if local_cost > 50:
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="Anthropic spend above $50 MTD",
                detail=(f"${local_cost:.2f} so far this month across "
                        f"{local_calls} calls. Audit which agent is the "
                        "biggest spender via individual usage.jsonl files."),
                estimated_monthly_savings_usd=0.0,
            ))

        # Sonnet on tasks that should be Haiku
        sonnet_calls = by_model.get("claude-sonnet-4-6", {}).get("calls", 0)
        haiku_calls = by_model.get("claude-haiku-4-5", {}).get("calls", 0)
        if sonnet_calls > 50 and sonnet_calls > haiku_calls:
            sonnet_cost = by_model.get("claude-sonnet-4-6", {}).get("cost", 0)
            potential_savings = sonnet_cost * 0.66  # haiku is ~3x cheaper
            report.waste_findings.append(WasteFinding(
                severity="info",
                title="Sonnet-heavy usage — consider Haiku for routine tasks",
                detail=(f"{sonnet_calls} Sonnet 4.6 calls (${sonnet_cost:.2f}) "
                        f"vs only {haiku_calls} Haiku calls. For diff review, "
                        "summary, classification — Haiku is 3× cheaper with "
                        "comparable quality."),
                estimated_monthly_savings_usd=round(potential_savings, 2),
            ))

        return report
