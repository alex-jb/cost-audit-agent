"""CLI entry — cost-audit-agent.

Designed to run on the 2nd of each month (cron) and dump the report to
your Obsidian vault. Run manually any time too.

    cost-audit-agent                                # print to stdout
    cost-audit-agent --out ~/.../cost-2026-04.md   # write to file
    cost-audit-agent --provider vercel              # one provider only

Bypass: COST_AUDIT_SKIP=1 makes the agent a no-op.
"""
from __future__ import annotations
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

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


def main(argv: list[str] | None = None) -> int:
    if os.getenv("COST_AUDIT_SKIP") == "1":
        return 0

    p = argparse.ArgumentParser(
        prog="cost-audit-agent",
        description="Monthly bill audit across the indie SaaS stack.",
    )
    p.add_argument("--provider", action="append", default=None,
                   choices=list(ALL_PROVIDERS.keys()),
                   help="Limit to specific provider(s); default: all configured")
    p.add_argument("--out", default=None,
                   help="Write report to file instead of stdout")
    p.add_argument("--title", default=None,
                   help="Custom report title")
    args = p.parse_args(argv)

    selected = args.provider or list(ALL_PROVIDERS.keys())
    providers = [ALL_PROVIDERS[name]() for name in selected]
    reports: list[ProviderReport] = []
    for provider in providers:
        try:
            reports.append(provider.fetch())
        except Exception as e:
            reports.append(ProviderReport(
                provider=provider.name,
                fetched_at=datetime.now(timezone.utc),
                error=f"unhandled: {e}",
            ))

    text = compose_report(reports, title=args.title)
    if args.out:
        Path(args.out).write_text(text)
        print(f"✓ report written to {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
