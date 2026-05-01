"""Tests for v0.3 providers: OpenPanel, HyperDX, Supabase, GitHub Actions."""
from __future__ import annotations
import json
import os
import sys
from unittest.mock import MagicMock, patch


sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cost_audit_agent.providers.openpanel import OpenPanelProvider
from cost_audit_agent.providers.hyperdx import HyperDXProvider
from cost_audit_agent.providers.supabase import SupabaseProvider
from cost_audit_agent.providers.github import GitHubActionsProvider


def _ok(payload: dict):
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


# ─── OpenPanelProvider ────────────────────────────────

def test_openpanel_unconfigured(monkeypatch):
    for k in ("OPENPANEL_PLAN", "OPENPANEL_CLIENT_ID"):
        monkeypatch.delenv(k, raising=False)
    assert OpenPanelProvider().configured is False


def test_openpanel_free_plan_has_zero_spend(monkeypatch):
    monkeypatch.setenv("OPENPANEL_PLAN", "free")
    r = OpenPanelProvider().fetch()
    assert r.spend_usd_mtd == 0.0
    assert r.subscription_cost_usd_monthly == 0.0


def test_openpanel_hobby_plan_flagged_for_review(monkeypatch):
    monkeypatch.setenv("OPENPANEL_PLAN", "hobby")
    r = OpenPanelProvider().fetch()
    assert r.subscription_cost_usd_monthly == 9.0
    assert any("Hobby" in f.title or "verify" in f.title.lower()
               for f in r.waste_findings)
    assert sum(f.estimated_monthly_savings_usd for f in r.waste_findings) == 9.0


def test_openpanel_unknown_plan_returns_error(monkeypatch):
    monkeypatch.setenv("OPENPANEL_PLAN", "platinum")
    r = OpenPanelProvider().fetch()
    assert r.error is not None
    assert "platinum" in r.error


# ─── HyperDXProvider ──────────────────────────────────

