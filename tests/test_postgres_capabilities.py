from src.database.database import (
    PostgresCapabilities,
    capabilities_from_table_names,
    parse_postgres_capability_allowlist,
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


def test_absent_allowlist_preserves_legacy_capabilities() -> None:
    assert parse_postgres_capability_allowlist(None) == {
        "profiles",
        "conversation_memory",
        "coins",
        "affection",
        "memory_notes",
        "persona",
    }


def test_allowlist_limits_capabilities_even_when_all_tables_exist() -> None:
    all_tables = {
        "community.member_profiles",
        "conversation.conversation_blocks",
        "economy.user_coins",
        "user.user_affection",
        "user.user_memory_notes",
        "user.user_persona_preference",
    }
    allowed = parse_postgres_capability_allowlist(
        "profiles, conversation_memory"
    )

    capabilities = capabilities_from_table_names(all_tables, allowed)

    assert capabilities.long_term_memory is True
    assert capabilities.coins is False
    assert capabilities.affection is False
    assert capabilities.memory_notes is False
    assert capabilities.persona is False


def test_unknown_or_explicit_none_capabilities_fail_closed() -> None:
    assert parse_postgres_capability_allowlist("unknown") == set()
    assert parse_postgres_capability_allowlist("none") == set()
