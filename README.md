# cost-audit-agent

**English** | [中文](README.zh-CN.md)

> Solo Founder OS agent #11 — monthly bill audit across the SaaS stack indie founders use. Flags underused subscriptions, spend spikes, and specific waste recommendations with estimated dollar savings.

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/cost-audit-agent.svg)](https://pypi.org/project/cost-audit-agent/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

Built by [Alex Ji](https://github.com/alex-jb). Born from this thought:

> *I'm subscribed to 14 SaaS tools. I have no idea which I actually use enough to justify. The 2nd of every month I should know exactly what's worth keeping.*

## What it does

Pulls month-to-date usage + spend from each provider, runs heuristics, outputs a markdown report with specific dollar-tagged recommendations:

```
## 🔍 Waste findings — potential savings: $42.00/mo

- ⚠️ **[vercel]** Vercel Pro underused (~$20.00/mo)
  - Only 3 deployment(s) this month on a $20.00/mo Pro plan. If you can wait 45s
    longer per build, the Hobby plan is free.

- 💡 **[anthropic]** Sonnet-heavy usage — consider Haiku for routine tasks (~$22.00/mo)
  - 73 Sonnet 4.6 calls ($33.40) vs only 12 Haiku calls. For diff review, summary,
    classification — Haiku is 3× cheaper with comparable quality.
```

## Install

```bash
git clone https://github.com/alex-jb/cost-audit-agent.git
cd cost-audit-agent
pip install -e .
cp .env.example .env  # fill in VERCEL_TOKEN etc.
```

## Usage

```bash
# One-shot report to stdout
cost-audit-agent

# Write to your Obsidian vault on the 2nd of each month (cron-friendly)
cost-audit-agent --out ~/Documents/Obsidian/.../cost-$(date +%Y-%m).md

# Limit to one provider
cost-audit-agent --provider vercel
```

## Providers (v0.1)

| Provider | What it reads | Auth |
|---|---|---|
| **vercel** | deployments + build-minute estimate + Pro-plan baseline | `VERCEL_TOKEN` |
| **anthropic** | local agent usage logs (`~/.build-quality-agent/usage.jsonl`, `~/.funnel-analytics-agent/usage.jsonl`); org-wide if admin key provided | optional `ANTHROPIC_ADMIN_KEY` + `ANTHROPIC_ORG_ID` |

## Why local-logs fallback for Anthropic

Anthropic's organization billing API requires an admin-scoped key, which most indie founders don't bother creating. But build-quality-agent and funnel-analytics-agent both write per-call usage to `~/.<agent>/usage.jsonl`. For a solo founder running 2-3 agents, those logs cover ~95% of monthly Anthropic spend. We aggregate them by month with the published Haiku/Sonnet/Opus prices.

## Roadmap

- [x] **v0.1** — Vercel + Anthropic providers · markdown report · waste heuristics · 14 tests
- [ ] **v0.2** — OpenPanel, HyperDX, Supabase, GitHub Actions providers
- [ ] **v0.3** — 3-month trailing baseline · spike detection
- [ ] **v0.4** — Claude-summarized executive narrative at top of report
- [ ] **v0.5** — Auto-cancel button (one-click webhook to provider's cancel endpoint when finding savings > $10/mo, gated by HITL like vc-outreach)

## License

MIT.
