from src.database.database import (
    PostgresCapabilities,
    capabilities_from_table_names,
)


def test_long_term_memory_does_not_require_community_features() -> None:
    capabilities = capabilities_from_table_names(
        {
            "community.member_profiles",
            "conversation.conversation_blocks",
        }
    )

    assert capabilities.long_term_memory is True
    assert capabilities.coins is False
    assert capabilities.affection is False
    assert capabilities.all_legacy_features is False


def test_full_capabilities_preserve_legacy_behavior() -> None:
    capabilities = PostgresCapabilities.full()

    assert capabilities.any_enabled is True
    assert capabilities.long_term_memory is True
    assert capabilities.all_legacy_features is True
