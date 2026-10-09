"""
Graph Memory - GraphRAG-style cross-session memory persistence.

Stores entities (people, organizations, documents, concepts) and their
relationships as a property graph in PostgreSQL. Uses recursive CTEs for
graph traversal, avoiding the need for an external graph database.

Integrates with LongTermMemory to provide entity-aware context retrieval.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from settings import settings
from prompts import render_prompt, PromptNotFoundError
from memory.document_reference import (
    document_needles,
    postgres_reference_pattern,
    references_document,
)

logger = logging.getLogger(__name__)

try:
    import asyncpg
    HAS_PG = True
except ImportError:
    HAS_PG = False
    logger.warning("asyncpg not installed - graph memory will use in-memory fallback.")


def _pg_dsn() -> str:
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


ENTITY_PERSON = "PERSON"
ENTITY_ORG = "ORG"
ENTITY_DOCUMENT = "DOCUMENT"
ENTITY_CONCEPT = "CONCEPT"
ENTITY_TYPES = {ENTITY_PERSON, ENTITY_ORG, ENTITY_DOCUMENT, ENTITY_CONCEPT}


@dataclass
class Entity:
    id: str = ""
    name: str = ""
    type: str = ENTITY_CONCEPT
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Relationship:
    id: str = ""
    source_entity_id: str = ""
    target_entity_id: str = ""
    relationship_type: str = ""
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EntityMention:
    id: str = ""
    entity_id: str = ""
    session_id: str = ""
    turn_id: int = 0
    context_text: str = ""
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class GraphMemory:
    """PostgreSQL-backed graph memory with recursive CTE traversal.
    
    Provides GraphRAG-style entity extraction, storage, and retrieval
    across conversation sessions. Falls back to in-memory storage when
    PostgreSQL is unavailable (data lost on restart).
    """

    def __init__(self, llm_router=None):
        self._pool: Optional[Any] = None
        self._llm = llm_router
        self._table_ensured = False
        self._pg_warned = False
        self._local_entities: Dict[str, Entity] = {}
        self._local_relationships: List[Relationship] = []
        self._local_mentions: List[EntityMention] = []

    async def _get_pool(self):
        if self._pool is None and HAS_PG:
            try:
                self._pool = await asyncpg.create_pool(
                    _pg_dsn(), min_size=1, max_size=5, timeout=5
                )
                logger.info("GraphMemory: connected to PostgreSQL")
            except Exception as exc:
                if not self._pg_warned:
                    logger.warning(
                        "GraphMemory: PostgreSQL unavailable (%s), using in-memory fallback.",
                        exc,
                    )
                    self._pg_warned = True
                self._pool = False
        return self._pool if self._pool else None

    async def ensure_tables(self):
        """Create graph memory tables if they don't exist."""
        pool = await self._get_pool()
        if not pool or self._table_ensured:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS entities (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        name        VARCHAR(512) NOT NULL,
                        type        VARCHAR(32)  NOT NULL DEFAULT 'CONCEPT',
                        metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
                        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS relationships (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        source_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        target_entity_id UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        relationship_type VARCHAR(128) NOT NULL,
                        weight      FLOAT        NOT NULL DEFAULT 1.0,
                        metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
                        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    );
                    CREATE TABLE IF NOT EXISTS entity_mentions (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        entity_id   UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
                        session_id  VARCHAR(64)  NOT NULL,
                        turn_id     INTEGER      NOT NULL DEFAULT 0,
                        context_text TEXT        NOT NULL,
                        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_entities_name_lower ON entities (LOWER(name));
                    CREATE INDEX IF NOT EXISTS idx_entities_type ON entities (type);
                    CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships (source_entity_id);
                    CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships (target_entity_id);
                    CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity ON entity_mentions (entity_id);
                    CREATE INDEX IF NOT EXISTS idx_entity_mentions_session ON entity_mentions (session_id);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type ON entities (LOWER(name), type);
                """)
                self._table_ensured = True
                logger.info("GraphMemory: tables ensured")
        except Exception as exc:
            logger.warning("GraphMemory: table creation failed (%s)", exc)

    async def extract_and_store(
        self,
        session_id: str,
        user_id: str,
        conversation_turns: List[Dict[str, str]],
    ) -> Tuple[List[Entity], List[Relationship]]:
        """Extract entities from conversation using LLM and store in graph."""
        if not conversation_turns:
            return [], []

        lines = [
            f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
            for m in conversation_turns
        ]
        conversation_text = "\n".join(lines)
        
        extracted = await self._extract_with_llm(conversation_text)
        entities = extracted.get("entities", [])
        relationships = extracted.get("relationships", [])

        stored_entities = []
        stored_relationships = []

        for ent_data in entities:
            name = ent_data.get("name", "").strip()
            ent_type = ent_data.get("type", ENTITY_CONCEPT).upper()
            if not name or ent_type not in ENTITY_TYPES:
                continue
            
            description = ent_data.get("description", "")
            entity = await self._store_entity(name, ent_type, {"description": description})
            if entity:
                stored_entities.append(entity)
                
                await self._store_mention(
                    entity_id=entity.id,
                    session_id=session_id,
                    turn_id=len(conversation_turns),
                    context_text=conversation_text[:500],
                )

        entity_name_to_id = {e.name.lower(): e.id for e in stored_entities}
        for rel_data in relationships:
            source_name = rel_data.get("source", "").strip().lower()
            target_name = rel_data.get("target", "").strip().lower()
            rel_type = rel_data.get("type", "related_to").strip()
            weight = float(rel_data.get("weight", 0.5))
            
            source_id = entity_name_to_id.get(source_name)
            target_id = entity_name_to_id.get(target_name)
            
            if not source_id:
                existing = await self._get_entity_by_name(source_name)
                if existing:
                    source_id = existing.id
            if not target_id:
                existing = await self._get_entity_by_name(target_name)
                if existing:
                    target_id = existing.id
                    
            if source_id and target_id:
                rel = await self._store_relationship(source_id, target_id, rel_type, weight)
                if rel:
                    stored_relationships.append(rel)

        logger.info(
            "GraphMemory: extracted %d entities, %d relationships from session %s",
            len(stored_entities), len(stored_relationships), session_id,
        )
        return stored_entities, stored_relationships

    async def _extract_with_llm(self, text: str) -> Dict:
        """Use LLM to extract entities and relationships."""
        if not self._llm:
            return self._heuristic_extract(text)
        
        try:
            prompt = render_prompt("entity_extraction", conversation_text=text[:3000])
        except PromptNotFoundError:
            logger.warning("entity_extraction prompt not found, using fallback")
            prompt = (
                "You are a knowledge graph extraction system. From the conversation below, "
                "extract entities and their relationships.\n\n"
                "Rules:\n"
                "- Entities: people (PERSON), organizations (ORG), documents (DOCUMENT), concepts (CONCEPT)\n"
                "- Only extract meaningful, specific entities (skip pronouns, generic terms)\n"
                "- Relationships: how entities connect (works_at, mentioned_in, related_to, part_of, created_by, etc.)\n"
                "- Weight: 0.1-1.0 indicating relationship strength\n"
                "- Each entity needs a short description\n\n"
                "Output format - JSON ONLY, no other text:\n"
                '{{"entities":[{{"name":"...","type":"PERSON|ORG|DOCUMENT|CONCEPT","description":"..."}}],"relationships":[{{"source":"entity name","target":"entity name","type":"...","weight":0.8}}]}}\n\n'
                f"Conversation:\n{text[:3000]}"
            )
        
        try:
            from langchain_core.messages import HumanMessage
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content.strip()
            if raw.startswith("{"):
                return json.loads(raw)
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as exc:
            logger.warning("LLM extraction failed (%s), heuristic fallback", exc)
        return self._heuristic_extract(text)

    def _heuristic_extract(self, text: str) -> Dict:
        """Simple heuristic entity extraction when LLM is unavailable."""
        entities = []
        relationships = []
        seen = set()
        
        pattern = r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b'
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            key = name.lower()
            if key not in seen and len(name) > 3:
                seen.add(key)
                ent_type = ENTITY_CONCEPT
                if any(w in name.lower() for w in ["inc", "corp", "ltd", "company", "organization"]):
                    ent_type = ENTITY_ORG
                elif any(w in name.lower() for w in ["doc", "report", "paper", "file"]):
                    ent_type = ENTITY_DOCUMENT
                entities.append({
                    "name": name,
                    "type": ent_type,
                    "description": f"Heuristic extraction: {name}",
                })
        
        ent_names = [e["name"] for e in entities]
        for i in range(len(ent_names) - 1):
            relationships.append({
                "source": ent_names[i],
                "target": ent_names[i + 1],
                "type": "mentioned_together",
                "weight": 0.3,
            })
        
        return {"entities": entities, "relationships": relationships}

    async def _store_entity(self, name: str, ent_type: str, metadata: Dict = None) -> Optional[Entity]:
        """Store or update an entity. Returns the stored entity."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        INSERT INTO entities (name, type, metadata)
                        VALUES ($1, $2, $3)
                        ON CONFLICT (LOWER(name), type) DO UPDATE SET
                            metadata = entities.metadata || EXCLUDED.metadata,
                            updated_at = NOW()
                        RETURNING id, name, type, metadata, created_at
                    """, name, ent_type, json.dumps(metadata or {}))
                    if row:
                        return Entity(
                            id=str(row["id"]),
                            name=row["name"],
                            type=row["type"],
                            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                            created_at=row["created_at"].timestamp() if hasattr(row["created_at"], "timestamp") else 0,
                        )
            except Exception as exc:
                logger.warning("Entity store failed (%s)", exc)
        
        key = name.lower()
        if key in self._local_entities:
            ent = self._local_entities[key]
            if metadata:
                ent.metadata.update(metadata)
            return ent
        entity = Entity(
            id=f"local_{len(self._local_entities)}",
            name=name,
            type=ent_type,
            metadata=metadata or {},
            created_at=time.time(),
        )
        self._local_entities[key] = entity
        return entity

    async def _store_relationship(
        self, source_id: str, target_id: str, rel_type: str, weight: float = 1.0
    ) -> Optional[Relationship]:
        """Store a relationship between two entities."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        INSERT INTO relationships (source_entity_id, target_entity_id, relationship_type, weight)
                        VALUES ($1, $2, $3, $4)
                        ON CONFLICT DO NOTHING
                        RETURNING id, source_entity_id, target_entity_id, relationship_type, weight, created_at
                    """, source_id, target_id, rel_type, weight)
                    if row:
                        return Relationship(
                            id=str(row["id"]),
                            source_entity_id=str(row["source_entity_id"]),
                            target_entity_id=str(row["target_entity_id"]),
                            relationship_type=row["relationship_type"],
                            weight=row["weight"],
                            created_at=row["created_at"].timestamp() if hasattr(row["created_at"], "timestamp") else 0,
                        )
            except Exception as exc:
                logger.warning("Relationship store failed (%s)", exc)
        
        rel = Relationship(
            id=f"local_rel_{len(self._local_relationships)}",
            source_entity_id=source_id,
            target_entity_id=target_id,
            relationship_type=rel_type,
            weight=weight,
            created_at=time.time(),
        )
        self._local_relationships.append(rel)
        return rel

    async def _store_mention(
        self, entity_id: str, session_id: str, turn_id: int, context_text: str
    ) -> Optional[EntityMention]:
        """Store an entity mention."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow("""
                        INSERT INTO entity_mentions (entity_id, session_id, turn_id, context_text)
                        VALUES ($1, $2, $3, $4)
                        RETURNING id, entity_id, session_id, turn_id, context_text, created_at
                    """, entity_id, session_id, turn_id, context_text)
                    if row:
                        return EntityMention(
                            id=str(row["id"]),
                            entity_id=str(row["entity_id"]),
                            session_id=row["session_id"],
                            turn_id=row["turn_id"],
                            context_text=row["context_text"],
                            created_at=row["created_at"].timestamp() if hasattr(row["created_at"], "timestamp") else 0,
                        )
            except Exception as exc:
                logger.warning("Mention store failed (%s)", exc)
        
        mention = EntityMention(
            id=f"local_men_{len(self._local_mentions)}",
            entity_id=entity_id,
            session_id=session_id,
            turn_id=turn_id,
            context_text=context_text,
            created_at=time.time(),
        )
        self._local_mentions.append(mention)
        return mention

    async def retrieve_related(self, entity_name: str, depth: int = 2) -> List[Dict[str, Any]]:
        """Find related entities using recursive CTE traversal."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        WITH RECURSIVE related AS (
                            SELECT 
                                e.id, e.name, e.type, e.metadata,
                                r.relationship_type, r.weight,
                                1 as depth,
                                ARRAY[e.name] as path
                            FROM entities e
                            JOIN relationships r ON r.source_entity_id = e.id
                            WHERE LOWER(e.name) = LOWER($1)
                            
                            UNION
                            
                            SELECT 
                                e.id, e.name, e.type, e.metadata,
                                r.relationship_type, r.weight,
                                rel.depth + 1,
                                rel.path || e.name
                            FROM related rel
                            JOIN relationships r ON r.source_entity_id = 
                                (SELECT id FROM entities WHERE LOWER(name) = LOWER(rel.path[array_length(rel.path, 1)]))
                            JOIN entities e ON e.id = r.target_entity_id
                            WHERE rel.depth < $2
                        )
                        SELECT DISTINCT ON (id) * FROM related
                        ORDER BY id, depth ASC
                    """, entity_name, depth)
                    
                    return [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "type": r["type"],
                            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                            "relationship_type": r["relationship_type"],
                            "weight": r["weight"],
                            "depth": r["depth"],
                            "path": r["path"],
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("retrieve_related failed (%s)", exc)
        
        return self._in_memory_related(entity_name, depth)

    def _in_memory_related(self, entity_name: str, depth: int) -> List[Dict[str, Any]]:
        """Simple BFS for in-memory fallback."""
        start_key = entity_name.lower()
        start = self._local_entities.get(start_key)
        if not start:
            return []
        
        visited = {start_key}
        results = []
        queue = [(start, 0, [start.name])]
        
        while queue:
            current, d, path = queue.pop(0)
            if d >= depth:
                continue
            
            for rel in self._local_relationships:
                next_ent = None
                if rel.source_entity_id == current.id:
                    next_ent = next(
                        (e for e in self._local_entities.values() if e.id == rel.target_entity_id),
                        None,
                    )
                elif rel.target_entity_id == current.id:
                    next_ent = next(
                        (e for e in self._local_entities.values() if e.id == rel.source_entity_id),
                        None,
                    )
                
                if next_ent and next_ent.name.lower() not in visited:
                    visited.add(next_ent.name.lower())
                    new_path = path + [next_ent.name]
                    results.append({
                        "id": next_ent.id,
                        "name": next_ent.name,
                        "type": next_ent.type,
                        "metadata": next_ent.metadata,
                        "relationship_type": rel.relationship_type,
                        "weight": rel.weight,
                        "depth": d + 1,
                        "path": new_path,
                    })
                    queue.append((next_ent, d + 1, new_path))
        
        return results

    async def get_entity_context(self, entity_name: str) -> Dict[str, Any]:
        """Get all facts about an entity: its info, relationships, and mentions."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    ent_row = await conn.fetchrow(
                        "SELECT id, name, type, metadata, created_at FROM entities WHERE LOWER(name) = LOWER($1)",
                        entity_name,
                    )
                    if not ent_row:
                        return {"found": False}
                    
                    entity_id = str(ent_row["id"])
                    
                    rel_rows = await conn.fetch("""
                        SELECT r.*, 
                               e1.name as source_name, 
                               e2.name as target_name
                        FROM relationships r
                        JOIN entities e1 ON e1.id = r.source_entity_id
                        JOIN entities e2 ON e2.id = r.target_entity_id
                        WHERE r.source_entity_id = $1 OR r.target_entity_id = $1
                        ORDER BY r.weight DESC
                    """, entity_id)
                    
                    mention_rows = await conn.fetch("""
                        SELECT session_id, turn_id, context_text, created_at
                        FROM entity_mentions
                        WHERE entity_id = $1
                        ORDER BY created_at DESC
                        LIMIT 20
                    """, entity_id)
                    
                    return {
                        "found": True,
                        "entity": {
                            "id": entity_id,
                            "name": ent_row["name"],
                            "type": ent_row["type"],
                            "metadata": json.loads(ent_row["metadata"]) if isinstance(ent_row["metadata"], str) else ent_row["metadata"],
                        },
                        "relationships": [
                            {
                                "type": r["relationship_type"],
                                "weight": r["weight"],
                                "source": r["source_name"],
                                "target": r["target_name"],
                            }
                            for r in rel_rows
                        ],
                        "mentions": [
                            {
                                "session_id": m["session_id"],
                                "context": m["context_text"][:200],
                            }
                            for m in mention_rows
                        ],
                    }
            except Exception as exc:
                logger.warning("get_entity_context failed (%s)", exc)
        
        key = entity_name.lower()
        ent = self._local_entities.get(key)
        if not ent:
            return {"found": False}
        
        relationships = []
        for rel in self._local_relationships:
            if rel.source_entity_id == ent.id or rel.target_entity_id == ent.id:
                source = next((e for e in self._local_entities.values() if e.id == rel.source_entity_id), None)
                target = next((e for e in self._local_entities.values() if e.id == rel.target_entity_id), None)
                if source and target:
                    relationships.append({
                        "type": rel.relationship_type,
                        "weight": rel.weight,
                        "source": source.name,
                        "target": target.name,
                    })
        
        mentions = [
            {"session_id": m.session_id, "context": m.context_text[:200]}
            for m in self._local_mentions
            if m.entity_id == ent.id
        ]
        
        return {
            "found": True,
            "entity": ent.to_dict(),
            "relationships": relationships,
            "mentions": mentions[:20],
        }

    async def find_path(self, entity_a: str, entity_b: str) -> Optional[List[Dict[str, Any]]]:
        """Find relationship path between two entities using BFS."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        WITH RECURSIVE path_finder AS (
                            SELECT 
                                e.id, e.name, e.type,
                                ARRAY[e.id] as visited,
                                ARRAY[ROW(e.name, '', 0.0)]::text[] as path_steps,
                                0 as depth
                            FROM entities e
                            WHERE LOWER(e.name) = LOWER($1)
                            
                            UNION
                            
                            SELECT 
                                e.id, e.name, e.type,
                                pf.visited || e.id,
                                pf.path_steps || ROW(e.name, r.relationship_type, r.weight)::text,
                                pf.depth + 1
                            FROM path_finder pf
                            JOIN relationships r ON r.source_entity_id = pf.visited[array_length(pf.visited, 1)]
                                OR r.target_entity_id = pf.visited[array_length(pf.visited, 1)]
                            JOIN entities e ON 
                                (e.id = r.source_entity_id AND e.id != pf.visited[array_length(pf.visited, 1)])
                                OR (e.id = r.target_entity_id AND e.id != pf.visited[array_length(pf.visited, 1)])
                            WHERE e.id != ALL(pf.visited) AND pf.depth < 5
                        )
                        SELECT * FROM path_finder
                        WHERE LOWER(name) = LOWER($2)
                        ORDER BY depth ASC
                        LIMIT 1
                    """, entity_a, entity_b)
                    
                    if rows:
                        row = rows[0]
                        return {
                            "found": True,
                            "depth": row["depth"],
                            "path_steps": row["path_steps"],
                        }
                    return {"found": False}
            except Exception as exc:
                logger.warning("find_path failed (%s)", exc)
        
        return self._in_memory_find_path(entity_a, entity_b)

    def _in_memory_find_path(self, entity_a: str, entity_b: str) -> Optional[Dict[str, Any]]:
        """BFS for path finding in memory."""
        start_key = entity_a.lower()
        target_key = entity_b.lower()
        
        if start_key not in self._local_entities or target_key not in self._local_entities:
            return {"found": False}
        
        start = self._local_entities[start_key]
        target = self._local_entities[target_key]
        
        if start.id == target.id:
            return {"found": True, "depth": 0, "path_steps": [start.name]}
        
        queue = [(start, [start.name])]
        visited = {start.id}
        
        while queue:
            current, path = queue.pop(0)
            if len(path) > 6:
                break
            
            for rel in self._local_relationships:
                next_id = None
                if rel.source_entity_id == current.id:
                    next_id = rel.target_entity_id
                elif rel.target_entity_id == current.id:
                    next_id = rel.source_entity_id
                
                if next_id and next_id not in visited:
                    visited.add(next_id)
                    next_ent = next((e for e in self._local_entities.values() if e.id == next_id), None)
                    if next_ent:
                        new_path = path + [next_ent.name]
                        if next_ent.id == target.id:
                            return {"found": True, "depth": len(new_path) - 1, "path_steps": new_path}
                        queue.append((next_ent, new_path))
        
        return {"found": False}

    async def get_session_entities(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all entities mentioned in a session."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT e.id, e.name, e.type, e.metadata, COUNT(m.id) as mention_count
                        FROM entities e
                        JOIN entity_mentions m ON m.entity_id = e.id
                        WHERE m.session_id = $1
                        GROUP BY e.id, e.name, e.type, e.metadata
                        ORDER BY mention_count DESC
                    """, session_id)
                    
                    return [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "type": r["type"],
                            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                            "mention_count": r["mention_count"],
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("get_session_entities failed (%s)", exc)
        
        entity_counts: Dict[str, int] = {}
        for m in self._local_mentions:
            if m.session_id == session_id:
                entity_counts[m.entity_id] = entity_counts.get(m.entity_id, 0) + 1
        
        results = []
        for ent_id, count in entity_counts.items():
            ent = next((e for e in self._local_entities.values() if e.id == ent_id), None)
            if ent:
                results.append({
                    "id": ent.id,
                    "name": ent.name,
                    "type": ent.type,
                    "metadata": ent.metadata,
                    "mention_count": count,
                })
        
        return sorted(results, key=lambda x: x["mention_count"], reverse=True)

    async def _get_entity_by_name(self, name: str) -> Optional[Entity]:
        """Look up an entity by name."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    row = await conn.fetchrow(
                        "SELECT id, name, type, metadata FROM entities WHERE LOWER(name) = LOWER($1)",
                        name,
                    )
                    if row:
                        return Entity(
                            id=str(row["id"]),
                            name=row["name"],
                            type=row["type"],
                            metadata=json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                        )
            except Exception as exc:
                logger.warning("Entity lookup failed (%s)", exc)
        
        return self._local_entities.get(name.lower())

    async def search_entities(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search entities by name (fuzzy prefix match)."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch("""
                        SELECT id, name, type, metadata
                        FROM entities
                        WHERE LOWER(name) LIKE LOWER($1)
                        ORDER BY name ASC
                        LIMIT $2
                    """, f"%{query}%", limit)
                    
                    return [
                        {
                            "id": str(r["id"]),
                            "name": r["name"],
                            "type": r["type"],
                            "metadata": json.loads(r["metadata"]) if isinstance(r["metadata"], str) else r["metadata"],
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("Entity search failed (%s)", exc)
        
        query_lower = query.lower()
        results = [
            {"id": e.id, "name": e.name, "type": e.type, "metadata": e.metadata}
            for e in self._local_entities.values()
            if query_lower in e.name.lower()
        ]
        return results[:limit]

    async def get_stats(self) -> Dict[str, Any]:
        """Get graph statistics."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    ent_count = await conn.fetchval("SELECT COUNT(*) FROM entities")
                    rel_count = await conn.fetchval("SELECT COUNT(*) FROM relationships")
                    mention_count = await conn.fetchval("SELECT COUNT(*) FROM entity_mentions")
                    return {
                        "entities": ent_count,
                        "relationships": rel_count,
                        "mentions": mention_count,
                        "storage": "postgresql",
                    }
            except Exception as exc:
                logger.warning("Stats query failed (%s)", exc)
        
        return {
            "entities": len(self._local_entities),
            "relationships": len(self._local_relationships),
            "mentions": len(self._local_mentions),
            "storage": "in-memory",
        }

    async def delete_document_mentions(
        self,
        document_id: str,
        document_name: str = "",
        user_id: str = "",
    ) -> Dict[str, Any]:
        """Tombstone the graph mentions that quote a deleted document.

        Phase 2: a mention stores the conversation text it was extracted from,
        so it is the only graph row that can leak a deleted document's content
        back into an answer. Entities and relationships are cross-session
        knowledge and are deliberately left in place — only the provenance rows
        referencing the document are removed.
        """
        report: Dict[str, Any] = {
            "mentions_deleted": 0,
            "backend": "memory",
        }
        needles = document_needles(document_id, document_name)
        if not needles:
            return report

        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    clauses = []
                    params: List[Any] = []
                    for needle in needles:
                        params.append(postgres_reference_pattern(needle))
                        clauses.append(f"context_text ~* ${len(params)}")
                    result = await conn.execute(
                        "DELETE FROM entity_mentions WHERE " + " OR ".join(clauses),
                        *params,
                    )
                    try:
                        report["mentions_deleted"] = int(str(result).split()[-1])
                    except (IndexError, ValueError):
                        pass
                report["backend"] = "postgresql"
                return report
            except Exception as exc:
                logger.warning(
                    "Document mention purge failed (%s), in-memory fallback", exc
                )

        kept = [
            m for m in self._local_mentions
            if not references_document(m.context_text, needles)
        ]
        report["mentions_deleted"] = len(self._local_mentions) - len(kept)
        self._local_mentions[:] = kept
        if report["mentions_deleted"]:
            logger.info(
                "GraphMemory: purged %d mention(s) referencing a deleted document",
                report["mentions_deleted"],
            )
        return report

    async def close(self):
        """Close the database pool."""
        if self._pool and hasattr(self._pool, "close"):
            await self._pool.close()
