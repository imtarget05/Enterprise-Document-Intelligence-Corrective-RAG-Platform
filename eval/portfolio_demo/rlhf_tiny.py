"""Local educational RLHF: pairwise reward model and one REINFORCE pass.

The policy is SmolLM2-135M-Instruct selecting A/B answers to synthetic policy
questions; this does not train a useful chatbot or enter the serving path.
Only the final transformer block is updated to fit an M1 Pro 16 GB machine.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer

MODEL_ID = "HuggingFaceTB/SmolLM2-135M-Instruct"
MODEL_REVISION = "12fd25f77366fa6b3b4b768ec3050bf629380bac"
DATASET = Path(__file__).with_name("rlhf_preferences.json")


def features(answer: str, evidence: str) -> torch.Tensor:
    """Inspectable reward features; no opaque LLM judge in this toy demo."""
    normalized = lambda text: set(text.lower().replace(".", "").split())
    evidence_terms = normalized(evidence) - {"policy:", "the", "a", "an", "is", "for"}
    answer_terms = normalized(answer.replace("[S1]", ""))
    overlap = len(evidence_terms & answer_terms) / max(1, len(evidence_terms))
    return torch.tensor([float("[S1]" in answer), overlap, len(answer.split()) / 20.0], dtype=torch.float32)


def train_reward_model(train: list[dict], seed: int) -> torch.nn.Linear:
    torch.manual_seed(seed)
    reward_model = torch.nn.Linear(3, 1)
    optimizer = torch.optim.Adam(reward_model.parameters(), lr=0.05)
    for _ in range(120):
        losses = []
        for item in train:
            chosen = reward_model(features(item["chosen"], item["evidence"]))
            rejected = reward_model(features(item["rejected"], item["evidence"]))
            losses.append(F.softplus(rejected - chosen))
        optimizer.zero_grad()
        torch.stack(losses).mean().backward()
        optimizer.step()
    reward_model.eval()
    return reward_model


def policy_prompt(item: dict, flip: bool) -> str:
    a, b = (item["rejected"], item["chosen"]) if flip else (item["chosen"], item["rejected"])
    return (
        f"Evidence: {item['evidence']}\nQuestion: {item['question']}\n"
        f"A: {a}\nB: {b}\nChoose the answer supported by evidence. Letter:"
    )


def option_scores(model, tokenizer, item: dict, flip: bool, device: str) -> torch.Tensor:
    inputs = tokenizer(policy_prompt(item, flip), return_tensors="pt", truncation=True, max_length=160)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    logits = model(**inputs).logits[0, -1]
    a_id = tokenizer.encode(" A", add_special_tokens=False)
    b_id = tokenizer.encode(" B", add_special_tokens=False)
    if len(a_id) != 1 or len(b_id) != 1:
        raise RuntimeError("A/B answer tokens must each be one token")
    return torch.stack([logits[a_id[0]], logits[b_id[0]]])


@torch.no_grad()
def evaluate(model, tokenizer, heldout: list[dict], device: str) -> dict:
    model.eval()
    correct = 0
    preferred_prob = 0.0
    for index, item in enumerate(heldout):
        flip = bool(index % 2)
        scores = option_scores(model, tokenizer, item, flip, device)
        target = 1 if flip else 0
        correct += int(scores.argmax().item() == target)
        preferred_prob += F.softmax(scores, dim=0)[target].item()
    return {"preferred_choice_accuracy": correct / len(heldout),
            "mean_preferred_probability": preferred_prob / len(heldout)}


def run(output: Path, seed: int = 42, device: str = "cpu") -> dict:
    if device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("MPS unavailable")
    random.seed(seed)
    torch.manual_seed(seed)
    data = json.loads(DATASET.read_text())
    train = [item for item in data if item["split"] == "train"]
    heldout = [item for item in data if item["split"] == "heldout"]
    reward_model = train_reward_model(train, seed)
    reward_ranking = sum(
        int(reward_model(features(row["chosen"], row["evidence"])) >
            reward_model(features(row["rejected"], row["evidence"])))
        for row in heldout
    ) / len(heldout)

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = AutoModelForCausalLM.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model.to(device)
    model.eval()
    before = evaluate(model, tokenizer, heldout, device)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    final_block = model.model.layers[-1]
    for parameter in final_block.parameters():
        parameter.requires_grad_(True)
    first_parameter = next(final_block.parameters())
    initial = first_parameter.detach().cpu().clone()
    optimizer = torch.optim.AdamW(final_block.parameters(), lr=1e-5)
    updates = []
    for index, item in enumerate(train):
        flip = bool(index % 2)
        model.train()
        scores = option_scores(model, tokenizer, item, flip, device)
        distribution = torch.distributions.Categorical(logits=scores)
        choice = distribution.sample()
        candidates = ([item["rejected"], item["chosen"]] if flip
                      else [item["chosen"], item["rejected"]])
        with torch.no_grad():
            rewards = torch.stack([
                reward_model(features(answer, item["evidence"])).squeeze()
                for answer in candidates
            ]).to(device)
            advantage = rewards[choice] - rewards.mean()
        loss = -advantage * distribution.log_prob(choice)
        optimizer.zero_grad()
        loss.backward()
        torch.nn.utils.clip_grad_norm_(final_block.parameters(), 1.0)
        optimizer.step()
        updates.append({"example": index, "chosen_arm": int(choice.item()),
                        "reward": float(rewards[choice].item()),
                        "advantage": float(advantage.item()), "loss": float(loss.item())})
    changed = float(torch.linalg.vector_norm(first_parameter.detach().cpu() - initial).item())
    after = evaluate(model, tokenizer, heldout, device)
    result = {
        "kind": "educational_synthetic_preference_policy_gradient",
        "model_id": MODEL_ID, "model_revision": MODEL_REVISION,
        "seed": seed, "device": device, "train_pairs": len(train), "heldout_pairs": len(heldout),
        "reward_model": "3-feature linear pairwise logistic ranking",
        "reward_heldout_pair_accuracy": reward_ranking,
        "policy_algorithm": "REINFORCE on A/B choice; final transformer block only",
        "learning_rate": 1e-5, "before": before, "after": after,
        "parameter_delta_l2": changed, "updates": updates,
        "limitations": "Synthetic labels and two-choice output; no production LLM quality claim.",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", choices=("cpu", "mps"), default="cpu")
    args = parser.parse_args()
    result = run(args.output, args.seed, args.device)
    print(json.dumps({k: v for k, v in result.items() if k != "updates"}, indent=2))


if __name__ == "__main__":
    main()
