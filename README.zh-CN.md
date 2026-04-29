# cost-audit-agent

[English](README.md) | **中文**

> Solo Founder OS 第 11 个 agent —— 月度账单扫描,跑过独立开发者常用的 SaaS 一圈。标出闲置订阅、消费突增、和能省的具体美元数字。

[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](#)

作者 [Alex Ji](https://github.com/alex-jb)。诞生于这一句:

> *我订了 14 个 SaaS。完全不知道哪些用够本了。每月 2 号应该知道哪些值得继续付。*

## 它干什么

从每个 provider 拉月初至今的用量 + 消费,跑启发式规则,输出一份 markdown 报告,每条建议都带具体省钱数字:

```
## 🔍 浪费检测 —— 潜在月省:$42.00

- ⚠️ **[vercel]** Vercel Pro 用得不够(~$20.00/月)
  - 这个月就 3 次部署,但你在 $20/月 的 Pro。如果你能接受每次 build 多等 45 秒,
    Hobby plan 是免费的。

- 💡 **[anthropic]** Sonnet 用太多 —— 日常任务考虑切 Haiku(~$22.00/月)
  - 73 次 Sonnet 4.6($33.40)vs 只有 12 次 Haiku。Diff review、摘要、分类这种 ——
    Haiku 便宜 3 倍且质量相当。
```

## 安装

```bash
git clone https://github.com/alex-jb/cost-audit-agent.git
cd cost-audit-agent
pip install -e .
cp .env.example .env  # 填 VERCEL_TOKEN 等
```

## 使用

```bash
# 一次性报告到 stdout
cost-audit-agent

# 每月 2 号 cron 写到 Obsidian vault
cost-audit-agent --out ~/Documents/Obsidian/.../cost-$(date +%Y-%m).md

# 只看一个 provider
cost-audit-agent --provider vercel
```

## v0.1 数据源

| Provider | 读什么 | Auth |
|---|---|---|
| **vercel** | deployment 数量 + build-minute 估算 + Pro plan 基础费 | `VERCEL_TOKEN` |
| **anthropic** | 本地 agent 用量日志(`~/.build-quality-agent/usage.jsonl`、`~/.funnel-analytics-agent/usage.jsonl`);有 admin key 就读 org-wide | 可选 `ANTHROPIC_ADMIN_KEY` + `ANTHROPIC_ORG_ID` |

## 为什么 Anthropic 走本地日志降级

Anthropic 的 organization billing API 要 admin scope key,大部分独立开发者懒得创。但 build-quality-agent 和 funnel-analytics-agent 都把每次调用的 usage 写到 `~/.<agent>/usage.jsonl`。对跑 2-3 个 agent 的独立开发者来说,这些日志覆盖了 95% 的月度 Anthropic 消费。我们按月聚合,用公开的 Haiku/Sonnet/Opus 价格算成本。

## Roadmap

- [x] **v0.1** —— Vercel + Anthropic providers · markdown 报告 · 浪费启发式 · 14 tests
- [ ] **v0.2** —— OpenPanel, HyperDX, Supabase, GitHub Actions providers
- [ ] **v0.3** —— 3 个月滚动基线 · 突增检测
- [ ] **v0.4** —— Claude 写的 executive 摘要放报告顶部
- [ ] **v0.5** —— 一键取消按钮(月省 > $10 时 webhook 调 provider 取消端点,跟 vc-outreach 一样 HITL gated)

## 协议

MIT。