def test_hyperdx_unconfigured(monkeypatch):
    for k in ("HYPERDX_PLAN", "HYPERDX_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert HyperDXProvider().configured is False


def test_hyperdx_free_no_findings(monkeypatch):
    monkeypatch.setenv("HYPERDX_PLAN", "free")
    r = HyperDXProvider().fetch()
    assert r.spend_usd_mtd == 0.0
    assert r.waste_findings == []


def test_hyperdx_pro_flagged_with_savings(monkeypatch):
    monkeypatch.setenv("HYPERDX_PLAN", "pro")
    r = HyperDXProvider().fetch()
    assert r.subscription_cost_usd_monthly == 199.0
    assert any(f.severity == "warn" for f in r.waste_findings)
    assert any(f.estimated_monthly_savings_usd == 150.0
               for f in r.waste_findings)


# ─── SupabaseProvider ─────────────────────────────────

def test_supabase_unconfigured(monkeypatch):
    for k in ("SUPABASE_PLAN", "SUPABASE_PERSONAL_ACCESS_TOKEN",
              "SUPABASE_PROJECT_REF"):
        monkeypatch.delenv(k, raising=False)
    assert SupabaseProvider().configured is False


def test_supabase_free_plan(monkeypatch):
    monkeypatch.setenv("SUPABASE_PLAN", "free")
    r = SupabaseProvider().fetch()
    assert r.spend_usd_mtd == 0.0


def test_supabase_pro_with_advisor_critical(monkeypatch):
    """When advisor creds are set, hit the advisor endpoint and surface
    CRITICALs as a high-severity waste finding."""
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc")
    fake = _ok({"lints": [
        {"name": "auth_users_exposed", "level": "ERROR",
         "title": "User data exposed", "description": "..."},
    ]})
    with patch("urllib.request.urlopen", return_value=fake):
        r = SupabaseProvider().fetch()
    # Pro tier finding + CRITICAL advisor finding
    assert len(r.waste_findings) >= 2
    assert any(f.severity == "alert" and "CRITICAL" in f.title
               for f in r.waste_findings)


def test_supabase_advisor_endpoint_failure_doesnt_crash(monkeypatch):
    """If the advisor API fails, we still return the basic plan report."""
    monkeypatch.setenv("SUPABASE_PLAN", "pro")
    monkeypatch.setenv("SUPABASE_PERSONAL_ACCESS_TOKEN", "x")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc")
    with patch("urllib.request.urlopen", side_effect=Exception("network")):
        r = SupabaseProvider().fetch()
    assert r.error is None  # base plan info still there
    assert r.subscription_cost_usd_monthly == 25.0


def test_supabase_team_flagged(monkeypatch):
    monkeypatch.setenv("SUPABASE_PLAN", "team")
    r = SupabaseProvider().fetch()
    assert r.subscription_cost_usd_monthly == 599.0
    assert any(f.severity == "warn" for f in r.waste_findings)


# ─── GitHubActionsProvider ────────────────────────────

def test_github_unconfigured(monkeypatch):
    for k in ("GITHUB_TOKEN", "GITHUB_REPO"):
        monkeypatch.delenv(k, raising=False)
    r = GitHubActionsProvider().fetch()
    assert r.error is not None


def test_github_no_runs_no_overage(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    fake = _ok({"workflow_runs": []})
    with patch("urllib.request.urlopen", return_value=fake):
        r = GitHubActionsProvider().fetch()
    assert r.error is None
    assert r.spend_usd_mtd == 0.0
    assert r.usage_units["runs_mtd"] == 0


def test_github_overage_flagged(monkeypatch):
    """500 runs × 8min = 4000min, free plan = 2000 → 2000 overage = $16."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    monkeypatch.setenv("GITHUB_PLAN", "free")
    runs = [{"id": i, "created_at": "2026-04-15T00:00:00Z"} for i in range(500)]
    fake = _ok({"workflow_runs": runs})
    with patch("urllib.request.urlopen", return_value=fake):
        r = GitHubActionsProvider().fetch()
    assert r.error is None
    assert r.usage_units["runs_mtd"] == 500
    assert r.usage_units["overage_minutes"] == 2000
    # $0.008 * 2000 = $16
    assert r.usage_units["overage_cost_usd"] == 16.0
    assert any(f.severity == "alert" for f in r.waste_findings)


def test_github_pro_plan_higher_cap(monkeypatch):
    """Pro plan = 3000 free min. 250 runs × 8min = 2000 = no overage."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    monkeypatch.setenv("GITHUB_PLAN", "pro")
    runs = [{"id": i, "created_at": "2026-04-15T00:00:00Z"} for i in range(250)]
    fake = _ok({"workflow_runs": runs})
    with patch("urllib.request.urlopen", return_value=fake):
        r = GitHubActionsProvider().fetch()
    assert r.usage_units["overage_minutes"] == 0


def test_github_close_to_cap_warns(monkeypatch):
    """At >70% of cap, warn before hitting overage."""
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    # 200 runs × 8 = 1600 min, free cap = 2000 → 80%
    runs = [{"id": i, "created_at": "2026-04-15T00:00:00Z"} for i in range(200)]
    fake = _ok({"workflow_runs": runs})
    with patch("urllib.request.urlopen", return_value=fake):
        r = GitHubActionsProvider().fetch()
    assert any(f.severity == "warn" and "trending hot" in f.title
               for f in r.waste_findings)


def test_github_custom_avg_minutes(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    monkeypatch.setenv("GITHUB_AVG_MINUTES_PER_RUN", "20")
    runs = [{"id": 1}]
    fake = _ok({"workflow_runs": runs})
    with patch("urllib.request.urlopen", return_value=fake):
        r = GitHubActionsProvider().fetch()
    assert r.usage_units["estimated_minutes_mtd"] == 20


def test_github_api_failure_returns_error(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "x")
    monkeypatch.setenv("GITHUB_REPO", "alex-jb/test")
    with patch("urllib.request.urlopen", side_effect=Exception("dead")):
        r = GitHubActionsProvider().fetch()
    assert r.error is not None
