from unittest.mock import AsyncMock

import pytest

import src.chat.services.chat_service as chat_service_module
from src.chat.services.chat_service import ChatService
from src.database.database import PostgresCapabilities


@pytest.mark.asyncio
async def test_optional_context_skips_all_postgres_services_when_disabled(
    monkeypatch,
) -> None:
    profile_lookup = AsyncMock()
    affection_lookup = AsyncMock()
    persona_lookup = AsyncMock()
    ensure_profile = AsyncMock()
    monkeypatch.setattr(
        chat_service_module.world_book_service,
        "get_profile_by_user_id",
        profile_lookup,
    )
    monkeypatch.setattr(
        chat_service_module.affection_service,
        "get_affection_status",
        affection_lookup,
    )
    monkeypatch.setattr(
        chat_service_module.persona_preference_service,
        "get_persona_style",
        persona_lookup,
    )
    monkeypatch.setattr(
        chat_service_module.member_profile_service,
        "ensure_minimal_profile",
        ensure_profile,
    )
    service = ChatService()
    service.set_optional_postgres_enabled(False)

    result = await service._load_optional_user_context(
        "qq", "10001", "骰友", 10001
    )

    assert result == (None, None, "default")
    profile_lookup.assert_not_awaited()
    affection_lookup.assert_not_awaited()
    persona_lookup.assert_not_awaited()
    ensure_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_optional_context_keeps_independent_capabilities_when_affection_fails(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_service_module.world_book_service,
        "get_profile_by_user_id",
        AsyncMock(return_value={"user_id": "10001"}),
    )
    monkeypatch.setattr(
        chat_service_module.affection_service,
        "get_affection_status",
        AsyncMock(side_effect=ConnectionError("database offline")),
    )
    persona_lookup = AsyncMock(return_value="gentle")
    monkeypatch.setattr(
        chat_service_module.member_profile_service,
        "ensure_minimal_profile",
        AsyncMock(),
    )
    monkeypatch.setattr(
        chat_service_module.persona_preference_service,
        "get_persona_style",
        persona_lookup,
    )
    service = ChatService()

    result = await service._load_optional_user_context(
        "qq", "10001", "骰友", 10001
    )

    assert result == ({"user_id": "10001"}, None, "gentle")
    persona_lookup.assert_awaited_once_with("qq:10001")


@pytest.mark.asyncio
async def test_optional_context_bootstraps_qq_profile_with_namespaced_id(
    monkeypatch,
) -> None:
    ensure_profile = AsyncMock()
    profile_lookup = AsyncMock(return_value={"user_id": "qq:10001"})
    monkeypatch.setattr(
        chat_service_module.member_profile_service,
        "ensure_minimal_profile",
        ensure_profile,
    )
    monkeypatch.setattr(
        chat_service_module.world_book_service,
        "get_profile_by_user_id",
        profile_lookup,
    )
    monkeypatch.setattr(
        chat_service_module.affection_service,
        "get_affection_status",
        AsyncMock(return_value={"level": 0}),
    )
    monkeypatch.setattr(
        chat_service_module.persona_preference_service,
        "get_persona_style",
        AsyncMock(return_value="default"),
    )
    service = ChatService()

    result = await service._load_optional_user_context(
        "qq", "10001", "骰友", 10001
    )

    identity = ensure_profile.await_args.args[0]
    assert identity.database_key == "qq:10001"
    assert ensure_profile.await_args.args[1] == "骰友"
    profile_lookup.assert_awaited_once_with("qq:10001")
    assert result == ({"user_id": "qq:10001"}, {"level": 0}, "default")


@pytest.mark.asyncio
async def test_memory_capability_does_not_call_coins_affection_or_persona(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        chat_service_module.member_profile_service,
        "ensure_minimal_profile",
        AsyncMock(),
    )
    monkeypatch.setattr(
        chat_service_module.world_book_service,
        "get_profile_by_user_id",
        AsyncMock(return_value={"user_id": "qq:10001"}),
    )
    affection_lookup = AsyncMock()
    persona_lookup = AsyncMock()
    monkeypatch.setattr(
        chat_service_module.affection_service,
        "get_affection_status",
        affection_lookup,
    )
    monkeypatch.setattr(
        chat_service_module.persona_preference_service,
        "get_persona_style",
        persona_lookup,
    )
    service = ChatService()
    service.set_postgres_capabilities(
        PostgresCapabilities(profiles=True, conversation_memory=True)
    )

    result = await service._load_optional_user_context(
        "qq", "10001", "骰友", 10001
    )

    assert result == ({"user_id": "qq:10001"}, None, "default")
    affection_lookup.assert_not_awaited()
    persona_lookup.assert_not_awaited()
