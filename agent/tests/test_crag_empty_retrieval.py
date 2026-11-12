from unittest.mock import AsyncMock
from agents.rag_agent import RagAgent


async def test_empty_first_retrieval_reaches_reformulation():
    agent = object.__new__(RagAgent)

    async def retrieve(query, *args):
        if query == 'reformulated':
            return [{'text': 'recovered evidence', 'score': 0.95}], 0.95
        return [], 0.0

    agent._retrieve = AsyncMock(side_effect=retrieve)
    agent._reformulate_query = AsyncMock(return_value=['reformulated'])
    chunks, score = await agent._crag_loop('original', ['1'], True)
    assert chunks[0]['text'] == 'recovered evidence'
    assert score == 0.95
    agent._reformulate_query.assert_awaited_once_with('original')
