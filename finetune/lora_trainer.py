#!/usr/bin/env python3
"""LoRA Fine-tuning Pipeline for Vietnamese Legal Q&A.

Loads a base causal-LLM, applies PEFT/LoRA adapters, trains on JSONL
(instruction, input, output) data, evaluates perplexity on a validation set,
and saves the adapter weights.

Gracefully degrades when peft/transformers are unavailable — the module
can still be imported for data-path helpers and config validation.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Optional

# ---------------------------------------------------------------------------
# Optional heavy imports — graceful fallback
# ---------------------------------------------------------------------------
try:
    import torch
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    PEFT_AVAILABLE = True
except ImportError:
    PEFT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_BASE_MODEL = os.getenv("LORA_BASE_MODEL", "Qwen/Qwen2.5-1.5B-Instruct")
DEFAULT_LORA_R = int(os.getenv("LORA_R", "8"))
DEFAULT_LORA_ALPHA = int(os.getenv("LORA_ALPHA", "32"))
DEFAULT_LORA_DROPOUT = float(os.getenv("LORA_DROPOUT", "0.05"))
DEFAULT_LORA_TARGET_MODULES = os.getenv(
    "LORA_TARGET_MODULES", "q_proj,k_proj,v_proj,o_proj,gate_proj,up_proj,down_proj"
).split(",")
EVAL_INTERVAL_STEPS = int(os.getenv("LORA_EVAL_STEPS", "50"))

# Safe torch.cuda check (may not be installed)
def _torch_cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False



def load_jsonl(path: str | Path) -> list[dict]:
    """Read a JSONL file — one JSON object per line."""
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def format_row(row: dict, tokenizer: Any) -> dict:
    """Turn a raw JSONL row into a single tokenised text field.

    Expected row schema (all keys optional except `instruction`):
        instruction: system prompt / task description
        input:       user content
        output:       assistant content
    Falls back to `messages` (list of {role, content}) when present.
    """
    if "messages" in row:
        text = tokenizer.apply_chat_template(
            row["messages"], tokenize=False, add_generation_prompt=False
        )
    else:
        parts: list[str] = []
        if row.get("instruction"):
            parts.append(f"### Instruction:\n{row['instruction']}\n")
        if row.get("input"):
            parts.append(f"### Input:\n{row['input']}\n")
        if row.get("output"):
            parts.append(f"### Response:\n{row['output']}\n")
        text = "\n".join(parts)
    return {"text": text}


class LoRATrainer:
    """Train a LoRA adapter on top of a base causal language model.

    Usage::

        trainer = LoRATrainer(
            base_model="Qwen/Qwen2.5-1.5B-Instruct",
            train_path="finetune/data/train.jsonl",
            valid_path="finetune/data/valid.jsonl",
            output_dir="finetune/adapters/lora-t4",
        )
        trainer.train(num_train_epochs=3, per_device_train_batch_size=2)
        trainer.save()
    """

    def __init__(
        self,
        base_model: str = DEFAULT_BASE_MODEL,
        train_path: str | Path = "finetune/data/train.jsonl",
        valid_path: str | Path = "finetune/data/valid.jsonl",
        output_dir: str | Path = "finetune/adapters/lora-t4",
        lora_r: int = DEFAULT_LORA_R,
        lora_alpha: int = DEFAULT_LORA_ALPHA,
        lora_dropout: float = DEFAULT_LORA_DROPOUT,
        lora_target_modules: Optional[Iterable[str]] = None,
        max_length: int = int(os.getenv("LORA_MAX_LENGTH", "1024")),
        use_8bit: bool = os.getenv("LORA_8BIT", "false").lower() == "true",
        device_map: str | None = "auto",
    ):
        if not PEFT_AVAILABLE:
            raise RuntimeError(
                "peft and transformers are required for LoRA training. "
                "Install with: pip install peft transformers torch"
            )
        self.base_model_name = base_model
        self.train_path = Path(train_path)
        self.valid_path = Path(valid_path)
        self.output_dir = Path(output_dir)
        self.max_length = max_length
        self.use_8bit = use_8bit
        self.device_map = device_map

        self.lora_config = LoraConfig(
            r=lora_r,
            lora_alpha=lora_alpha,
            lora_dropout=lora_dropout,
            target_modules=list(lora_target_modules or DEFAULT_LORA_TARGET_MODULES),
            bias="none",
            task_type=TaskType.CAUSAL_LM,
        )

        self.tokenizer: Any = None
        self.model: Any = None
        self.trainer: Any = None

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def _tokenize(self, row: dict) -> dict:
        text = format_row(row, self.tokenizer)["text"]
        enc = self.tokenizer(
            text,
            truncation=True,
            max_length=self.max_length,
            padding="max_length",
        )
        enc["labels"] = enc["input_ids"].copy()
        return enc

    def _load_dataset(self):
        train_rows = load_jsonl(self.train_path)
        valid_rows = load_jsonl(self.valid_path) if self.valid_path.exists() else []

        train_enc = [self._tokenize(r) for r in train_rows]
        valid_enc = [self._tokenize(r) for r in valid_rows]

        return train_enc, valid_enc

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------
    def _load_model(self):
        self.tokenizer = AutoTokenizer.from_pretrained(self.base_model_name)
        if self.tokenizer.pad_token is None:
            self.tokenizer.pad_token = self.tokenizer.eos_token

        load_kwargs: dict[str, Any] = {"device_map": self.device_map}
        if self.use_8bit:
            load_kwargs["load_in_8bit"] = True

        self.model = AutoModelForCausalLM.from_pretrained(
            self.base_model_name, **load_kwargs
        )
        if self.use_8bit:
            self.model = prepare_model_for_kbit_training(self.model)
        self.model = get_peft_model(self.model, self.lora_config)
        self.model.print_trainable_parameters()

    # ------------------------------------------------------------------
    # Training
    # ------------------------------------------------------------------
    def train(
        self,
        num_train_epochs: int = 3,
        per_device_train_batch_size: int = 2,
        gradient_accumulation_steps: int = 4,
        learning_rate: float = 2e-4,
        warmup_steps: int = 50,
        logging_steps: int = 10,
        save_steps: int = 100,
        eval_strategy: str = "steps",
        eval_steps: int = EVAL_INTERVAL_STEPS,
        fp16: bool = _torch_cuda_available(),
        report_to: str = "none",
    ):
        self._load_model()
        train_data, valid_data = self._load_dataset()

        self.output_dir.mkdir(parents=True, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=str(self.output_dir),
            num_train_epochs=num_train_epochs,
            per_device_train_batch_size=per_device_train_batch_size,
            gradient_accumulation_steps=gradient_accumulation_steps,
            learning_rate=learning_rate,
            warmup_steps=warmup_steps,
            logging_steps=logging_steps,
            save_steps=save_steps,
            eval_strategy=eval_strategy if valid_data else "no",
            eval_steps=eval_steps if valid_data else None,
            fp16=fp16,
            report_to=report_to,
            save_total_limit=2,
            load_best_model_at_end=bool(valid_data),
            metric_for_best_model="eval_loss" if valid_data else None,
        )

        data_collator = DataCollatorForLanguageModeling(
            tokenizer=self.tokenizer, mlm=False
        )

        self.trainer = Trainer(
            model=self.model,
            args=training_args,
            train_dataset=train_data,
            eval_dataset=valid_data if valid_data else None,
            data_collator=data_collator,
        )

        self.trainer.train()

    # ------------------------------------------------------------------
    # Perplexity evaluation
    # ------------------------------------------------------------------
    def evaluate(self, valid_path: Optional[str | Path] = None) -> float:
        """Compute perplexity on the (optionally overridden) validation set."""
        if self.trainer is None:
            raise RuntimeError("Model must be trained before evaluation.")

        path = Path(valid_path) if valid_path else self.valid_path
        if not path.exists():
            raise FileNotFoundError(f"Validation set not found: {path}")

        rows = load_jsonl(path)
        enc = [self._tokenize(r) for r in rows]

        eval_args = TrainingArguments(
            output_dir=str(self.output_dir / "_eval"),
            per_device_eval_batch_size=2,
            report_to="none",
        )
        eval_trainer = Trainer(
            model=self.model,
            args=eval_args,
            eval_dataset=enc,
            data_collator=DataCollatorLanguageModeling(
                tokenizer=self.tokenizer, mlm=False
            ),
        )
        metrics = eval_trainer.evaluate()
        perplexity = math.exp(metrics.get("eval_loss", float("inf")))
        print(f"Perplexity: {perplexity:.4f}")
        return perplexity

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save(self, path: Optional[str | Path] = None):
        """Save adapter weights + tokenizer to *path*."""
        save_path = Path(path) if path else self.output_dir
        save_path.mkdir(parents=True, exist_ok=True)
        self.model.save_pretrained(save_path)
        self.tokenizer.save_pretrained(save_path)
        print(f"Adapter saved → {save_path}")

    @classmethod
    def load_adapter(
        cls,
        base_model: str,
        adapter_path: str | Path,
        tokenizer_path: Optional[str | Path] = None,
    ) -> tuple[Any, Any]:
        """Load a fine-tuned adapter and return (model, tokenizer)."""
        if not PEFT_AVAILABLE:
            raise RuntimeError("peft and transformers are required.")
        from peft import PeftModel

        tok_path = Path(tokenizer_path) if tokenizer_path else Path(adapter_path)
        tokenizer = AutoTokenizer.from_pretrained(tok_path)
        model = AutoModelForCausalLM.from_pretrained(base_model, device_map="auto")
        model = PeftModel.from_pretrained(model, str(adapter_path))
        return model, tokenizer


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    import argparse

    parser = argparse.ArgumentParser(description="LoRA Fine-tuning Pipeline")
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--train-path", default="finetune/data/train.jsonl")
    parser.add_argument("--valid-path", default="finetune/data/valid.jsonl")
    parser.add_argument("--output-dir", default="finetune/adapters/lora-t4")
    parser.add_argument("--lora-r", type=int, default=DEFAULT_LORA_R)
    parser.add_argument("--lora-alpha", type=int, default=DEFAULT_LORA_ALPHA)
    parser.add_argument("--lora-dropout", type=float, default=DEFAULT_LORA_DROPOUT)
    parser.add_argument("--max-length", type=int, default=1024)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--fp16", action="store_true", default=_torch_cuda_available())
    parser.add_argument("--8bit", action="store_true", dest="use_8bit")
    parser.add_argument("--eval-only", action="store_true", help="Skip training, evaluate only")
    args = parser.parse_args()

    if not PEFT_AVAILABLE:
        print("⚠️  peft/transformers not installed — running in dry-run mode.")
        print("    Install with: pip install peft transformers torch")
        print("    Data files validated:")
        for p in (args.train_path, args.valid_path):
            n = len(load_jsonl(p)) if Path(p).exists() else 0
            print(f"      {p}: {n} rows")
        return

    trainer = LoRATrainer(
        base_model=args.base_model,
        train_path=args.train_path,
        valid_path=args.valid_path,
        output_dir=args.output_dir,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        max_length=args.max_length,
        use_8bit=args.use_8bit,
    )

    if args.eval_only:
        trainer._load_model()
        trainer.evaluate()
    else:
        trainer.train(
            num_train_epochs=args.epochs,
            per_device_train_batch_size=args.batch_size,
            learning_rate=args.lr,
            fp16=args.fp16,
        )
        trainer.save()


if __name__ == "__main__":
    main()
