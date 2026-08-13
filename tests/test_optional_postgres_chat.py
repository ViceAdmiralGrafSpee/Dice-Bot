from unittest.mock import AsyncMock

import pytest

import src.chat.services.chat_service as chat_service_module
from src.chat.services.chat_service import ChatService


@pytest.mark.asyncio
async def test_optional_context_skips_all_postgres_services_when_disabled(
    monkeypatch,
) -> None:
    profile_lookup = AsyncMock()
    affection_lookup = AsyncMock()
    persona_lookup = AsyncMock()
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
    service = ChatService()
    service.set_optional_postgres_enabled(False)

    result = await service._load_optional_user_context("10001", 10001)

    assert result == (None, None, "default")
    profile_lookup.assert_not_awaited()
    affection_lookup.assert_not_awaited()
    persona_lookup.assert_not_awaited()


@pytest.mark.asyncio
async def test_optional_context_falls_back_if_database_stops_responding(
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
    persona_lookup = AsyncMock()
    monkeypatch.setattr(
        chat_service_module.persona_preference_service,
        "get_persona_style",
        persona_lookup,
    )
    service = ChatService()

    result = await service._load_optional_user_context("10001", 10001)

    assert result == (None, None, "default")
    persona_lookup.assert_not_awaited()
