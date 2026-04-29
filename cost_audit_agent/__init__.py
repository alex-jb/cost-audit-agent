"""cost-audit-agent — monthly bill audit across the SaaS stack indie founders use.

Solo Founder OS agent #11. Pulls usage + spend from Vercel, Anthropic,
OpenAI, Supabase, OpenPanel, HyperDX, GitHub Actions, and renders a
markdown report flagging:
- Total month-to-date spend per provider
- Underutilized SaaS (subscribed but ~0 usage)
- Cost spikes vs trailing 3-month average
- Specific waste recommendations (e.g. "you're on Pro at $20/mo but only
  used $1.40 of credits this month — drop to Free")

Designed for: monthly retro. Not real-time. Run on the 2nd of each month
via cron and read in Obsidian over coffee.
"""
__version__ = "0.2.0"
