"""Anthropic API spend provider.

Anthropic exposes per-organization usage via the Admin API
(api.anthropic.com/v1/organizations/.../usage_report). We need an admin
key for this, NOT a regular API key.

Env: ANTHROPIC_ADMIN_KEY (admin scope), ANTHROPIC_ORG_ID

Falls back to local usage logs from any solo-founder-os agent if no admin
key — those at least cover the agents' own spend, which for indie
founders is most of the month-end bill. Currently scans:
  ~/.build-quality-agent/usage.jsonl
  ~/.funnel-analytics-agent/usage.jsonl
  ~/.vc-outreach-agent/usage.jsonl
  ~/.customer-discovery-agent/usage.jsonl

Heuristics:
- spend > $50/mo with no obvious heavy task → flag review
- spend on Sonnet for diff-review tasks (Haiku 4.5 cheaper) → flag swap

v0.2: PRICES table now imported from solo-founder-os (single source of
truth across the agent stack — when prices change we update one place).
"""
from __future__ import annotations
import json
import os
import pathlib
from datetime import datetime, timezone

from solo_founder_os.usage_log import PRICES

from .base import Provider, ProviderReport, WasteFinding


# Agents whose ~/.<name>/usage.jsonl we scan in fallback mode. Add new
# agents here as they ship.
LOCAL_LOG_AGENTS = [
    ".build-quality-agent",
    ".funnel-analytics-agent",
    ".vc-outreach-agent",
    ".customer-discovery-agent",
]


def _scan_local_usage_logs() -> dict:
    """Aggregate token + cost from all solo-founder-os agent logs.

    Per-model dict tracks:
        in        — base input tokens (uncached)
        out       — output tokens
        cache_w   — cache_creation_input_tokens (5m TTL → 1.25× base price)
        cache_r   — cache_read_input_tokens (→ 0.10× base price)
        cost      — actual $ paid (with cache discount applied)
        cost_no_cache — what we'd have paid if cache hadn't been used
                        (used to compute realized savings)
        calls
    """
    home = pathlib.Path.home()
    logs = [home / agent_dir / "usage.jsonl" for agent_dir in LOCAL_LOG_AGENTS]
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
                cache_w = row.get("cache_creation_input_tokens", 0) or 0
                cache_r = row.get("cache_read_input_tokens", 0) or 0
                # Anthropic prompt-cache pricing (5m TTL):
                #   cache write = 1.25× base input
                #   cache read  = 0.10× base input
                cost = (
                    in_tok * in_p
                    + cache_w * in_p * 1.25
                    + cache_r * in_p * 0.10
                    + out_tok * out_p
                ) / 1_000_000
                cost_no_cache = (
                    (in_tok + cache_w + cache_r) * in_p
                    + out_tok * out_p
                ) / 1_000_000
                m = by_model.setdefault(model, {
                    "in": 0, "out": 0,
                    "cache_w": 0, "cache_r": 0,
                    "cost": 0.0, "cost_no_cache": 0.0,
                    "calls": 0,
                })
                m["in"] += in_tok
                m["out"] += out_tok
                m["cache_w"] += cache_w
                m["cache_r"] += cache_r
                m["cost"] += cost
                m["cost_no_cache"] += cost_no_cache
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
        return any((home / agent / "usage.jsonl").exists()
                   for agent in LOCAL_LOG_AGENTS)

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

        # Cache savings: $ we WOULD have paid without cache, minus what we did pay
        cost_no_cache = sum(m["cost_no_cache"] for m in by_model.values())
        cache_savings_realized = max(0.0, cost_no_cache - local_cost)
        total_cache_r = sum(m["cache_r"] for m in by_model.values())
        total_cache_w = sum(m["cache_w"] for m in by_model.values())
        total_input = sum(m["in"] for m in by_model.values())

        report.spend_usd_mtd = round(local_cost, 4)
        report.usage_units = {
            "calls_mtd": float(local_calls),
            **{f"{m}_calls": v["calls"] for m, v in by_model.items()},
            **{f"{m}_input_tokens": v["in"] for m, v in by_model.items()},
            **{f"{m}_output_tokens": v["out"] for m, v in by_model.items()},
        }
        if total_cache_r or total_cache_w:
            report.usage_units["cache_read_tokens"] = total_cache_r
            report.usage_units["cache_creation_tokens"] = total_cache_w
            report.usage_units["cache_savings_usd"] = round(cache_savings_realized, 4)
        report.raw = {"by_model": by_model,
                      "source": "local_agent_logs",
                      "cache_savings_usd": round(cache_savings_realized, 4)}

        # If cache is being used effectively, surface the win as an info finding
        if cache_savings_realized > 1.0:
            report.waste_findings.append(WasteFinding(
                severity="info",
                title=f"Prompt cache saving ~${cache_savings_realized:.2f}/mo",
                detail=(f"{total_cache_r:,} cached read tokens this month "
                        f"(at 10% of base input price). Without cache you'd "
                        f"have paid ${cost_no_cache:.2f} instead of "
                        f"${local_cost:.2f}. Keep cache_control=ephemeral on "
                        f"long stable prompts."),
                estimated_monthly_savings_usd=0.0,  # already realized, not future
            ))
        # Cache miss opportunity: lots of input tokens, zero cache fields seen
        elif total_input > 100_000 and total_cache_r == 0 and total_cache_w == 0:
            # Estimate: if we cached the system prompt portion (~30% of input
            # tokens, conservatively), and it got hit on 70% of calls, savings
            # = 0.30 × total_input × 0.70 × 0.90 × avg_in_price
            avg_in_p = sum(PRICES.get(m, (1.0, 5.0))[0] for m in by_model.keys())
            avg_in_p = avg_in_p / max(len(by_model), 1)
            est_savings = (total_input * 0.30 * 0.70 * 0.90 * avg_in_p) / 1_000_000
            report.waste_findings.append(WasteFinding(
                severity="warn",
                title="No prompt caching detected — leaving money on the table",
                detail=(f"{total_input:,} input tokens this month, but no "
                        f"cache hits/writes seen in any agent log. Adding "
                        f"`cache_control={{'type':'ephemeral'}}` to stable "
                        f"system prompts gives 90% off reads after 1st call "
                        f"in any 5-min window."),
                estimated_monthly_savings_usd=round(est_savings, 2),
            ))

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
