from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: str | Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path} must decode to a JSON object"
    return data


def test_agent_tool_contracts_and_routing_exist_with_required_keys(repo_root: Path = Path('.').resolve()):
    # Tool contracts
    tool_contracts_path = repo_root / 'agent' / 'contracts' / 'tool_contracts.json'
    assert tool_contracts_path.exists(), f"missing {tool_contracts_path}"
    contracts = _load_json(tool_contracts_path)
    assert contracts.get('version') == 1
    tools = {t['name']: t for t in contracts.get('tools', [])}
    for name in (
        'frontdesk.onboarding',
        'frontdesk.followup.monthly',
        'frontdesk.status',
        'frontdesk.feedback',
        'frontdesk.approve_plan',
    ):
        assert name in tools, f"missing tool contract: {name}"
        assert isinstance(tools[name].get('inputs'), list)
        assert isinstance(tools[name].get('outputs'), list)

    # Skill routing
    routing_path = repo_root / 'agent' / 'routing' / 'skill_routing.json'
    assert routing_path.exists(), f"missing {routing_path}"
    routing = _load_json(routing_path)
    intents = routing.get('intents') or []
    assert any(i.get('tool') == 'frontdesk.onboarding' for i in intents)
    assert any(i.get('tool') == 'frontdesk.followup.monthly' for i in intents)

    # Source map and policies
    source_map_path = repo_root / 'agent' / 'source_map.json'
    assert source_map_path.exists(), f"missing {source_map_path}"
    source_map = _load_json(source_map_path)
    assert 'external_skills' in source_map
    assert 'openclaw' in {k.lower() for k in source_map.get('external_skills', {}).keys()}

    boundary_doc = repo_root / 'agent' / 'boundary.md'
    patch_policy = repo_root / 'agent' / 'patch_back_policy.md'
    playbook = repo_root / 'agent' / 'playbooks' / 'frontdesk_nli_playbook.md'
    assert boundary_doc.exists(), f"missing {boundary_doc}"
    assert patch_policy.exists(), f"missing {patch_policy}"
    assert playbook.exists(), f"missing {playbook}"


def test_openclaw_docs_exist(repo_root: Path = Path('.').resolve()):
    base = repo_root / 'integration' / 'openclaw'
    assert (base / 'README.md').exists()
    assert (base / 'contracts' / 'bridge_contract.md').exists()
    assert (base / 'config' / 'schema.json').exists()
    assert (base / 'acceptance.md').exists()

