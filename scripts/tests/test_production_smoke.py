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
            self.assertTrue(smoke.valid_smoke_answer({'aiResponse': 'The Eiffel Tower is in Paris, France [1].', 'ragStrategy': strategy}))

    def test_rag_mode_requires_llm_origin(self):
        response = {'aiResponse': 'The excerpt says Paris, France [1].', 'ragStrategy': 'direct'}
        self.assertFalse(smoke.valid_smoke_answer(response, require_llm=True))
        response['answerOrigin'] = 'extractive_fallback'
        self.assertFalse(smoke.valid_smoke_answer(response, require_llm=True))
        response['answerOrigin'] = 'llm'
        self.assertTrue(smoke.valid_smoke_answer(response, require_llm=True))

    def test_requires_citation_as_well_as_fact(self):
        self.assertFalse(smoke.valid_smoke_answer({'aiResponse': 'Paris, France', 'ragStrategy': 'direct', 'answerOrigin': 'llm'}, require_llm=True))
        self.assertFalse(smoke.valid_smoke_answer({'aiResponse': '[TÀI LIỆU] [1] Paris, France', 'ragStrategy': 'direct', 'answerOrigin': 'llm'}, require_llm=True))


if __name__ == '__main__':
    unittest.main()
