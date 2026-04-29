"""Tests for provider classes — graceful degradation + waste heuristics."""
from __future__ import annotations
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from cost_audit_agent.providers.vercel import VercelProvider
from cost_audit_agent.providers.anthropic import AnthropicProvider, _scan_local_usage_logs


def _ok_response(payload: dict):
    fake = MagicMock()
    fake.read.return_value = json.dumps(payload).encode()
    fake.__enter__ = lambda s: s
    fake.__exit__ = lambda *a: None
    return fake


# ─── VercelProvider ───────────────────────────────────────────

def test_vercel_no_token(monkeypatch):
    monkeypatch.delenv("VERCEL_TOKEN", raising=False)
    r = VercelProvider().fetch()
    assert r.error is not None


def test_vercel_zero_deploys_flags_underuse(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    fake = _ok_response({"deployments": []})
    with patch("urllib.request.urlopen", return_value=fake):
        r = VercelProvider().fetch()
    assert r.error is None
    findings = [f.title for f in r.waste_findings]
    assert "Vercel Pro underused" in findings


def test_vercel_excessive_build_minutes_flags_alert(monkeypatch):
    """100 deployments at fallback 5min each = 500 build-minutes → alert."""
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    now = datetime.now(timezone.utc)
    deploys = [
        {"createdAt": now.replace(day=1).timestamp() * 1000 + i, "state": "READY"}
        for i in range(100)
    ]
    fake = _ok_response({"deployments": deploys})
    with patch("urllib.request.urlopen", return_value=fake):
        r = VercelProvider().fetch()
    assert any(f.severity == "alert" for f in r.waste_findings)
    assert any("blowing up" in f.title for f in r.waste_findings)


def test_vercel_api_error(monkeypatch):
    monkeypatch.setenv("VERCEL_TOKEN", "x")
    with patch("urllib.request.urlopen", side_effect=Exception("net")):
        r = VercelProvider().fetch()
    assert r.error is not None


# ─── AnthropicProvider — local logs path ──────────────────────

def test_anthropic_no_keys_no_logs_returns_error(monkeypatch, tmp_path):
    monkeypatch.delenv("ANTHROPIC_ADMIN_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_ORG_ID", raising=False)
    # Hijack home dir to tmp so no real logs are found
    monkeypatch.setenv("HOME", str(tmp_path))
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    r = AnthropicProvider().fetch()
    assert r.error is not None
    assert "no local agent usage logs" in r.error or "ANTHROPIC_ADMIN_KEY" in r.error


def test_anthropic_local_logs_aggregation(monkeypatch, tmp_path):
    """Drop a fake build-quality-agent usage.jsonl and verify it's read."""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    bqa_dir = tmp_path / ".build-quality-agent"
    bqa_dir.mkdir()
    log = bqa_dir / "usage.jsonl"

    now = datetime.now(timezone.utc).isoformat()
    log.write_text("\n".join([
        json.dumps({"ts": now, "model": "claude-haiku-4-5",
                    "input_tokens": 100, "output_tokens": 20,
                    "verdict": "PASS", "bytes": 0}),
        json.dumps({"ts": now, "model": "claude-haiku-4-5",
                    "input_tokens": 200, "output_tokens": 30,
                    "verdict": "PASS", "bytes": 0}),
    ]))

    r = AnthropicProvider().fetch()
    assert r.error is None
    # 300 input + 50 output Haiku = 300*1/M + 50*5/M = 0.000300 + 0.000250 = 0.000550
    assert r.spend_usd_mtd > 0
    assert r.usage_units["calls_mtd"] == 2


def test_anthropic_sonnet_heavy_flags_haiku_swap(monkeypatch, tmp_path):
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    fa_dir = tmp_path / ".funnel-analytics-agent"
    fa_dir.mkdir()
    log = fa_dir / "usage.jsonl"
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for _ in range(60):  # 60 sonnet calls > 50 threshold and > haiku
        rows.append(json.dumps({
            "ts": now, "model": "claude-sonnet-4-6",
            "input_tokens": 500, "output_tokens": 200,
        }))
    log.write_text("\n".join(rows))

    r = AnthropicProvider().fetch()
    assert any("Sonnet-heavy" in f.title for f in r.waste_findings)


def test_anthropic_old_logs_excluded(monkeypatch, tmp_path):
    """Logs from previous month should not count toward this month's spend."""
    import pathlib
    monkeypatch.setattr(pathlib.Path, "home", lambda: tmp_path)
    bqa_dir = tmp_path / ".build-quality-agent"
    bqa_dir.mkdir()
    log = bqa_dir / "usage.jsonl"
    # 2025 timestamp (old)
    log.write_text(json.dumps({
        "ts": "2025-12-15T10:00:00+00:00",
        "model": "claude-haiku-4-5",
        "input_tokens": 1_000_000, "output_tokens": 1_000_000,
    }))
    r = AnthropicProvider().fetch()
    # No this-month entries → no calls counted
    assert r.spend_usd_mtd == 0
