"""
Long-term memory - PostgreSQL-backed persistent memory across sessions.
Stores important facts extracted from conversations per user.
Retrieved at session start to provide continuity across sessions.

Issue #26: When PostgreSQL is unavailable, the system falls back to an
in-memory dictionary. This means memory is LOST on process restart. In
production, PostgreSQL must be available; the fallback is for local dev only.
"""

import json
import logging
import os
import time
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from settings import settings
from memory.document_reference import (
    document_needles,
    postgres_reference_pattern,
    references_document,
)

logger = logging.getLogger(__name__)

# Environments where in-memory fallback is acceptable.
_PERMISSIVE_ENVS = {"local", "dev", "development", "test"}


def _is_strict_env() -> bool:
    env = os.getenv("APP_ENV", "production").strip().lower()
    return env not in _PERMISSIVE_ENVS


try:
    import asyncpg

    HAS_PG = True
except ImportError:
    HAS_PG = False
    logger.warning(
        "asyncpg not installed - long-term memory will use in-memory fallback (data lost on restart)."
    )


def _pg_dsn() -> str:
    """Build the DSN for the shared Postgres memory store.

    ``POSTGRES_SSLMODE`` (unset by default) is appended when present: managed
    Postgres — Neon in particular — refuses plaintext connections, and without
    this the whole memory layer silently fell back to in-process RAM, losing
    every fact on restart. ``sslmode=require`` enables TLS without requiring a
    CA bundle, which is exactly what a pooled endpoint expects.
    """
    dsn = (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )
    sslmode = os.getenv("POSTGRES_SSLMODE", "").strip()
    if sslmode:
        sep = "&" if "?" in dsn else "?"
        dsn = f"{dsn}{sep}sslmode={sslmode}"
    return dsn


@dataclass
class LongTermFact:
    fact_text: str
    importance: float = 0.5
    category: str = "general"
    user_id: str = ""
    session_id: str = ""
    fact_id: str = ""
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "fact_text": self.fact_text,
            "importance": self.importance,
            "category": self.category,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "created_at": self.created_at,
        }


FACT_EXTRACTION_PROMPT = """You are a memory extraction system. From the conversation below, extract 1-3 important facts that should be remembered LONG-TERM about the user or their preferences.

Rules:
- Only extract facts that are USEFUL to remember across sessions.
- Skip trivial/greeting content.
- Each fact must be a complete sentence.
- Rate importance 0.0-1.0 (1.0 = critical).
- Assign category: "personal_info", "preference", "goal", "project", "technical", "general".

Output format - JSON array ONLY:
[
  {"fact": "...", "importance": 0.8, "category": "preference"}
]

Conversation:
{conversation_text}
"""


