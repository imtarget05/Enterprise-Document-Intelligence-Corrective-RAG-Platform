"""Shared (Postgres/Neon) checkpoint storage — Sprint 2: SQLite -> managed PG.

``DATABASE_URL`` / ``NEON_DATABASE_URL`` naming a Postgres URL moves the
LangGraph checkpoints out of the container's local SQLite file into a store
every replica reaches and every redeploy keeps. The switch is opt-in and,
unless ``LANGGRAPH_CHECKPOINT_SHARED_REQUIRED`` is set, fail-open: a database
blip logs loudly and keeps the SQLite file instead of taking the agent down.

Real-database behaviour is covered by the ``integration`` test, which runs only
when ``TEST_POSTGRES_DSN`` points at a disposable Postgres.
"""

import os

import pytest

from graph import workflow


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch, tmp_path):
    """No shared URL by default, throwaway SQLite fallback, clean registries."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.delenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_DB", str(tmp_path / "checkpoints.sqlite"))
    workflow._open_checkpointers.clear()
    workflow._shared_open_failures.clear()
    yield
    workflow.close_checkpointers()
    workflow._open_checkpointers.clear()
    workflow._shared_open_failures.clear()


# --------------------------------------------------------------- URL parsing


@pytest.mark.parametrize("value", ["", "   ", "mysql://db/x", "not-a-url", "sqlite:///x"])
def test_non_postgres_values_never_enable_shared_storage(monkeypatch, value):
    monkeypatch.setenv("DATABASE_URL", value)
    assert workflow._shared_postgres_url() == ""


@pytest.mark.parametrize("scheme", ["postgres://", "postgresql://"])
def test_postgres_schemes_enable_shared_storage(monkeypatch, scheme):
    monkeypatch.setenv("DATABASE_URL", f"{scheme}user:pw@db.example/x")
    assert workflow._shared_postgres_url().startswith(scheme)


def test_database_url_wins_over_neon(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://render/db")
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://neon/db")
    assert workflow._shared_postgres_url() == "postgresql://render/db"


def test_neon_url_is_accepted_when_no_database_url(monkeypatch):
    monkeypatch.setenv("NEON_DATABASE_URL", "postgresql://neon/db")
    assert workflow._shared_postgres_url() == "postgresql://neon/db"


def test_redact_url_hides_the_password():
    redacted = workflow._redact_url("postgresql://agent:s3cret@db.example:5432/x")
    assert "s3cret" not in redacted
    assert redacted == "postgresql://***@db.example:5432/x"


def test_redact_url_leaves_urls_without_credentials_alone():
    assert workflow._redact_url("postgresql://db.example/x") == "postgresql://db.example/x"


@pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
def test_shared_required_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", value)
    assert workflow._shared_required() is True


def test_shared_required_defaults_to_off(monkeypatch):
    assert workflow._shared_required() is False


# -------------------------------------------------------------- fail-open PG


def _fail_open(url):
    raise ConnectionError("database is unreachable")


def test_postgres_failure_falls_back_to_the_sqlite_file(monkeypatch):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _fail_open)

    saver = workflow._build_checkpointer()

    assert isinstance(saver, AsyncSqliteSaver)
    assert workflow._shared_open_failures, "the failure must be remembered"


def test_postgres_failure_is_attempted_once_per_process(monkeypatch):
    """A down database must not spawn a connection thread on every build."""
    calls = []

    def _counting_fail(url):
        calls.append(url)
        raise ConnectionError("database is unreachable")

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _counting_fail)

    workflow._build_checkpointer()
    workflow._build_checkpointer()

    assert len(calls) == 1


def test_postgres_failure_fails_closed_when_shared_storage_is_required(monkeypatch):
    from graph.workflow import SharedCheckpointUnavailable

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", "1")
    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _fail_open)

    with pytest.raises(SharedCheckpointUnavailable, match="unreachable"):
        workflow._build_checkpointer()


def test_required_mode_stays_closed_even_on_a_later_build(monkeypatch):
    from graph.workflow import SharedCheckpointUnavailable

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", "true")
    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _fail_open)

    for _ in range(2):
        with pytest.raises(SharedCheckpointUnavailable):
            workflow._build_checkpointer()


# ----------------------------------------------------------------- success


class _FakeHandle:
    def __init__(self, saver):
        self.saver = saver
        self.closed = False

    def close(self):
        self.closed = True


def test_postgres_saver_is_used_and_reused(monkeypatch):
    sentinel = object()
    opened = []

    def _fake_open(url):
        opened.append(url)
        return _FakeHandle(sentinel)

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _fake_open)

    assert workflow._build_checkpointer() is sentinel
    assert workflow._build_checkpointer() is sentinel
    assert len(opened) == 1, "the shared connection must be opened once"
    assert opened[0] in workflow._open_checkpointers


def test_shared_url_key_is_the_url_not_the_sqlite_path(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")
    monkeypatch.setattr(
        workflow, "_open_postgres_checkpointer", lambda url: _FakeHandle(object())
    )

    workflow._build_checkpointer()

    assert "postgresql://user:pw@db/x" in workflow._open_checkpointers
    assert str(os.getenv("LANGGRAPH_CHECKPOINT_DB")) not in workflow._open_checkpointers


def test_test_env_never_opens_postgres(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db/x")

    def _boom(url):
        raise AssertionError("APP_ENV=test must not reach the database")

    monkeypatch.setattr(workflow, "_open_postgres_checkpointer", _boom)
    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(workflow._build_checkpointer(), MemorySaver)


# --------------------------------------------------------------- integration


@pytest.mark.integration
async def test_checkpoint_survives_a_postgres_reconnect():
    """Write a checkpoint to a real Postgres and read it back through a NEW
    saver — the restart/redeploy case Sprint 2 exists to fix.

    Needs ``TEST_POSTGRES_DSN`` (e.g. postgresql://postgres:pw@localhost:5432/lc).
    """
    dsn = os.getenv("TEST_POSTGRES_DSN", "").strip()
    # Only a real Postgres URL counts: "none"/"redis://..." must skip, never
    # silently pass through the SQLite path.
    if not dsn.startswith(("postgres://", "postgresql://")):
        pytest.skip("TEST_POSTGRES_DSN is not set to a postgres URL")

    import uuid

    from langgraph.checkpoint.base import Checkpoint, CheckpointMetadata

    from graph.workflow import _build_checkpointer, close_checkpointers

    thread_id = f"pg-{uuid.uuid4().hex[:12]}"
    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
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
    # PostgresSaver keys the stored values off new_versions: an empty mapping
    # stores no channel values (the SQLite saver tolerates that, this one
    # does not), so the version map must name the channel being written.
    new_versions = {"query": 1}

    import os as _os

    _os.environ["DATABASE_URL"] = dsn
    try:
        saver = _build_checkpointer()
        await saver.aput(config, checkpoint, metadata, new_versions)
        # Restart: close the handle and open a brand-new saver on the same DB.
        close_checkpointers()
        saver2 = _build_checkpointer()
        stored = await saver2.aget_tuple(config)
        assert stored is not None, "checkpoint must survive a reconnect"
        assert stored.checkpoint["channel_values"]["query"] == "checkpoint phải sống sót"
    finally:
        close_checkpointers()
        _os.environ.pop("DATABASE_URL", None)


# ----------------------------------------------------- transient-blip retry


def test_postgres_open_retries_transient_blips_then_succeeds(monkeypatch):
    """Render's Postgres restarts alongside the agent — retry, do not crash."""
    calls = []
    sleeps = []

    def _twice_then_ok(url, target):
        calls.append(url)
        if len(calls) < 3:
            raise ConnectionError("the database system is starting up")
        return _FakeHandle(object())

    monkeypatch.setattr(workflow, "_connect_postgres_once", _twice_then_ok)
    monkeypatch.setattr(workflow.time, "sleep", sleeps.append)

    handle = workflow._open_postgres_checkpointer("postgresql://u:p@db/x")

    assert isinstance(handle, _FakeHandle)
    assert len(calls) == 3
    assert sleeps == [1.0, 2.0], "linear backoff: 1s after attempt 1, 2s after 2"


def test_postgres_open_gives_up_after_max_attempts(monkeypatch):
    calls = []

    def _always_down(url, target):
        calls.append(url)
        raise ConnectionError("database is unreachable")

    monkeypatch.setattr(workflow, "_connect_postgres_once", _always_down)
    monkeypatch.setattr(workflow.time, "sleep", lambda _s: None)

    with pytest.raises(ConnectionError, match="unreachable"):
        workflow._open_postgres_checkpointer("postgresql://u:p@db/x")

    assert len(calls) == workflow._PG_OPEN_ATTEMPTS


def test_postgres_retry_does_not_run_for_a_missing_driver(monkeypatch):
    """Import errors are permanent — retrying them only slows the boot down."""
    import builtins

    real_import = builtins.__import__

    def _no_pg(name, *args, **kwargs):
        if name.startswith("langgraph.checkpoint.postgres"):
            raise ImportError("no postgres driver")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_pg)
    monkeypatch.setattr(workflow.time, "sleep", lambda _s: None)

    with pytest.raises(ImportError):
        workflow._open_postgres_checkpointer("postgresql://u:p@db/x")


