"""Tests for the cost-audit MCP server tools.

`mcp` is an optional dep — skip the whole module if it's not installed.
We don't need a live MCP runtime; FastMCP's `@mcp.tool()` decorator wraps
each function in an object whose underlying callable is at `.fn`, so we
invoke that directly.
"""
from __future__ import annotations
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

mcp_available = True
try:
    from mcp.server.fastmcp import FastMCP  # noqa: F401
except ImportError:
    mcp_available = False

pytestmark = pytest.mark.skipif(not mcp_available,
                                  reason="mcp optional dep not installed")


@pytest.fixture
def mod():
    from cost_audit_agent import mcp_server
    return mcp_server


def _unset_all_provider_env(monkeypatch):
    """Strip every env var any provider might pick up, so all providers
    return error reports without making network calls."""
    for k in (
        "VERCEL_TOKEN", "VERCEL_TEAM_ID", "VERCEL_PROJECT_ID",
        "ANTHROPIC_API_KEY",
        "OPENPANEL_CLIENT_ID", "OPENPANEL_CLIENT_SECRET",
        "HYPERDX_API_KEY",
        "SUPABASE_PERSONAL_ACCESS_TOKEN", "SUPABASE_PROJECT_REF",
        "GITHUB_TOKEN", "GITHUB_REPO",
    ):
        monkeypatch.delenv(k, raising=False)


def test_get_monthly_report_renders_markdown(mod, monkeypatch):
    _unset_all_provider_env(monkeypatch)
    out = mod.get_monthly_report()
    # compose_report always emits a header
    assert "Cost audit" in out or "cost audit" in out.lower()


def test_get_provider_unknown(mod):
    out = mod.get_provider("nonexistent")
    assert "Unknown provider" in out
    assert "vercel" in out


def test_get_provider_unconfigured(mod, monkeypatch):
    _unset_all_provider_env(monkeypatch)
    out = mod.get_provider("vercel")
    assert "vercel" in out.lower()
    assert "unavailable" in out.lower()


def test_top_savings_no_findings(mod, monkeypatch):
    _unset_all_provider_env(monkeypatch)
    out = mod.top_savings()
    # All providers errored → no waste findings → lean message
    assert "lean" in out.lower() or "no waste" in out.lower()


def test_main_skips_when_skip_env_set(mod, monkeypatch):
    monkeypatch.setenv("COST_AUDIT_SKIP", "1")
    with patch.object(mod.mcp, "run") as fake_run:
        mod.main()
    fake_run.assert_not_called()


def test_mcp_instance_is_fastmcp(mod):
    from mcp.server.fastmcp import FastMCP
    assert isinstance(mod.mcp, FastMCP)
