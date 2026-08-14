from src.database.identity import PlatformUserIdentity, platform_user_identity
from src.database.services.member_profile_service import MemberProfileService


def test_qq_identity_is_namespaced() -> None:
    identity = platform_user_identity("QQ", 123456)

    assert identity.database_key == "qq:123456"
    assert identity.external_id == "platform:qq:123456"


def test_legacy_discord_identity_remains_compatible() -> None:
    identity = platform_user_identity("discord", "123456")

    assert identity.database_key == "123456"
    assert identity.database_key != platform_user_identity("qq", "123456").database_key


def test_identity_rejects_oversized_database_key() -> None:
    try:
        PlatformUserIdentity("qq", "x" * 50)
    except ValueError as error:
        assert "exceeds 50" in str(error)
    else:
        raise AssertionError("oversized identity was accepted")


def test_minimal_profile_contains_only_platform_metadata() -> None:
    identity = platform_user_identity("qq", "123456")

    values = MemberProfileService.minimal_values(identity, "骰友")

    assert values["user_id"] == "qq:123456"
    assert values["external_id"] == "platform:qq:123456"
    assert values["title"] == "骰友"
    assert values["history"] == []
    assert values["source_metadata"] == {
        "platform": "qq",
        "platform_user_id": "123456",
        "display_name": "骰友",
        "auto_created": True,
    }
