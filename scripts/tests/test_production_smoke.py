"""A healthy HTTP response must not hide a failed RAG pipeline."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('production_smoke', Path(__file__).parents[1] / 'production_smoke.py')
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


class AnswerValidationTest(unittest.TestCase):
    def test_rejects_error_and_abstention_even_if_they_mention_paris(self):
        for strategy in ('error', 'no_evidence', 'general_knowledge', ''):
            self.assertFalse(smoke.valid_smoke_answer({'aiResponse': 'Paris', 'ragStrategy': strategy}))

    def test_requires_correct_fixture_answer(self):
        for answer in ('', 'No evidence found', 'Tokyo', 'temporarily unavailable in Paris'):
            self.assertFalse(smoke.valid_smoke_answer({'aiResponse': answer, 'ragStrategy': 'direct'}))

    def test_accepts_grounded_rag_and_agent_answers(self):
        for strategy in ('direct', 'corrective', 'agentic'):
            self.assertTrue(smoke.valid_smoke_answer({'aiResponse': 'The Eiffel Tower is in Paris, France.', 'ragStrategy': strategy}))


if __name__ == '__main__':
    unittest.main()