# ------------------------------------------------------- status (surfaced by /ready)


def test_checkpointer_status_reports_memory_in_test_env(monkeypatch):
    # The file-level fixture runs in APP_ENV=local; tests use MemorySaver.
    monkeypatch.setenv("APP_ENV", "test")
    status = workflow.checkpointer_status()
    assert status["test_env"] == "true"
    assert status["backend"] == "memory"
    assert status["configured"] == "sqlite"


def test_checkpointer_status_reports_sqlite(monkeypatch):
    workflow._build_checkpointer()  # no DATABASE_URL in this fixture -> sqlite
    status = workflow.checkpointer_status()
    assert status["backend"] == "sqlite"
    assert status["configured"] == "sqlite"
    assert "p@" not in status["target"]


def test_checkpointer_status_reports_postgres_with_redacted_target(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://agent:s3cret@db.example/x")
    monkeypatch.setattr(
        workflow, "_open_postgres_checkpointer", lambda url: _FakeHandle(object())
    )

    workflow._build_checkpointer()
    status = workflow.checkpointer_status()

    assert status["backend"] == "postgres"
    assert status["configured"] == "postgres"
    assert status["required"] == "false"
    assert "s3cret" not in status["target"]
    assert status["target"].startswith("postgresql://***@")


def test_checkpointer_status_flags_required_mode(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_CHECKPOINT_SHARED_REQUIRED", "1")
    assert workflow.checkpointer_status()["required"] == "true"
