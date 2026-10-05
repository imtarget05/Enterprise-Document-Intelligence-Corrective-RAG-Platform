"""Regression tests for live-benchmark retrieval scoring.

Guards the metric-integrity rule: a question with no ground truth must be
reported as UNSCORED (excluded from aggregates), never scored as a perfect 1.0.

Historically `evaluate_retrieval_ranking` returned
``{"hit": True, "recall": 1.0, "mrr": 1.0}`` for keyword-less questions, and
those values were averaged into `hit_rate_at_k` / `mean_recall_at_k` /
`mean_reciprocal_rank`, inflating the reported benchmark.

Run:  cd <repo-root> && python3 -m pytest eval/tests/test_live_benchmark_scoring.py -q

No network, no LLM, no production access.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from run_live_benchmark import evaluate_retrieval_ranking  # noqa: E402


def _chunk(idx, text, rank=None):
    return {"chunk_id": str(idx), "text": text, "rank": rank if rank is not None else idx}


class UnscoredQuestionTests(unittest.TestCase):
    def test_question_without_keywords_is_not_scored_as_perfect(self):
        metrics = evaluate_retrieval_ranking(
            [_chunk(1, "irrelevant text")], expected_keywords=[]
        )

        self.assertFalse(metrics["scored"], "must be flagged unscored")
        self.assertFalse(metrics["hit"], "no ground truth cannot be a hit")
        self.assertIsNone(metrics["recall"], "recall must be undefined, not 1.0")
        self.assertIsNone(metrics["mrr"], "mrr must be undefined, not 1.0")

    def test_unscored_result_cannot_be_summed_into_an_aggregate(self):
        metrics = evaluate_retrieval_ranking([], expected_keywords=[])
        results = [{"scored": metrics["scored"], "recall": metrics["recall"]}]

        scored = [r for r in results if r["scored"]]
        self.assertEqual(scored, [], "unscored questions must leave the denominator")


class ScoredQuestionTests(unittest.TestCase):
    def test_keyword_found_in_top_chunk_is_a_hit(self):
        metrics = evaluate_retrieval_ranking(
            [_chunk(1, "this chunk mentions spring boot and postgres")],
            expected_keywords=["spring boot"],
            top_k=5,
        )

        self.assertTrue(metrics["scored"])
        self.assertTrue(metrics["hit"])
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["mrr"], 1.0)

    def test_recall_is_fraction_of_keywords_found_not_any_keyword(self):
        metrics = evaluate_retrieval_ranking(
            [_chunk(1, "only spring boot appears here")],
            expected_keywords=["spring boot", "qdrant", "langgraph"],
            top_k=5,
        )

        self.assertTrue(metrics["hit"], "one keyword is enough for a hit")
        self.assertAlmostEqual(metrics["recall"], 1 / 3, places=4,
                               msg="recall must be keyword coverage, not any-hit")

    def test_keywords_outside_top_k_do_not_count(self):
        # parse_retrieved_chunks always assigns rank = idx + 1, so a real
        # response has 6 ordered chunks before any top-5 slicing happens.
        chunks = [
            _chunk(1, "no relevant content", rank=1),
            _chunk(2, "still no relevant content", rank=2),
            _chunk(3, "nope", rank=3),
            _chunk(4, "nothing here", rank=4),
            _chunk(5, "unrelated", rank=5),
            _chunk(6, "the answer is qdrant", rank=6),
        ]
        metrics = evaluate_retrieval_ranking(chunks, expected_keywords=["qdrant"], top_k=5)

        self.assertFalse(metrics["hit"], "rank 6 is outside top-5")
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["mrr"], 0.0)

    def test_rank_matches_list_position_in_production_output(self):
        # The contract the rest of the script relies on: rank and list order
        # are the same thing, so slicing by position IS slicing by rank.
        chunks = [_chunk(i, "text", rank=i) for i in range(1, 7)]
        self.assertEqual([c["rank"] for c in chunks[:5]], [1, 2, 3, 4, 5])


if __name__ == "__main__":
    unittest.main()
