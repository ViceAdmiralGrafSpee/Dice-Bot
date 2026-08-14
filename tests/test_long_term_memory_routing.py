from unittest.mock import AsyncMock

import pytest

import src.chat.services.chat_service as chat_service_module
from src.chat.services.chat_service import ChatService
from src.database.database import PostgresCapabilities


@pytest.mark.asyncio
async def test_memory_route_creates_block_before_retrieval(monkeypatch) -> None:
    calls: list[str] = []

    async def create_block(**_kwargs):
        calls.append("create")
        return True

    async def search(**_kwargs):
        calls.append("search")
        return [{"conversation_text": "用户喜欢侦探故事"}]

    monkeypatch.setattr(
        chat_service_module.personal_memory_service,
        "check_and_create_block_before_reply",
        create_block,
    )
    monkeypatch.setattr(
        chat_service_module.conversation_memory_search_service,
        "search",
        search,
    )
    monkeypatch.setattr(
        chat_service_module.conversation_memory_search_service,
        "format_blocks_for_context",
        lambda blocks: blocks[0]["conversation_text"],
    )
    service = ChatService()
    service.set_postgres_capabilities(
        PostgresCapabilities(profiles=True, conversation_memory=True)
    )

    result = await service._prepare_long_term_memory(
        memory_user_id="qq:10001",
        query="推荐一个故事",
        profile_available=True,
    )

    assert calls == ["create", "search"]
    assert result == "用户喜欢侦探故事"


@pytest.mark.asyncio
async def test_memory_route_is_independent_from_coins_and_affection(
    monkeypatch,
) -> None:
    search = AsyncMock(return_value=[])
    monkeypatch.setattr(
        chat_service_module.personal_memory_service,
        "check_and_create_block_before_reply",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        chat_service_module.conversation_memory_search_service,
        "search",
        search,
    )
    service = ChatService()
    service.set_postgres_capabilities(
        PostgresCapabilities(profiles=True, conversation_memory=True)
    )

    result = await service._prepare_long_term_memory(
        memory_user_id="qq:10001",
        query="还记得吗",
        profile_available=True,
    )

    assert result is None
    search.assert_awaited_once_with(user_id="qq:10001", query="还记得吗")


@pytest.mark.asyncio
async def test_memory_route_fails_open_when_embedding_provider_is_down(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_service_module.personal_memory_service,
        "check_and_create_block_before_reply",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        chat_service_module.conversation_memory_search_service,
        "search",
        AsyncMock(side_effect=ConnectionError("embedding unavailable")),
    )
    service = ChatService()
    service.set_postgres_capabilities(
        PostgresCapabilities(profiles=True, conversation_memory=True)
    )

    result = await service._prepare_long_term_memory(
        memory_user_id="qq:10001",
        query="继续聊天",
        profile_available=True,
    )

    assert result is None
