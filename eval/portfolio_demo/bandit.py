"""Offline contextual-bandit routing demo over synthetic, read-only queries.

This module never imports or modifies the serving router. Outcomes are fully
specified fixtures, so the comparison is a simulation rather than evidence
that an online policy improves a real deployment.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

ARMS = ("rag", "agent")
CONTEXTS = ("simple", "complex")


@dataclass(frozen=True)
class Outcome:
    citation_correct: float
    latency_seconds: float
    cost_usd: float

    @property
    def reward(self) -> float:
        return self.citation_correct - 0.1 * self.latency_seconds - self.cost_usd


# Synthetic fixtures, not latency/cost measurements from the application.
OUTCOMES = {
    "simple": {"rag": Outcome(1.0, 0.3, 0.02), "agent": Outcome(1.0, 1.4, 0.08)},
    "complex": {"rag": Outcome(0.5, 0.3, 0.02), "agent": Outcome(0.9, 1.4, 0.08)},
}


class EpsilonGreedy:
    def __init__(self, epsilon: float = 0.2):
        if not 0 < epsilon < 1:
            raise ValueError("epsilon must be strictly between zero and one")
        self.epsilon = epsilon
        self.counts = {(ctx, arm): 0 for ctx in CONTEXTS for arm in ARMS}
        self.means = {(ctx, arm): 0.0 for ctx in CONTEXTS for arm in ARMS}

    def greedy_arm(self, context: str) -> str:
        if context not in CONTEXTS:
            raise ValueError(f"unknown context: {context}")
        return max(ARMS, key=lambda arm: (self.means[(context, arm)], -ARMS.index(arm)))

    def choose(self, context: str, rng: random.Random) -> tuple[str, float]:
        greedy = self.greedy_arm(context)
        arm = rng.choice(ARMS) if rng.random() < self.epsilon else greedy
        propensity = self.epsilon / len(ARMS) + (1 - self.epsilon if arm == greedy else 0)
        return arm, propensity

    def update(self, context: str, arm: str, reward: float) -> None:
        key = (context, arm)
        if key not in self.counts:
            raise ValueError("unknown context or arm")
        self.counts[key] += 1
        n = self.counts[key]
        self.means[key] += (reward - self.means[key]) / n


def run(seed: int = 42, training_events: int = 200, evaluation_events: int = 80) -> dict:
    if training_events < 20 or evaluation_events < 2:
        raise ValueError("training_events >= 20 and evaluation_events >= 2 required")
    rng = random.Random(seed)
    policy = EpsilonGreedy()
    log = []
    for i in range(training_events):
        context = CONTEXTS[i % len(CONTEXTS)]
        arm, propensity = policy.choose(context, rng)
        outcome = OUTCOMES[context][arm]
        policy.update(context, arm, outcome.reward)
        log.append({"event_id": i, "context": context, "action": arm,
                    "propensity": propensity, "outcome": asdict(outcome),
                    "reward": outcome.reward})

    # Held-out synthetic contexts; every arm's outcome is known by construction.
    # This is paired full-information evaluation, not an online A/B result.
    heldout = [CONTEXTS[i % len(CONTEXTS)] for i in range(evaluation_events)]
    learned = {ctx: policy.greedy_arm(ctx) for ctx in CONTEXTS}
    learned_reward = sum(OUTCOMES[ctx][learned[ctx]].reward for ctx in heldout) / len(heldout)
    rag_reward = sum(OUTCOMES[ctx]["rag"].reward for ctx in heldout) / len(heldout)
    return {
        "kind": "synthetic_offline_contextual_bandit", "seed": seed,
        "reward_formula": "citation_correct - 0.1*latency_seconds - cost_usd",
        "training_events": training_events, "evaluation_events": evaluation_events,
        "policy": learned, "learned_mean_reward": learned_reward,
        "always_rag_mean_reward": rag_reward,
        "observed_log": log,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    result = run(seed=args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "observed_log"}, indent=2))


if __name__ == "__main__":
    main()
