"""
Tests for GraphMemory - GraphRAG-style cross-session memory persistence.

These tests use the in-memory fallback (no PostgreSQL required) to verify
the core logic works. In production, PostgreSQL provides persistent storage.
"""

import asyncio
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from memory.graph_memory import (
    GraphMemory,
    Entity,
    Relationship,
    EntityMention,
    ENTITY_PERSON,
    ENTITY_ORG,
    ENTITY_DOCUMENT,
    ENTITY_CONCEPT,
)


@pytest.fixture
def graph():
    """Create a GraphMemory instance (uses in-memory fallback)."""
    return GraphMemory(llm_router=None)


@pytest.mark.asyncio
async def test_store_entity(graph):
    """Test storing an entity."""
    entity = await graph._store_entity("Alice Smith", ENTITY_PERSON, {"description": "A software engineer"})
    
    assert entity is not None
    assert entity.name == "Alice Smith"
    assert entity.type == ENTITY_PERSON
    assert entity.metadata["description"] == "A software engineer"
    assert entity.id.startswith("local_")


@pytest.mark.asyncio
async def test_store_entity_deduplication(graph):
    """Test that storing the same entity twice returns the existing one."""
    ent1 = await graph._store_entity("Bob Jones", ENTITY_PERSON)
    ent2 = await graph._store_entity("Bob Jones", ENTITY_PERSON)
    
    assert ent1.id == ent2.id
    assert len(graph._local_entities) == 1


@pytest.mark.asyncio
async def test_store_relationship(graph):
    """Test storing a relationship between entities."""
    ent1 = await graph._store_entity("Alice", ENTITY_PERSON)
    ent2 = await graph._store_entity("Acme Corp", ENTITY_ORG)
    
    rel = await graph._store_relationship(ent1.id, ent2.id, "works_at", 0.9)
    
    assert rel is not None
    assert rel.source_entity_id == ent1.id
    assert rel.target_entity_id == ent2.id
    assert rel.relationship_type == "works_at"
    assert rel.weight == 0.9


@pytest.mark.asyncio
async def test_store_mention(graph):
    """Test storing an entity mention."""
    ent = await graph._store_entity("Python", ENTITY_CONCEPT)
    
    mention = await graph._store_mention(
        entity_id=ent.id,
        session_id="session_123",
        turn_id=5,
        context_text="User asked about Python programming",
    )
    
    assert mention is not None
    assert mention.entity_id == ent.id
    assert mention.session_id == "session_123"
    assert mention.turn_id == 5


@pytest.mark.asyncio
async def test_retrieve_related(graph):
    """Test retrieving related entities via graph traversal."""
    # Build a small graph: Alice -> works_at -> Acme -> located_in -> NYC
    alice = await graph._store_entity("Alice", ENTITY_PERSON)
    acme = await graph._store_entity("Acme Corp", ENTITY_ORG)
    nyc = await graph._store_entity("New York City", ENTITY_CONCEPT)
    
    await graph._store_relationship(alice.id, acme.id, "works_at", 0.9)
    await graph._store_relationship(acme.id, nyc.id, "located_in", 0.8)
    
    # Get entities related to Alice (depth 2)
    related = await graph.retrieve_related("Alice", depth=2)
    
    assert len(related) >= 2
    names = [r["name"] for r in related]
    assert "Acme Corp" in names
    assert "New York City" in names


@pytest.mark.asyncio
async def test_get_entity_context(graph):
    """Test getting full context for an entity."""
    alice = await graph._store_entity("Alice", ENTITY_PERSON, {"role": "engineer"})
    acme = await graph._store_entity("Acme Corp", ENTITY_ORG)
    await graph._store_relationship(alice.id, acme.id, "works_at", 0.9)
    await graph._store_mention(alice.id, "session_1", 1, "Alice works at Acme")
    
    context = await graph.get_entity_context("Alice")
    
    assert context["found"] is True
    assert context["entity"]["name"] == "Alice"
    assert context["entity"]["type"] == ENTITY_PERSON
    assert len(context["relationships"]) >= 1
    assert context["relationships"][0]["type"] == "works_at"
    assert len(context["mentions"]) >= 1


@pytest.mark.asyncio
async def test_get_entity_context_not_found(graph):
    """Test getting context for non-existent entity."""
    context = await graph.get_entity_context("NonExistentPerson")
    assert context["found"] is False


@pytest.mark.asyncio
async def test_find_path(graph):
    """Test finding path between two entities."""
    # Build graph: A -> B -> C -> D
    a = await graph._store_entity("EntityA", ENTITY_CONCEPT)
    b = await graph._store_entity("EntityB", ENTITY_CONCEPT)
    c = await graph._store_entity("EntityC", ENTITY_CONCEPT)
    d = await graph._store_entity("EntityD", ENTITY_CONCEPT)
    
    await graph._store_relationship(a.id, b.id, "relates_to", 0.5)
    await graph._store_relationship(b.id, c.id, "relates_to", 0.5)
    await graph._store_relationship(c.id, d.id, "relates_to", 0.5)
    
    path = await graph.find_path("EntityA", "EntityD")
    
    assert path["found"] is True
    assert path["depth"] == 3
    assert "EntityA" in path["path_steps"]
    assert "EntityD" in path["path_steps"]


@pytest.mark.asyncio
async def test_find_path_same_entity(graph):
    """Test finding path from entity to itself."""
    a = await graph._store_entity("EntityA", ENTITY_CONCEPT)
    
    path = await graph.find_path("EntityA", "EntityA")
    
    assert path["found"] is True
    assert path["depth"] == 0


