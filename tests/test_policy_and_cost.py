import pytest

from acs.guards.cost_guard import BudgetExceeded, BudgetGuard, UnknownPrice, estimate_video_cost
from acs.policy import load_policy, policy_hash


def test_policy_hash_ignores_key_order_but_not_values():
    a = {"x": 1, "y": {"b": 2, "a": 3}}
    b = {"y": {"a": 3, "b": 2}, "x": 1}
    assert policy_hash(a) == policy_hash(b)
    assert policy_hash(a) != policy_hash({**a, "x": 2})
    assert len(policy_hash(a)) == 12


def test_load_policy_by_name():
    p = load_policy("production_spec")
    assert p.name == "production_spec"
    assert p.data["episode"]["hard_max_s"] == 60


def test_15s_720p_costs_1_05(models_config):
    assert estimate_video_cost(15, "720p", models_config) == 1.05
    assert estimate_video_cost(45, "720p", models_config) == 3.15


def test_unverified_price_is_not_estimated(models_config):
    for resolution in ("360p", "1080p", "4k"):
        with pytest.raises(UnknownPrice):
            estimate_video_cost(15, resolution, models_config)


def test_budget_guard_blocks_before_spending():
    guard = BudgetGuard(2.00)
    guard.charge(1.05)
    with pytest.raises(BudgetExceeded):
        guard.charge(1.05)
    assert guard.spent_usd == 1.05          # 막힌 호출은 누적하지 않는다
    assert guard.remaining_usd == 0.95
