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

Two independent signals, both present in every summary artifact:

| Signal | Mock stack | Live stack |
|---|---|---|
| `base_url` | `http://localhost:8081/api` (see `eval/mock_backend.py`) | a real deployment |
| `average_latency_ms` | **11–20 ms** | **~1900–2700 ms** |

The mock replies from an in-process dictionary keyed on the question text and
sleeps only 10% of the canned latency, so it is physically incapable of
produces multi-second latencies. **Latency is the decisive tell.**

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
  --questions eval/questions.json \
  --output eval/results/live_benchmark.json
```

`run_live_benchmark.py` reports **Hit@K / Recall@K / MRR** computed by matching
expected source keywords inside the top-K retrieved chunks (so: ranking-aware
and K-scoped, but still lexical — not gold-chunk-ID ground truth). Questions
that carry no expected keywords are reported as `scored: false` with `None`
metrics and are excluded from every aggregate; they are never scored as 1.0.

A live run cannot be executed from a machine without a reachable provider, and
**no result may be fabricated in its absence**.