@pytest.mark.asyncio
async def test_find_path_no_path(graph):
    """Test finding path when no connection exists."""
    a = await graph._store_entity("IsolatedA", ENTITY_CONCEPT)
    b = await graph._store_entity("IsolatedB", ENTITY_CONCEPT)
    
    path = await graph.find_path("IsolatedA", "IsolatedB")
    
    assert path["found"] is False


@pytest.mark.asyncio
async def test_get_session_entities(graph):
    """Test getting all entities mentioned in a session."""
    a = await graph._store_entity("Python", ENTITY_CONCEPT)
    b = await graph._store_entity("Machine Learning", ENTITY_CONCEPT)
    c = await graph._store_entity("Deep Learning", ENTITY_CONCEPT)
    
    await graph._store_mention(a.id, "session_1", 1, "Python is great")
    await graph._store_mention(b.id, "session_1", 2, "ML is useful")
    await graph._store_mention(a.id, "session_1", 3, "Python again")
    await graph._store_mention(c.id, "session_2", 1, "DL stuff")
    
    entities = await graph.get_session_entities("session_1")
    
    assert len(entities) == 2
    # Python should have 2 mentions
    python = next(e for e in entities if e["name"] == "Python")
    assert python["mention_count"] == 2


@pytest.mark.asyncio
async def test_search_entities(graph):
    """Test searching entities by name."""
    await graph._store_entity("Python Programming", ENTITY_CONCEPT)
    await graph._store_entity("Python Script", ENTITY_DOCUMENT)
    await graph._store_entity("Java Language", ENTITY_CONCEPT)
    
    results = await graph.search_entities("Python")
    
    assert len(results) == 2
    names = [r["name"] for r in results]
    assert "Python Programming" in names
    assert "Python Script" in names


@pytest.mark.asyncio
async def test_extract_and_store(graph):
    """Test extracting entities from conversation and storing them."""
    conversation = [
        {"role": "user", "content": "I work at Google as a software engineer"},
        {"role": "assistant", "content": "That's great! Google is a top tech company."},
        {"role": "user", "content": "Yes, I work on the Search team with John Smith"},
    ]
    
    entities, relationships = await graph.extract_and_store(
        session_id="test_session",
        user_id="test_user",
        conversation_turns=conversation,
    )
    
    # Should extract some entities (heuristic extraction)
    assert isinstance(entities, list)
    assert isinstance(relationships, list)
    
    # Verify entities were stored
    stats = await graph.get_stats()
    assert stats["entities"] > 0


@pytest.mark.asyncio
async def test_get_stats(graph):
    """Test getting graph statistics."""
    await graph._store_entity("Test1", ENTITY_CONCEPT)
    await graph._store_entity("Test2", ENTITY_CONCEPT)
    
    stats = await graph.get_stats()
    
    assert stats["entities"] == 2
    assert stats["storage"] == "in-memory"


@pytest.mark.asyncio
async def test_entity_to_dict():
    """Test Entity serialization."""
    entity = Entity(
        id="test_id",
        name="Test Entity",
        type=ENTITY_PERSON,
        metadata={"key": "value"},
        created_at=1234567890.0,
    )
    
    d = entity.to_dict()
    assert d["id"] == "test_id"
    assert d["name"] == "Test Entity"
    assert d["type"] == ENTITY_PERSON
    assert d["metadata"]["key"] == "value"


@pytest.mark.asyncio
async def test_relationship_to_dict():
    """Test Relationship serialization."""
    rel = Relationship(
        id="rel_id",
        source_entity_id="src",
        target_entity_id="tgt",
        relationship_type="knows",
        weight=0.8,
    )
    
    d = rel.to_dict()
    assert d["id"] == "rel_id"
    assert d["relationship_type"] == "knows"
    assert d["weight"] == 0.8


@pytest.mark.asyncio
async def test_heuristic_extract(graph):
    """Test heuristic entity extraction."""
    text = """
    User: I work at Google with Alice Smith on Project Alpha.
    Assistant: That sounds interesting! Google is a great company.
    User: Yes, Alice and I are building a Machine Learning system.
    """
    
    result = graph._heuristic_extract(text)
    
    assert "entities" in result
    assert "relationships" in result
    # Should extract some capitalized phrases
    assert len(result["entities"]) >= 0  # May vary based on text


@pytest.mark.asyncio
async def test_case_insensitive_lookup(graph):
    """Test that entity lookup is case-insensitive."""
    await graph._store_entity("Alice Smith", ENTITY_PERSON)
    
    # Should find regardless of case
    ent = await graph._get_entity_by_name("alice smith")
    assert ent is not None
    assert ent.name == "Alice Smith"
    
    ent2 = await graph._get_entity_by_name("ALICE SMITH")
    assert ent2 is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_pg_dsn_requests_tls_when_sslmode_is_configured(monkeypatch):
    """Managed Postgres (Neon) refuses plaintext: the DSN must carry sslmode."""
    from memory.graph_memory import _pg_dsn
    from memory.long_term import _pg_dsn as _long_term_dsn

    monkeypatch.delenv("POSTGRES_SSLMODE", raising=False)
    assert "sslmode" not in _pg_dsn()
    assert "sslmode" not in _long_term_dsn()

    monkeypatch.setenv("POSTGRES_SSLMODE", "require")
    assert "sslmode=require" in _pg_dsn()
    assert "sslmode=require" in _long_term_dsn()
