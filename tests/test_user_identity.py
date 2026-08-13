from __future__ import annotations

from typing import Any

import pytest

from src.chat.features.world_book.services import world_book_service as service_module
from src.database.models import CommunityMemberProfile, ConversationBlock


def test_identity_models_use_platform_neutral_user_id() -> None:
    profile_columns = CommunityMemberProfile.__table__.columns
    conversation_columns = ConversationBlock.__table__.columns

    assert "user_id" in profile_columns
    assert "discord_id" not in profile_columns
    assert "user_id" in conversation_columns
    assert "discord_id" not in conversation_columns


class _FakeCursor:
    def __init__(self) -> None:
        self.query = ""
        self.params: tuple[str] | None = None

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, query: str, params: tuple[str]) -> None:
        self.query = query
        self.params = params

    def fetchone(self) -> dict[str, str]:
        return {"user_id": "123456789", "title": "QQ User"}


class _FakeConnection:
    def __init__(self) -> None:
        self.last_cursor: _FakeCursor | None = None

    def cursor(self, **_kwargs: Any) -> _FakeCursor:
        self.last_cursor = _FakeCursor()
        return self.last_cursor


@pytest.mark.asyncio
async def test_profile_lookup_accepts_qq_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _FakeConnection()
    monkeypatch.setattr(
        service_module.incremental_rag_service,
        "_get_parade_connection",
        lambda: connection,
    )

    profile = await service_module.world_book_service.get_profile_by_user_id(
        "123456789"
    )

    assert profile == {"user_id": "123456789", "title": "QQ User"}
    assert connection.last_cursor is not None
    assert "WHERE user_id = %s" in connection.last_cursor.query
    assert connection.last_cursor.params == ("123456789",)
