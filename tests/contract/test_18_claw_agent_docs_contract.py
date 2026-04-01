from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.contract
def test_agent_and_openclaw_integration_docs_exist():
    repo = Path("/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1")
    required = [
        repo / "agent" / "AGENT_GUIDE.md",
        repo / "agent" / "TOOL_CONTRACTS.md",
        repo / "agent" / "SKILL_ROUTING.md",
        repo / "agent" / "PLAYBOOK_ADVISOR_FULL.md",
        repo / "agent" / "NATURAL_LANGUAGE_TASK_SURFACE.md",
        repo / "integration" / "openclaw" / "BOUNDARY.md",
        repo / "integration" / "openclaw" / "SOURCE_MAP.md",
        repo / "integration" / "openclaw" / "PATCH_BACK_POLICY.md",
    ]
    missing = [str(path) for path in required if not path.exists()]
    assert not missing, "missing docs: " + ", ".join(missing)


@pytest.mark.contract
def test_openclaw_source_map_points_to_real_external_assets():
    repo = Path("/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1")
    source_map = (repo / "integration" / "openclaw" / "SOURCE_MAP.md").read_text(encoding="utf-8")

    required_paths = [
        "/root/.openclaw/workspace/skills/memory-system/SKILL.md",
        "/root/.openclaw/workspace/skills/policy-news-search/SKILL.md",
        "/root/.openclaw/workspace/skills/policy-news-analysis/SKILL.md",
        "/root/.openclaw/workspace/CRON.md",
    ]
    for path in required_paths:
        assert path in source_map
        assert Path(path).exists()


@pytest.mark.contract
def test_patch_back_policy_declares_no_copy_rule():
    repo = Path("/root/AndyFtp/investment_system_codex_ready_repo/.worktrees/goal-solver-phase1")
    content = (repo / "integration" / "openclaw" / "PATCH_BACK_POLICY.md").read_text(encoding="utf-8")

    assert "不在本仓库存 fork 正文" in content
    assert "patch 回 OpenClaw 原路径" in content
