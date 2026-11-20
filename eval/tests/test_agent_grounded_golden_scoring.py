import importlib.util
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "agent_grounded_golden", Path(__file__).resolve().parents[1] / "run_agent_grounded_golden.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_missing_gold_chunk_counts_as_zero_reciprocal_rank():
    assert MODULE.metrics([1, 2, None, 6]) == {"recall_at_5": 0.5, "mrr": 0.4167}


def test_rank_uses_document_and_chunk_not_answer_text():
    rows = [("france.txt", 1), ("germany.txt", 0), ("france.txt", 0)]
    assert MODULE.rank_of(rows, ("france.txt", 0)) == 3
    assert MODULE.rank_of(rows, ("japan.txt", 0)) is None
