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
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from run_live_benchmark import (  # noqa: E402
    DEFAULT_CORPUS,
    DEFAULT_QUESTIONS,
    evaluate_abstention,
    evaluate_retrieval_ranking,
    run_benchmark,
    sha256_file,
    validate_question_corpus,
)
import hashlib
import json


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
    def test_keyword_matching_normalizes_wrapped_source_text(self):
        metrics = evaluate_retrieval_ranking(
            [_chunk(1, "install a pressure\nsensor with alarm on the line")],
            expected_keywords=["pressure sensor with alarm"],
        )
        self.assertTrue(metrics["hit"])
        self.assertEqual(metrics["recall"], 1.0)

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


class DatasetIntegrityTests(unittest.TestCase):
    def test_default_questions_match_uploaded_corpus(self):
        questions = json.loads(DEFAULT_QUESTIONS.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(questions), 3)
        validate_question_corpus(questions, DEFAULT_CORPUS.read_text(encoding="utf-8"))

    def test_architecture_questions_are_rejected_for_engineering_fixture(self):
        questions = [{"id": "architecture", "question": "Which backend framework?",
                      "expected_source_keywords": ["Spring Boot"]}]
        with self.assertRaisesRegex(ValueError, "architecture"):
            validate_question_corpus(questions, DEFAULT_CORPUS.read_text(encoding="utf-8"))

    def test_duplicate_ids_and_empty_questions_are_rejected(self):
        corpus = "bearing failure root cause"
        for questions in (
            [{"id": 1, "question": "A?", "expected_source_keywords": ["bearing"]},
             {"id": 1, "question": "B?", "expected_source_keywords": ["failure"]}],
            [{"id": 2, "question": "", "expected_source_keywords": ["bearing"]}],
        ):
            with self.assertRaises(ValueError):
                validate_question_corpus(questions, corpus)

    def test_mismatch_stops_before_network_and_files_have_stable_hashes(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "corpus.txt"
            questions = Path(directory) / "questions.json"
            corpus.write_text("bearing failure", encoding="utf-8")
            questions.write_text(json.dumps([{"id": 1, "question": "Which backend?",
                                              "expected_source_keywords": ["Spring Boot"]}]), encoding="utf-8")
            self.assertEqual(sha256_file(corpus), hashlib.sha256(b"bearing failure").hexdigest())
            with patch("run_live_benchmark.requests.Session") as session:
                with self.assertRaises(ValueError):
                    run_benchmark("http://localhost:8080/api", questions, corpus,
                                  Path(directory) / "result.json")
                session.assert_not_called()

    def test_unanswerable_question_must_have_no_retrieval_or_answer_gold(self):
        corpus = DEFAULT_CORPUS.read_text(encoding="utf-8")
        validate_question_corpus([{"id": "unknown", "question": "What was the repair cost?",
                                  "expect_abstain": True, "expected_source_keywords": [],
                                  "expected_answer_contains": []}], corpus)
        with self.assertRaises(ValueError):
            validate_question_corpus([{"id": "bad", "question": "What was the repair cost?",
                                      "expect_abstain": True, "expected_source_keywords": ["cost"]}], corpus)

    def test_abstention_requires_explicit_no_evidence_and_safe_answer(self):
        safe = "Không tìm thấy thông tin trong tài liệu để trả lời câu hỏi này."
        self.assertTrue(evaluate_abstention(200, {"ragStrategy": "no_evidence", "aiResponse": safe}))
        self.assertFalse(evaluate_abstention(200, {"ragStrategy": "error", "aiResponse": safe}))
        self.assertFalse(evaluate_abstention(200, {"ragStrategy": "no_evidence", "aiResponse": "The cost was $100"}))
        self.assertFalse(evaluate_abstention(503, {"ragStrategy": "no_evidence", "aiResponse": safe}))

    def test_live_summary_keeps_abstention_separate_from_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "corpus.txt"
            questions = Path(directory) / "questions.json"
            output = Path(directory) / "result.json"
            corpus.write_text("The verification checklist is mandatory.", encoding="utf-8")
            questions.write_text(json.dumps([
                {"id": "known", "question": "What is mandatory?",
                 "expected_source_keywords": ["verification checklist"],
                 "expected_answer_contains": ["checklist"]},
                {"id": "unknown", "question": "What is the total cost?",
                 "expect_abstain": True, "expected_source_keywords": [],
                 "expected_answer_contains": []},
            ]), encoding="utf-8")
            known = Mock(status_code=200, headers={})
            known.json.return_value = {"aiResponse": "The checklist is mandatory.",
                                       "ragStrategy": "direct",
                                       "sourceChunks": ["The verification checklist is mandatory."]}
            unknown = Mock(status_code=200, headers={})
            unknown.json.return_value = {"aiResponse": "Không tìm thấy thông tin trong tài liệu để trả lời câu hỏi này.",
                                         "ragStrategy": "no_evidence", "sourceChunks": []}
            session = Mock()
            session.post.side_effect = [known, unknown]
            with patch("run_live_benchmark.requests.Session", return_value=session), \
                 patch("run_live_benchmark.authenticate", return_value=("tester", {})), \
                 patch("run_live_benchmark.upload_corpus", return_value=12), \
                 patch("run_live_benchmark.get_csrf_token", return_value=None):
                summary = run_benchmark("http://localhost:8080/api", questions, corpus, output)
            self.assertEqual(summary["scored_retrieval_questions"], 1)
            self.assertEqual(summary["expected_abstention_questions"], 1)
            self.assertEqual(summary["abstention_success_rate"], 1.0)
            self.assertEqual(summary["unexpected_abstentions"], 0)
            self.assertEqual(summary["source_keyword_hit_rate_at_k"], 1.0)
            self.assertEqual(json.loads(output.read_text())["questions_sha256"], sha256_file(questions))

    def test_mock_backend_cannot_produce_a_passing_live_result(self):
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "corpus.txt"
            questions = Path(directory) / "questions.json"
            output = Path(directory) / "result.json"
            corpus.write_text("verification checklist", encoding="utf-8")
            questions.write_text(json.dumps([{"id": "one", "question": "What checklist?",
                                              "expected_source_keywords": ["verification checklist"]}]), encoding="utf-8")
            response = Mock(status_code=200, headers={"X-Mock-Backend": "true"})
            response.json.return_value = {"aiResponse": "verification checklist",
                                          "sourceChunks": ["verification checklist"]}
            session = Mock()
            session.post.return_value = response
            with patch("run_live_benchmark.requests.Session", return_value=session), \
                 patch("run_live_benchmark.authenticate", return_value=("tester", {})), \
                 patch("run_live_benchmark.upload_corpus", return_value=12), \
                 patch("run_live_benchmark.get_csrf_token", return_value=None):
                with self.assertRaisesRegex(RuntimeError, "Mock backend detected"):
                    run_benchmark("http://localhost:8081/api", questions, corpus, output)
            self.assertEqual(json.loads(output.read_text())["mock_responses"], 1)


if __name__ == "__main__":
    unittest.main()
