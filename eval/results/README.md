# Evaluation artifacts — provenance & how to read them

This directory holds **historical** evaluation runs. They are kept as raw
evidence and are **not** re-labelled or edited. This file is the index that says
what each artifact actually is, so none of them can be quoted out of context.

## 1. What `retrieval_accuracy` actually measures

From `eval/eval.py` (the classic RAG track):

```python
source_keywords = [k.lower() for k in question["expected_source_keywords"]]
source_hits     = [k for k in source_keywords if k in sources]
retrieval_accurate = len(source_hits) > 0 if sources else False
```

So `retrieval_accuracy` = the fraction of questions for which **at least one**
expected source keyword appeared as a substring of the returned `sourceChunks`
text.

It is therefore:

- **lexical** (substring match), not semantic;
- **OR-semantics** (≥1 keyword), not all-keywords;
- a *source-keyword hit rate*, **not** recall@k / MRR / gold-chunk precision.

It does **not** use labelled gold chunk IDs. Do not present it as "retrieval
accuracy" without this qualifier.

## 2. How to tell a mock run from a live run

Two useful clues, both present in historical summary artifacts:

| Signal | Mock stack | Live stack |
|---|---|---|
| `base_url` | `http://localhost:8081/api` (see `eval/mock_backend.py`) | a real deployment |
| `average_latency_ms` | **11–20 ms** | **~1900–2700 ms** |

The mock replies from an in-process dictionary keyed on question text and
sleeps only 10% of the canned latency. Latency alone does not prove a live
provider: a real backend may serve a cached answer or a fast fallback. For
new runs, inspect `mock_responses`, `answer_origin`, router/provider logs,
and the endpoint configuration together.

### Why several files all report 0.9677

`eval/mock_backend.py` contains `MOCK_RESPONSES`, a table of canned answers
keyed on question substrings. It was built to reproduce the live result, so a
mock run legitimately lands on the same `0.9677` as the live run. **Identical
numbers do not imply identical provenance** — check `base_url` and latency.

## 3. Trap: `genuine_llm_responses` in older artifacts

Artifacts generated before the `eval/eval.py` mock-detection fix compute

```python
"genuine_llm_responses": len(successful)   # == successful request count
```

That field only means "the HTTP call succeeded". It is **not** evidence that a
real LLM produced the answer. In mock artifacts it reads `31` and is wrong by
the field's own name. Newer runs set `test_type`, `is_mock_run` and
`mock_responses`, and `genuine_llm_responses` is `0` for mock runs.

## 4. Artifact classification

| Artifact | Kind | `base_url` | avg latency | `retrieval_accuracy` |
|---|---|---|---|---|
| `full_eval_2026-08-26_doc102_v2.json` | **LIVE** | `smart-doc-backend-h4mt.onrender.com` | 1930 ms | **0.9677** |
| `full_eval_2026-08-26_diag_doc101.json` | **LIVE** | `smart-doc-backend-h4mt.onrender.com` | 2685 ms | 0.7097 |
| `offline_eval.json` | mock fixture | `localhost:8081` | 20 ms | 0.9677 (`fixture_retrieval_pass_rate`) |
| `mock_live_eval_results.json` | mock | `localhost:8081` | 17 ms | 0.9677 |
| `hallucination_test.json` | mock | `localhost:8081` | 15 ms | 0.9677 |
| `agent_eval_results.json` | agent track, local | `localhost:9000` | — | not comparable (different track) |
| `fresh_eval_20260901_143319.json` | local run, 0 correct | `localhost:8080` | 0 ms | 0.0 |
| `final_eval_*`, `keyword_eval_*`, `verify_eval_*`, `fresh_eval_20260901_143*` | partial/step traces | — | — | no summary metrics |
| `full_eval.json`, `full_eval_2026-08-25.json`, `rag_30_trace*.json` | raw traces | — | — | no summary metrics |
| `*_mock.json`, `fixture_eval.json` | mock fixtures by name | — | — | no summary metrics |

## 5. Provenance of the "96.8%" figure

The number came from **`full_eval_2026-08-26_doc102_v2.json`** — a genuine live
run against the deployed backend:

- `base_url`: `https://smart-doc-backend-h4mt.onrender.com/api`
- `timestamp`: `2026-08-26T11:18:23Z`
- `total_questions`: 31, `provider_errors`: 0
- `average_latency_ms`: 1930 (min 952, max 4731)

**Defensible wording:**

> On 2026-08-26, 31 questions were run against the deployed backend: 30/31
> (96.77%) returned at least one expected source keyword in the retrieved chunk
> text — a lexical source-keyword hit rate, not a recall@K or gold-chunk metric.
> Mean end-to-end latency 1.93 s (p95 2.72 s).

**Not defensible:** "96.8% retrieval accuracy" with no qualifier, or any claim
that CI verifies it. CI runs the mock stack.

## 6. Reproducing

```bash
# Fixture / grader smoke test (mock stack, deterministic, CI-safe)
python eval/run_fixture_eval.py --base-url http://127.0.0.1:8081/api

# Live benchmark (requires a running deployment + uploaded document)
python eval/run_live_benchmark.py \
  --base-url https://<your-deployment>/api \
  --questions eval/engineering_benchmark_questions.json \
  --output eval/results/live_benchmark.json
```

`run_live_benchmark.py` reports **Hit@K / lexical keyword coverage@K / MRR** computed by matching
expected source keywords inside the top-K retrieved chunks (so: ranking-aware
and K-scoped, but still lexical — not gold-chunk-ID ground truth). Questions
that carry no expected keywords are reported as `scored: false` with `None`
metrics and are excluded from every aggregate; they are never scored as 1.0.

The default 15-question set has 12 answerable cases and 3 facts deliberately
absent from the uploaded 8D corpus. The runner rejects mismatched positive
source keywords before opening a session. Its JSON includes SHA-256 hashes of
the corpus and question file, explicit abstention outcomes, failed request
counts, and latency. It records model identity and cost as unavailable because
the current chat response exposes neither model ID nor token/billing usage.
No model or dollar figure should be inferred from the benchmark alone.
`eval/questions.json` contains architecture questions and must not be paired
with the default 8D corpus. A mock-marked response fails the live command.

The historical 3-question local live result in
`docs/evidence/live-validation-2026-11-12/engineering-benchmark.json` remains
as recorded. The 2026-11-18 local 15-question run is saved as
`live_engineering_15_ollama_qwen2_5_1_5b_2026-11-18.json`:
12/12 lexical source-keyword hits, 11/12 answer substring hits, 3/3 explicit
abstentions, 15/15 backend-reported LLM answers, no extractive fallback,
7,792 ms mean and 20,301 ms p95 end-to-end latency. These are fixture-specific
measurements, not semantic accuracy or production latency. The answer to
`eng-012` explains both cases correctly but lacks the rubric's literal
"mechanical"/"software" words, so its substring score is false. The local
router was configured with Ollama `qwen2.5:1.5b`, response cache disabled;
router logs showed `local_ollama` route completions during the run. The JSON
itself does not verify provider identity, token usage, or compute cost.

A live run cannot be executed from a machine without a reachable provider, and
**no result may be fabricated in its absence**.
