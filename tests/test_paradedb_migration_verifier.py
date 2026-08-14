from pathlib import Path
import runpy

import pytest


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "paradedb"
    / "verify_fresh_migrations.py"
)


@pytest.fixture(scope="module")
def verifier():
    return runpy.run_path(str(MODULE_PATH), run_name="paradedb_migration_verifier")


def test_build_test_database_name_is_safe_and_bounded(verifier) -> None:
    name = verifier["build_test_database_name"]("dice-bot/production", "deadbeef")

    assert name == "dice_bot_production_migration_test_deadbeef"
    assert len(name) <= 63


def test_build_test_database_name_truncates_long_names(verifier) -> None:
    name = verifier["build_test_database_name"]("x" * 100, "12345678")

    assert len(name) == 63
    assert name.endswith("_migration_test_12345678")


def test_private_settings_rejects_non_loopback_database(verifier, tmp_path) -> None:
    env_file = tmp_path / "private.env"
    env_file.write_text(
        "POSTGRES_DB=dice_bot\n"
        "POSTGRES_USER=dice_bot\n"
        "POSTGRES_PASSWORD=secret\n"
        "DB_HOST=0.0.0.0\n",
        encoding="utf-8",
    )

    with pytest.raises(verifier["VerificationError"], match="must be loopback"):
        verifier["_private_settings"](env_file)


def test_create_database_enables_autocommit_before_execute(
    verifier, monkeypatch
) -> None:
    events: list[str] = []

    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, _statement, _parameters=None):
            assert connection.autocommit is True
            events.append("execute")

    class FakeConnection:
        autocommit = False

        def cursor(self):
            return FakeCursor()

        def close(self):
            events.append("close")

    connection = FakeConnection()
    monkeypatch.setitem(
        verifier["_create_database"].__globals__,
        "_connect",
        lambda _settings, _database: connection,
    )

    verifier["_create_database"]({}, "dice_bot_migration_test_deadbeef")

    assert events == ["execute", "close"]