class LongTermMemory:
    """PostgreSQL-backed long-term memory with in-memory fallback.

    Issue #26: The in-memory fallback loses all data on process restart.
    In production (non-local env), PG unavailability is logged at ERROR level.
    """

    def __init__(self, llm_router=None):
        self._pool: Optional[Any] = None
        self._llm = llm_router
        self._local: Dict[str, List[LongTermFact]] = {}
        self._local_turns: Dict[str, List[Dict]] = {}
        self._table_ensured = False
        self._pg_warned = False

    async def _get_pool(self):
        if self._pool is None and HAS_PG:
            try:
                self._pool = await asyncpg.create_pool(
                    _pg_dsn(), min_size=1, max_size=5, timeout=5
                )
                logger.info("LongTermMemory: connected to PostgreSQL")
            except Exception as exc:
                if _is_strict_env():
                    logger.error(
                        "LongTermMemory: PostgreSQL unavailable (%s). "
                        "Falling back to in-memory storage - DATA WILL BE LOST ON RESTART. "
                        "This is unacceptable in production. Ensure PostgreSQL is running.",
                        exc,
                    )
                else:
                    logger.warning(
                        "LongTermMemory: PG unavailable (%s), using in-memory fallback "
                        "(data will be lost on restart - dev mode only).",
                        exc,
                    )
                self._pool = False
        return self._pool if self._pool else None

    async def ensure_table(self):
        pool = await self._get_pool()
        if not pool or self._table_ensured:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS long_term_memory (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id     VARCHAR(255) NOT NULL,
                        session_id  VARCHAR(64)  NOT NULL,
                        fact_text   TEXT         NOT NULL,
                        importance  FLOAT        NOT NULL DEFAULT 0.5,
                        category    VARCHAR(64)  DEFAULT 'general',
                        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
                        accessed_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_ltm_user ON long_term_memory(user_id);
                """)
                self._table_ensured = True
                logger.info("LongTermMemory: table ensured")
        except Exception as exc:
            logger.warning("LongTermMemory: table creation failed (%s)", exc)

    async def extract_and_store(
        self,
        session_id: str,
        user_id: str,
        conversation_history: List[Dict[str, str]],
    ) -> List[LongTermFact]:
        if not conversation_history:
            return []
        lines = [
            f"{m.get('role', 'user').capitalize()}: {m.get('content', '')}"
            for m in conversation_history
        ]
        facts = await self._extract_facts_with_llm("\n".join(lines))
        stored = []
        for fd in facts:
            f = LongTermFact(
                fact_text=fd.get("fact", ""),
                importance=float(fd.get("importance", 0.5)),
                category=fd.get("category", "general"),
                user_id=user_id,
                session_id=session_id,
                created_at=time.time(),
            )
            if f.fact_text:
                await self._store_fact(f)
                stored.append(f)
        if stored:
            logger.info(
                "LongTermMemory: stored %d fact(s) for user %s", len(stored), user_id
            )
        return stored

    async def _extract_facts_with_llm(self, text: str) -> List[Dict]:
        if not self._llm:
            return self._heuristic_extract(text)
        prompt = FACT_EXTRACTION_PROMPT.format(conversation_text=text[:3000])
        try:
            from langchain_core.messages import HumanMessage

            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = response.content.strip()
            if raw.startswith("["):
                return json.loads(raw)
            m = re.search(r"\[.*?\]", raw, re.DOTALL)
            if m:
                return json.loads(m.group())
        except Exception as exc:
            logger.warning("LLM extraction failed (%s), heuristic fallback", exc)
        return self._heuristic_extract(text)

    def _heuristic_extract(self, text: str) -> List[Dict]:
        """Extract sentences with preference keywords."""
        facts = []
        keywords = [
            "i like",
            "i want",
            "i am",
            "my name",
            "i prefer",
            "i need",
            "my goal",
            "i work",
            "i have been",
            "i don't like",
        ]
        for line in text.lower().split("\n"):
            for kw in keywords:
                if kw in line:
                    for sent in line.split("."):
                        if kw in sent:
                            facts.append(
                                {
                                    "fact": sent.strip().capitalize(),
                                    "importance": 0.5,
                                    "category": "general",
                                }
                            )
                            break
                    break
        return facts[:3]

    async def _store_fact(self, fact: LongTermFact):
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO long_term_memory (user_id, session_id, fact_text, importance, category) VALUES ($1,$2,$3,$4,$5)",
                        fact.user_id,
                        fact.session_id,
                        fact.fact_text,
                        fact.importance,
                        fact.category,
                    )
                return
            except Exception as exc:
                logger.warning("Store failed (%s), in-memory fallback", exc)
        if fact.user_id not in self._local:
            self._local[fact.user_id] = []
        self._local[fact.user_id].append(fact)
        if len(self._local[fact.user_id]) > 50:
            self._local[fact.user_id] = self._local[fact.user_id][-50:]

    async def retrieve(self, user_id: str, limit: int = 10) -> List[LongTermFact]:
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT id, user_id, session_id, fact_text, importance, category, created_at "
                        "FROM long_term_memory WHERE user_id=$1 ORDER BY importance DESC, created_at DESC LIMIT $2",
                        user_id,
                        limit,
                    )
                    facts = [
                        LongTermFact(
                            fact_id=str(r["id"]),
                            fact_text=r["fact_text"],
                            importance=r["importance"],
                            category=r["category"],
                            user_id=r["user_id"],
                            session_id=r["session_id"],
                            created_at=r["created_at"].timestamp()
                            if hasattr(r["created_at"], "timestamp")
                            else 0,
                        )
                        for r in rows
                    ]
                    if facts:
                        async with pool.acquire() as conn:
                            await conn.execute(
                                "UPDATE long_term_memory SET accessed_at=NOW() WHERE user_id=$1",
                                user_id,
                            )
                    return facts
            except Exception as exc:
                logger.warning("Retrieve failed (%s), in-memory fallback", exc)
        facts = self._local.get(user_id, [])
        return sorted(facts, key=lambda f: f.importance, reverse=True)[:limit]

    async def ensure_turn_table(self):
        """Ensure the conversation_turns table exists."""
        pool = await self._get_pool()
        if not pool:
            return
        try:
            async with pool.acquire() as conn:
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS conversation_turns (
                        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                        user_id     VARCHAR(255) NOT NULL,
                        session_id  VARCHAR(64)  NOT NULL,
                        role        VARCHAR(32)  NOT NULL,
                        content     TEXT         NOT NULL,
                        agent_type  VARCHAR(64)  DEFAULT '',
                        created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS idx_ct_user_session ON conversation_turns(user_id, session_id);
                """)
        except Exception as exc:
            logger.warning("Conversation turns table creation failed (%s)", exc)

    async def save_turn(
        self,
        user_id: str,
        session_id: str,
        role: str,
        content: str,
        agent_type: str = "",
    ) -> None:
        """Save a conversation turn to long-term storage."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO conversation_turns (user_id, session_id, role, content, agent_type) "
                        "VALUES ($1, $2, $3, $4, $5)",
                        user_id,
                        session_id,
                        role,
                        content,
                        agent_type,
                    )
                return
            except Exception as exc:
                logger.warning("save_turn failed (%s), in-memory fallback", exc)
        if user_id not in self._local_turns:
            self._local_turns[user_id] = []
        self._local_turns[user_id].append(
            {
                "session_id": session_id,
                "role": role,
                "content": content,
                "agent_type": agent_type,
            }
        )
        if len(self._local_turns[user_id]) > 200:
            self._local_turns[user_id] = self._local_turns[user_id][-200:]

    async def get_history(
        self,
        session_id: str,
        user_id: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get conversation history for a session."""
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    rows = await conn.fetch(
                        "SELECT role, content, agent_type, created_at "
                        "FROM conversation_turns "
                        "WHERE user_id=$1 AND session_id=$2 "
                        "ORDER BY created_at ASC LIMIT $3",
                        user_id,
                        session_id,
                        limit,
                    )
                    return [
                        {
                            "role": r["role"],
                            "content": r["content"],
                            "agent_type": r["agent_type"],
                        }
                        for r in rows
                    ]
            except Exception as exc:
                logger.warning("get_history failed (%s), in-memory fallback", exc)
        turns = self._local_turns.get(user_id, [])
        return [
            {
                "role": t["role"],
                "content": t["content"],
                "agent_type": t.get("agent_type", ""),
            }
            for t in turns
            if t.get("session_id") == session_id
        ][-limit:]

    async def delete_user_memory(self, user_id: str):
        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    await conn.execute(
                        "DELETE FROM long_term_memory WHERE user_id=$1", user_id
                    )
                return
            except Exception as exc:
                logger.warning("Delete failed (%s)", exc)
        self._local.pop(user_id, None)

    async def delete_document_memories(
        self,
        document_id: str,
        user_id: str = "",
        document_name: str = "",
    ) -> Dict[str, Any]:
        """Tombstone the durable memory entries that reference a document.

        Phase 2: after a document is deleted, its text must stop reaching an
        answer through memory. Facts and conversation turns are stored without a
        document foreign key, so entries are matched on the document reference
        (id, or the document name when the caller supplies it) — see
        memory.document_reference. An entry that cannot be attributed is left in
        place rather than risking a wrong delete.

        Returns per-table delete counts and which backend served them.
        """
        report: Dict[str, Any] = {
            "facts_deleted": 0,
            "turns_deleted": 0,
            "backend": "memory",
        }
        needles = document_needles(document_id, document_name)
        if not needles:
            return report

        pool = await self._get_pool()
        if pool:
            try:
                async with pool.acquire() as conn:
                    report["facts_deleted"] = await self._delete_referencing(
                        conn, "long_term_memory", "fact_text", needles, user_id
                    )
                    report["turns_deleted"] = await self._delete_referencing(
                        conn, "conversation_turns", "content", needles, user_id
                    )
                report["backend"] = "postgres"
                return report
            except Exception as exc:
                logger.warning(
                    "Document memory purge failed (%s), in-memory fallback", exc
                )

        facts_deleted, turns_deleted = self._delete_local_document_memories(
            needles, user_id
        )
        report["facts_deleted"] = facts_deleted
        report["turns_deleted"] = turns_deleted
        return report

    @staticmethod
    async def _delete_referencing(
        conn: Any,
        table: str,
        column: str,
        needles: List[str],
        user_id: str,
    ) -> int:
        """DELETE rows of `table` whose `column` references the document."""
        clauses: List[str] = []
        params: List[Any] = []
        for needle in needles:
            params.append(postgres_reference_pattern(needle))
            clauses.append(f"{column} ~* ${len(params)}")
        if user_id:
            params.append(user_id)
            clauses.append(f"user_id = ${len(params)}")
        result = await conn.execute(
            f"DELETE FROM {table} WHERE " + " AND ".join(clauses), *params
        )
        # asyncpg returns a command tag such as "DELETE 3".
        try:
            return int(str(result).split()[-1])
        except (IndexError, ValueError):
            return 0

    def _delete_local_document_memories(
        self, needles: List[str], user_id: str
    ) -> Tuple[int, int]:
        """In-memory fallback for delete_document_memories."""
        facts_deleted = 0
        for stored_user in list(self._local.keys()):
            if user_id and stored_user != user_id:
                continue
            facts = self._local[stored_user]
            kept = [
                f for f in facts if not references_document(f.fact_text, needles)
            ]
            facts_deleted += len(facts) - len(kept)
            if kept:
                self._local[stored_user] = kept
            else:
                self._local.pop(stored_user, None)

        turns_deleted = 0
        for stored_user in list(self._local_turns.keys()):
            if user_id and stored_user != user_id:
                continue
            turns = self._local_turns[stored_user]
            kept = [
                t for t in turns if not references_document(t.get("content", ""), needles)
            ]
            turns_deleted += len(turns) - len(kept)
            if kept:
                self._local_turns[stored_user] = kept
            else:
                self._local_turns.pop(stored_user, None)

        if facts_deleted or turns_deleted:
            logger.info(
                "LongTermMemory: purged %d fact(s) and %d turn(s) referencing a "
                "deleted document",
                facts_deleted,
                turns_deleted,
            )
        return facts_deleted, turns_deleted

    async def close(self):
        if self._pool and hasattr(self._pool, "close"):
            await self._pool.close()
