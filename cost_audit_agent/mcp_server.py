"""MCP (Model Context Protocol) server for cost-audit-agent.

Lets you query monthly bill state from Claude Desktop / Cursor / Zed
without leaving the AI assistant.

Tools exposed:
  - get_monthly_report() → full markdown bill audit across all configured providers
  - get_provider(name)   → single provider's spend + waste findings
  - top_savings()        → just the top 5 highest-savings waste findings,
                           sorted by estimated $/mo

Install:
    pip install cost-audit-agent[mcp]

Wire to Claude Desktop:

    {
      "mcpServers": {
        "cost-audit": {
          "command": "cost-audit-mcp",
          "env": {
            "VERCEL_TOKEN": "...",
            "VERCEL_PLAN_USD": "20",
            "SUPABASE_PLAN": "free",
            "GITHUB_TOKEN": "...",
            ...
          }
        }
      }
    }
"""
from __future__ import annotations
import os
import sys
from datetime import datetime, timezone

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    print("cost-audit-mcp requires the `mcp` package. "
          "Install with: pip install 'cost-audit-agent[mcp]'",
          file=sys.stderr)
    raise SystemExit(1) from e

from .providers import (
    VercelProvider, AnthropicProvider,
    OpenPanelProvider, HyperDXProvider,
    SupabaseProvider, GitHubActionsProvider,
)
from .providers.base import Provider, ProviderReport
from .report import compose_report


ALL_PROVIDERS: dict[str, type[Provider]] = {
    "vercel": VercelProvider,
    "anthropic": AnthropicProvider,
    "openpanel": OpenPanelProvider,
    "hyperdx": HyperDXProvider,
    "supabase": SupabaseProvider,
    "github_actions": GitHubActionsProvider,
}


mcp = FastMCP("cost-audit")


def _fetch_all() -> list[ProviderReport]:
    reports = []
    for name, cls in ALL_PROVIDERS.items():
        try:
            reports.append(cls().fetch())
        except Exception as e:
            reports.append(ProviderReport(
                provider=name,
                fetched_at=datetime.now(timezone.utc),
                error=f"unhandled: {e}",
            ))
    return reports


@mcp.tool()
def get_monthly_report() -> str:
    """Generate the cost-audit monthly report — the full markdown bill
    audit across Vercel, Anthropic, OpenPanel, HyperDX, Supabase, and
    GitHub Actions.

    Returns: markdown report with total $ MTD, sorted waste findings,
    per-provider breakdown.
    """
    reports = _fetch_all()
    return compose_report(reports)


@mcp.tool()
def get_provider(name: str) -> str:
    """Run a single billing provider and return its findings as markdown.

    Args:
        name: one of vercel, anthropic, openpanel, hyperdx, supabase,
              github_actions.

    Returns: markdown summary for that one provider.
    """
    cls = ALL_PROVIDERS.get(name)
    if cls is None:
        avail = ", ".join(ALL_PROVIDERS.keys())
        return f"Unknown provider: {name!r}. Available: {avail}"
    try:
        r = cls().fetch()
    except Exception as e:
        return f"Provider {name!r} failed: {e}"
    if r.error:
        return f"**{name}** unavailable: {r.error}"
    out = [f"## {name}", ""]
    out.append(f"- MTD spend: ${r.spend_usd_mtd:.2f}")
    if r.subscription_cost_usd_monthly:
        out.append(f"- Subscription: ${r.subscription_cost_usd_monthly:.2f}/mo")
    for k, v in r.usage_units.items():
        out.append(f"- {k}: {v}")
    if r.waste_findings:
        out.append("")
        out.append("### Waste findings")
        for f in r.waste_findings:
            saving = (f" (~${f.estimated_monthly_savings_usd:.2f}/mo)"
                      if f.estimated_monthly_savings_usd else "")
            out.append(f"- **{f.title}**{saving}")
            out.append(f"  - {f.detail}")
    return "\n".join(out)


@mcp.tool()
def top_savings(n: int = 5) -> str:
    """Return the top N waste findings across all providers, sorted by
    estimated monthly $ savings.

    Args:
        n: how many findings to return (default 5).

    Returns: markdown list of top findings with provider tag + $ saving.
    """
    reports = _fetch_all()
    flat: list = []
    for r in reports:
        for f in r.waste_findings:
            flat.append((r.provider, f))
    flat.sort(key=lambda x: -x[1].estimated_monthly_savings_usd)
    flat = flat[:n]
    if not flat:
        return "No waste findings — your stack is lean."
    total_savings = sum(f.estimated_monthly_savings_usd for _, f in flat)
    out = [f"## Top {len(flat)} potential savings — ~${total_savings:.2f}/mo total",
           ""]
    for provider, f in flat:
        saving = f" (~${f.estimated_monthly_savings_usd:.2f}/mo)" if f.estimated_monthly_savings_usd else ""
        out.append(f"- **[{provider}]** {f.title}{saving}")
        out.append(f"  - {f.detail}")
    return "\n".join(out)


def main() -> None:
    """Console-script entry point. Runs the MCP server over stdio."""
    if os.getenv("COST_AUDIT_SKIP") == "1":
        return
    mcp.run()


if __name__ == "__main__":
    main()
