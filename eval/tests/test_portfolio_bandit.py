import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portfolio_demo.bandit import EpsilonGreedy, run


def test_logged_propensity_and_reproducibility():
    first = run(seed=42)
    assert first == run(seed=42)
    assert len(first["observed_log"]) == 200
    assert all(0 < row["propensity"] <= 1 for row in first["observed_log"])
    assert all(row["context"] in {"simple", "complex"} for row in first["observed_log"])


def test_policy_and_heldout_baseline_are_explicit():
    result = run(seed=42)
    assert result["policy"] == {"simple": "rag", "complex": "agent"}
    assert result["learned_mean_reward"] > result["always_rag_mean_reward"]


def test_invalid_context_fails_closed():
    policy = EpsilonGreedy()
    try:
        policy.greedy_arm("unknown")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown context must fail")
