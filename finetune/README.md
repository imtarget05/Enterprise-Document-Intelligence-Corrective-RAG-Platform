# LoRA Fine-tuning Pipeline

Fine-tune a base language model with LoRA (Low-Rank Adaptation) on Vietnamese legal Q&A data.

## Architecture

```
finetune/
├── lora_trainer.py          # Main training pipeline
├── data/
│   ├── prepare_data.py      # Data preparation script
│   ├── train.jsonl          # Training set (generated)
│   └── valid.jsonl          # Validation set (generated)
└── adapters/                # Saved adapter weights
```

## Data Format

Training data uses JSONL format with one JSON object per line:

```json
{"instruction": "Bạn là trợ lý AI...", "input": "Câu hỏi...", "output": "Câu trả lời..."}
```

Or with chat messages:

```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}]}
```

## How to Prepare Data

```bash
# From repo root
python finetune/data/prepare_data.py
```

This converts existing eval questions and generates synthetic Vietnamese legal Q&A pairs.

## How to Run Training

### Basic training

```bash
python finetune/lora_trainer.py \
  --base-model Qwen/Qwen2.5-1.5B-Instruct \
  --train-path finetune/data/train.jsonl \
  --valid-path finetune/data/valid.jsonl \
  --output-dir finetune/adapters/lora-t4 \
  --epochs 3 \
  --batch-size 2
```

### 8-bit quantization (saves memory)

```bash
python finetune/lora_trainer.py \
  --base-model Qwen/Qwen2.5-1.5B-Instruct \
  --8bit \
  --epochs 3
```

### Evaluate only

```bash
python finetune/lora_trainer.py \
  --eval-only \
  --output-dir finetune/adapters/lora-t4
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LORA_BASE_MODEL` | `Qwen/Qwen2.5-1.5B-Instruct` | Base model name (open, không cần duyệt gated repo như dòng Llama) |
| `LORA_R` | `8` | LoRA rank |
| `LORA_ALPHA` | `32` | LoRA alpha |
| `LORA_DROPOUT` | `0.05` | LoRA dropout |
| `LORA_MAX_LENGTH` | `1024` | Max sequence length |
| `LORA_8BIT` | `false` | Use 8-bit quantization |
| `LORA_EVAL_STEPS` | `50` | Evaluation interval |

## How to Evaluate the Fine-tuned Model

```python
from finetune.lora_trainer import LoRATrainer

model, tokenizer = LoRATrainer.load_adapter(
    base_model="Qwen/Qwen2.5-1.5B-Instruct",
    adapter_path="finetune/adapters/lora-t4",
)

# Generate response
inputs = tokenizer("Câu hỏi pháp lý...", return_tensors="pt")
outputs = model.generate(**inputs, max_new_tokens=256)
print(tokenizer.decode(outputs[0]))
```

## Hardware Requirements

| Model Size | GPU VRAM (FP16) | GPU VRAM (8-bit) | Training Time* |
|------------|-----------------|------------------|----------------|
| 1B params  | ~6 GB           | ~3 GB            | ~30 min        |
| 3B params  | ~14 GB          | ~7 GB            | ~1.5 hours     |
| 8B params  | ~30 GB          | ~16 GB           | ~4 hours       |

*Approximate, 1000 samples, 3 epochs, batch size 2.

### Minimum requirements

- **GPU**: NVIDIA with CUDA support, ≥4 GB VRAM (8-bit mode)
- **RAM**: ≥16 GB system memory
- **Disk**: ≥10 GB free (model + adapters + data)

### Recommended

- **GPU**: NVIDIA RTX 3090/4090 (24 GB) or A100
- **RAM**: ≥32 GB
- **Use 8-bit quantization** for consumer GPUs

## Dependencies

```bash
pip install peft transformers torch accelerate
```

Optional for 8-bit training:
```bash
pip install bitsandbytes
```

## Local Training Runner (TRAINING_RUNNER_URL contract)

`agent/local_training_runner.py` is the external-runner side of
`agent/training_jobs.py`, running locally on Apple Silicon (MPS). It accepts
`POST /jobs`, spawns `lora_trainer.py`, and reports the real result
(`model_version`, `adapter_uri`, `sha256`, `metrics` from `trainer_state.json`)
back via the job's `callback_url` + `X-Callback-Token` (validated by
`/v1/training-jobs/{job_id}/callback`).

```bash
# from repo root
python -m agent.local_training_runner            # listens on :8791
export TRAINING_RUNNER_URL=http://127.0.0.1:8791 # then POST /v1/training-jobs
```

Default base model `Qwen/Qwen2.5-0.5B-Instruct` trains on M1 in ~2 min;
override with `LORA_BASE_MODEL` / `LORA_EPOCHS` / `LORA_MAX_LENGTH`.
Proven end-to-end locally: job `lora-20261009.001023-E7A2B2`,
eval_loss 2.67, perplexity 14.46.

## Integration with Smart Document Chatbot

After training, the adapter can be served via:

1. **Ollama**: Convert to GGUF format and serve locally
2. **llm-router**: Upload adapter and configure in Cloudflare Workers AI
3. **Direct inference**: Use `LoRATrainer.load_adapter()` in the agent service
