import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

search_module = importlib.import_module(
    "src.chat.features.personal_memory.services.conversation_memory_search_service"
)
memory_module = importlib.import_module(
    "src.chat.features.personal_memory.services.personal_memory_service"
)


class _AsyncSessionContext:
    def __init__(self, *, result=None):
        self.result = result
        self.execute = AsyncMock(return_value=result)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


@pytest.mark.asyncio
async def test_failed_block_write_keeps_pending_history(monkeypatch) -> None:
    history = [
        {"role": "user", "parts": [f"message-{index}"]}
        for index in range(10)
    ]
    profile = SimpleNamespace(history=history)
    scalar_result = SimpleNamespace(first=lambda: profile)
    read_result = SimpleNamespace(scalars=lambda: scalar_result)
    read_session = _AsyncSessionContext(result=read_result)
    block_session = _AsyncSessionContext()
    sessions = iter((read_session, block_session))
    monkeypatch.setattr(memory_module, "AsyncSessionLocal", lambda: next(sessions))

    create_block = AsyncMock(return_value=None)
    cleanup = AsyncMock()
    monkeypatch.setattr(
        memory_module.conversation_block_service,
        "create_block_from_history",
        create_block,
    )
    monkeypatch.setattr(
        memory_module.conversation_block_service,
        "cleanup_old_blocks",
        cleanup,
    )

    created = await memory_module.PersonalMemoryService().check_and_create_block_before_reply(
        "qq:10001"
    )

    assert created is False
    assert profile.history == history
    block_session.rollback.assert_awaited_once_with()
    block_session.commit.assert_not_awaited()
    cleanup.assert_not_awaited()


class _EmptyRows:
    def fetchall(self):
        return []


@pytest.mark.asyncio
async def test_empty_fts_query_uses_vector_only_sql(monkeypatch) -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyRows()))
    monkeypatch.setattr(
        search_module,
        "get_embedding_column",
        AsyncMock(return_value="qwen_embedding"),
    )

    results = await search_module.ConversationMemorySearchService()._hybrid_search_blocks(
        session,
        "qq:10001",
        "",
        [0.1, 0.2],
    )

    statement = str(session.execute.await_args.args[0])
    parameters = session.execute.await_args.args[1]
    assert results == []
    assert "@@@" not in statement
    assert "query_text" not in parameters
    assert "top_k_fts" not in parameters


@pytest.mark.asyncio
async def test_nonempty_fts_query_keeps_hybrid_search_sql(monkeypatch) -> None:
    session = SimpleNamespace(execute=AsyncMock(return_value=_EmptyRows()))
    monkeypatch.setattr(
        search_module,
        "get_embedding_column",
        AsyncMock(return_value="qwen_embedding"),
    )

    await search_module.ConversationMemorySearchService()._hybrid_search_blocks(
        session,
        "qq:10001",
        "海盐七号",
        [0.1, 0.2],
    )

    statement = str(session.execute.await_args.args[0])
    parameters = session.execute.await_args.args[1]
    assert "conversation_text @@@ :query_text" in statement
    assert parameters["query_text"] == "海盐七号"
    assert parameters["top_k_fts"] == 10
