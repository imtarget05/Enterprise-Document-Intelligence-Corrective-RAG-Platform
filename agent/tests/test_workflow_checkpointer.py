"""Checkpointer persistence tests for the LangGraph workflow."""

import os

import pytest


def test_compiled_workflow_has_checkpointer():
    """compile() phải truyền checkpointer, không được None."""
    from graph.workflow import build_workflow

    graph = build_workflow()
    assert getattr(graph, "checkpointer", None) is not None


def test_checkpointer_falls_back_to_memory_in_test_env():
    """Khi APP_ENV=test, checkpointer là in-memory saver (RAM)."""
    from langgraph.checkpoint.memory import MemorySaver

    from graph.workflow import _build_checkpointer

    assert os.environ.get("APP_ENV") == "test"
    saver = _build_checkpointer()
    assert isinstance(saver, MemorySaver)


@pytest.fixture
def durable_checkpoint_env(tmp_path, monkeypatch):
    """Force the durable SQLite checkpointer into a throwaway file.

    Outside APP_ENV=test the workflow must compile with a *persistent*
    checkpointer, and the test must never touch the real checkpoints.sqlite.
    """
    monkeypatch.setenv("APP_ENV", "local")
    db_path = tmp_path / "checkpoints.sqlite"
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DB", str(db_path))
    from graph import workflow

    try:
        yield workflow
    finally:
        workflow.close_checkpointers()


def test_durable_checkpointer_is_sqlite_backed(durable_checkpoint_env):
    """Ngoài APP_ENV=test, checkpointer phải bền vững (SQLite), không phải RAM."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    saver = durable_checkpoint_env._build_checkpointer()
    assert isinstance(saver, AsyncSqliteSaver)


def test_durable_checkpointer_is_reused(durable_checkpoint_env):
    """Mỗi build_workflow() tái dùng một connection duy nhất cho cùng DB file."""
    assert (
        durable_checkpoint_env._build_checkpointer()
        is durable_checkpoint_env._build_checkpointer()
    )


def test_compiled_workflow_uses_durable_checkpointer(durable_checkpoint_env):
    """build_workflow() ngoài APP_ENV=test phải compile với checkpointer bền vững."""
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    graph = durable_checkpoint_env.build_workflow()
    assert isinstance(graph.checkpointer, AsyncSqliteSaver)


def test_checkpoint_survives_a_restart(durable_checkpoint_env):
    """Checkpoint ghi bởi một saver phải đọc được bởi saver mới (restart)."""
    from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

    config = {"configurable": {"thread_id": "durable-1", "checkpoint_ns": ""}}
    checkpoint: Checkpoint = {
        "v": 1,
        "id": "00000000-0000-4000-8000-000000000001",
        "ts": "2026-01-01T00:00:00+00:00",
        "channel_values": {"query": "checkpoint phải sống sót"},
        "channel_versions": {"query": 1},
        "versions_seen": {},
        "updated_channels": ["query"],
    }
    metadata: CheckpointMetadata = {"step": 1, "source": "input"}

    saver = durable_checkpoint_env._build_checkpointer()
    saver.put(config, checkpoint, metadata, {})

    # Simulate a process restart: drop every cached saver and open a new one.
    durable_checkpoint_env.close_checkpointers()
    reopened = durable_checkpoint_env._build_checkpointer()

    stored = reopened.get_tuple(config)
    assert stored is not None
    assert stored.checkpoint["channel_values"]["query"] == "checkpoint phải sống sót"


def test_missing_sqlite_falls_back_to_memory(durable_checkpoint_env, monkeypatch):
    """ImportError/IO error → compile vẫn chạy, checkpointer về in-memory."""
    import builtins

    from langgraph.checkpoint.memory import MemorySaver

    real_import = builtins.__import__

    def _no_sqlite(name, *args, **kwargs):
        if name.startswith("aiosqlite") or name.startswith(
            "langgraph.checkpoint.sqlite"
        ):
            raise ImportError("sqlite checkpointer is not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_sqlite)
    saver = durable_checkpoint_env._build_checkpointer()
    assert isinstance(saver, MemorySaver)
