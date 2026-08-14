from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.napcat_watchdog import (
    HealthCheck,
    NapCatStatusProbe,
    ServerChanNotifier,
    WatchdogAlert,
    WatchdogConfigurationError,
    WatchdogController,
    WatchdogSettings,
    WatchdogStateStore,
    load_watchdog_settings,
)


def _valid_env() -> dict[str, str]:
    return {
        "ONEBOT_WS_URL": "ws://127.0.0.1:3001",
        "ONEBOT_ACCESS_TOKEN": "onebot-test-token",
        "SERVERCHAN_SENDKEY": "SCT-test-sendkey",
    }


def _settings(tmp_path: Path) -> WatchdogSettings:
    return WatchdogSettings(
        ws_url="ws://127.0.0.1:3001",
        access_token="onebot-test-token",
        serverchan_sendkey="SCT-test-sendkey",
        state_path=tmp_path / "watchdog.json",
    )


def test_load_settings_uses_conservative_defaults() -> None:
    settings = load_watchdog_settings(_valid_env())

    assert settings.interval_seconds == 60
    assert settings.failure_threshold == 3
    assert settings.timeout_seconds == 10
    assert settings.state_path == Path("data/napcat-watchdog.json")


@pytest.mark.parametrize(
    "missing_name",
    ["ONEBOT_WS_URL", "ONEBOT_ACCESS_TOKEN", "SERVERCHAN_SENDKEY"],
)
def test_load_settings_explains_missing_secrets(missing_name: str) -> None:
    environ = _valid_env()
    environ.pop(missing_name)

    with pytest.raises(WatchdogConfigurationError, match=missing_name):
        load_watchdog_settings(environ)


def test_load_settings_rejects_too_frequent_checks() -> None:
    environ = _valid_env()
    environ["NAPCAT_WATCHDOG_INTERVAL_SECONDS"] = "1"

    with pytest.raises(
        WatchdogConfigurationError,
        match="NAPCAT_WATCHDOG_INTERVAL_SECONDS",
    ):
        load_watchdog_settings(environ)


@pytest.mark.asyncio
async def test_probe_calls_get_status_on_a_separate_client(tmp_path: Path) -> None:
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.call_action.return_value = {"online": True, "good": True}

    # A factory is synchronous even though the client methods are async.
    factory = lambda *_args: fake_client
    probe = NapCatStatusProbe(_settings(tmp_path), client_factory=factory)

    result = await probe.check()

    assert result.healthy is True
    fake_client.call_action.assert_awaited_once_with(
        "get_status", {}, timeout_seconds=10
    )


@pytest.mark.asyncio
async def test_probe_reports_explicit_offline_status(tmp_path: Path) -> None:
    fake_client = AsyncMock()
    fake_client.__aenter__.return_value = fake_client
    fake_client.call_action.return_value = {"online": False, "good": True}
    probe = NapCatStatusProbe(
        _settings(tmp_path),
        client_factory=lambda *_args: fake_client,
    )

    result = await probe.check()

    assert result.healthy is False
    assert "离线" in result.reason


@pytest.mark.asyncio
async def test_serverchan_notifier_posts_expected_fields(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def json(self, *, content_type=None):
            return {"code": 0, "message": "success"}

    class FakeSession:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def post(self, url, *, data):
            captured["url"] = url
            captured["data"] = data
            return FakeResponse()

    monkeypatch.setattr(
        "src.napcat_watchdog.aiohttp.ClientSession",
        FakeSession,
    )
    notifier = ServerChanNotifier("SCT-test-sendkey")

    await notifier.send(WatchdogAlert("测试标题", "测试正文"))

    assert captured["url"] == (
        "https://sctapi.ftqq.com/SCT-test-sendkey.send"
    )
    assert captured["data"] == {"title": "测试标题", "desp": "测试正文"}


def test_controller_alerts_once_after_three_failures_and_once_on_recovery(
    tmp_path: Path,
) -> None:
    store = WatchdogStateStore(tmp_path / "watchdog.json")
    controller = WatchdogController(
        store,
        failure_threshold=3,
        now=lambda: datetime(2026, 8, 14, 6, 0, tzinfo=timezone.utc),
    )
    failed = HealthCheck(False, "NapCat 报告 QQ 账号已离线")

    assert controller.record(failed) is None
    assert controller.record(failed) is None
    outage_alert = controller.record(failed)
    assert outage_alert is not None
    assert "离线" in outage_alert.title
    assert controller.record(failed) is None

    recovery_alert = controller.record(HealthCheck(True, "恢复正常"))
    assert recovery_alert is not None
    assert "恢复" in recovery_alert.title
    assert controller.record(HealthCheck(True, "仍然正常")) is None


def test_persisted_unhealthy_state_prevents_duplicate_after_restart(
    tmp_path: Path,
) -> None:
    store = WatchdogStateStore(tmp_path / "watchdog.json")
    first = WatchdogController(store, failure_threshold=1)
    failed = HealthCheck(False, "连接失败")

    assert first.record(failed) is not None

    restarted = WatchdogController(store, failure_threshold=1)
    assert restarted.record(failed) is None
    assert restarted.state.status == "unhealthy"
