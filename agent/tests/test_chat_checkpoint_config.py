"""Live invocation must supply the persistent checkpointer's tenant-scoped key."""
from fastapi.testclient import TestClient
from main import app
import state


def test_invoke_supplies_checkpoint_identity(monkeypatch):
    calls = []

    class Workflow:
        async def ainvoke(self, inputs, config=None):
            assert config and config['configurable']['thread_id']
            calls.append(config['configurable']['thread_id'])
            return {'final_answer': 'Fixture answer', 'agent_type': 'rag', 'sources': [], 'confidence_score': 0.8}

    monkeypatch.setattr(state, '_workflow', Workflow())
    monkeypatch.setattr(state, '_long_term_memory', None)
    monkeypatch.setattr(state, '_rate_limiter', None)
    monkeypatch.setattr(state.settings, 'app_env', 'test')
    client = TestClient(app)
    for user in ('tenant-a', 'tenant-b', 'tenant-a'):
        response = client.post('/v1/agent/invoke', json={
            'query': 'Where is the fixture?', 'session_id': 'same-session', 'user_id': user,
        })
        assert response.status_code == 200, response.text
    assert calls[0] != calls[1]
    assert calls[0] == calls[2]
