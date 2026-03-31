from __future__ import annotations


def assert_has_keys(obj: dict, required_keys: list[str]) -> None:
    missing = [k for k in required_keys if k not in obj]
    assert not missing, f"缺少字段: {missing}"


def assert_run_ev_engine_signature(target) -> None:
    import inspect

    sig = inspect.signature(target)
    params = list(sig.parameters.keys())
    assert params == ["state", "candidate_actions", "trigger_type"], (
        "run_ev_engine(...) 正式签名应为 "
        "(state, candidate_actions, trigger_type)"
    )


def assert_decision_card_is_pure_render(card: dict) -> None:
    assert "recommended_action" in card, "决策卡必须展示推荐动作"
    assert "summary" in card, "决策卡必须展示摘要"
    assert "reasons" in card, "决策卡必须展示理由"
    assert "primary_recommendation" in card, "决策卡必须展示主建议"
    assert "guardrails" in card, "决策卡必须展示边界条件"
    assert "execution_notes" in card, "决策卡必须展示执行说明"
    assert "trace_refs" in card, "决策卡必须展示追踪锚点"
