"""Independent NapCat login watchdog with ServerChan notifications.

Run continuously with::

    python -m src.napcat_watchdog

Send one configuration test notification with::

    python -m src.napcat_watchdog --test-notification
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

import aiohttp
from dotenv import load_dotenv

from src.chat.platform.onebot.transport import OneBotWebSocketClient


log = logging.getLogger(__name__)
DEFAULT_STATE_PATH = Path("data/napcat-watchdog.json")


class WatchdogConfigurationError(RuntimeError):
    """Raised when the watchdog cannot start safely."""


class NotificationError(RuntimeError):
    """Raised when ServerChan does not accept a notification."""


@dataclass(frozen=True, slots=True)
class WatchdogSettings:
    ws_url: str
    access_token: str
    serverchan_sendkey: str
    interval_seconds: float = 60.0
    failure_threshold: int = 3
    timeout_seconds: float = 10.0
    state_path: Path = DEFAULT_STATE_PATH


@dataclass(frozen=True, slots=True)
class HealthCheck:
    healthy: bool
    reason: str


@dataclass(frozen=True, slots=True)
class WatchdogAlert:
    title: str
    description: str


@dataclass(slots=True)
class WatchdogState:
    status: str = "unknown"
    consecutive_failures: int = 0
    last_reason: str = "尚未检查"
    changed_at: str = ""


class OneBotStatusClient(Protocol):
    async def __aenter__(self) -> "OneBotStatusClient": ...

    async def __aexit__(self, *_args: Any) -> None: ...

    async def call_action(
        self,
        action: str,
        params: Mapping[str, Any],
        *,
        timeout_seconds: float = 30.0,
    ) -> Mapping[str, Any]: ...


OneBotClientFactory = Callable[[str, str], OneBotStatusClient]


def load_watchdog_settings(
    environ: Mapping[str, str] | None = None,
) -> WatchdogSettings:
    """Load watchdog settings without logging any secret value."""

    values = os.environ if environ is None else environ
    ws_url = values.get("ONEBOT_WS_URL", "").strip()
    access_token = values.get("ONEBOT_ACCESS_TOKEN", "").strip()
    sendkey = values.get("SERVERCHAN_SENDKEY", "").strip()

    missing = [
        name
        for name, value in (
            ("ONEBOT_WS_URL", ws_url),
            ("ONEBOT_ACCESS_TOKEN", access_token),
            ("SERVERCHAN_SENDKEY", sendkey),
        )
        if not value
    ]
    if missing:
        raise WatchdogConfigurationError(
            "缺少监控配置：" + "、".join(missing) + "。请填写 VPS 的 .env。"
        )

    parsed_url = urlparse(ws_url)
    if parsed_url.scheme not in {"ws", "wss"} or not parsed_url.hostname:
        raise WatchdogConfigurationError(
            "ONEBOT_WS_URL 不是有效的 WebSocket 地址。"
        )
    if not sendkey.startswith("SCT"):
        raise WatchdogConfigurationError(
            "SERVERCHAN_SENDKEY 看起来不是 Server酱 Turbo 的 SCT SendKey。"
        )

    interval_seconds = _parse_float_setting(
        values,
        "NAPCAT_WATCHDOG_INTERVAL_SECONDS",
        default=60.0,
        minimum=10.0,
    )
    timeout_seconds = _parse_float_setting(
        values,
        "NAPCAT_WATCHDOG_TIMEOUT_SECONDS",
        default=10.0,
        minimum=1.0,
    )
    failure_threshold = _parse_int_setting(
        values,
        "NAPCAT_WATCHDOG_FAILURE_THRESHOLD",
        default=3,
        minimum=1,
        maximum=20,
    )
    state_path_text = values.get(
        "NAPCAT_WATCHDOG_STATE_PATH", str(DEFAULT_STATE_PATH)
    ).strip()
    if not state_path_text:
        raise WatchdogConfigurationError(
            "NAPCAT_WATCHDOG_STATE_PATH 不能为空。"
        )

    return WatchdogSettings(
        ws_url=ws_url,
        access_token=access_token,
        serverchan_sendkey=sendkey,
        interval_seconds=interval_seconds,
        failure_threshold=failure_threshold,
        timeout_seconds=timeout_seconds,
        state_path=Path(state_path_text),
    )


def _parse_float_setting(
    values: Mapping[str, str],
    name: str,
    *,
    default: float,
    minimum: float,
) -> float:
    text = values.get(name, str(default)).strip()
    try:
        value = float(text)
    except ValueError as error:
        raise WatchdogConfigurationError(f"{name} 必须是数字。") from error
    if value < minimum:
        raise WatchdogConfigurationError(f"{name} 不能小于 {minimum:g}。")
    return value


def _parse_int_setting(
    values: Mapping[str, str],
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    text = values.get(name, str(default)).strip()
    try:
        value = int(text)
    except ValueError as error:
        raise WatchdogConfigurationError(f"{name} 必须是整数。") from error
    if not minimum <= value <= maximum:
        raise WatchdogConfigurationError(
            f"{name} 必须在 {minimum} 到 {maximum} 之间。"
        )
    return value


class NapCatStatusProbe:
    """Query NapCat on a short-lived WebSocket separate from the chat bot."""

    def __init__(
        self,
        settings: WatchdogSettings,
        *,
        client_factory: OneBotClientFactory = OneBotWebSocketClient,
    ) -> None:
        self._settings = settings
        self._client_factory = client_factory

    async def check(self) -> HealthCheck:
        try:
            client = self._client_factory(
                self._settings.ws_url,
                self._settings.access_token,
            )
            async with client:
                data = await client.call_action(
                    "get_status",
                    {},
                    timeout_seconds=self._settings.timeout_seconds,
                )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            return HealthCheck(
                healthy=False,
                reason=f"无法查询 NapCat（{type(error).__name__}）",
            )

        online = data.get("online") is True
        good = data.get("good") is True
        if online and good:
            return HealthCheck(healthy=True, reason="NapCat 与 QQ 登录均正常")
        if not online:
            return HealthCheck(healthy=False, reason="NapCat 报告 QQ 账号已离线")
        return HealthCheck(healthy=False, reason="NapCat 报告运行状态异常")


class WatchdogStateStore:
    """Persist only non-secret alert state so restarts do not duplicate alerts."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> WatchdogState:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return WatchdogState()
        if not isinstance(payload, dict):
            return WatchdogState()
        status = payload.get("status")
        if status not in {"unknown", "healthy", "unhealthy"}:
            return WatchdogState()
        try:
            failures = max(0, int(payload.get("consecutive_failures", 0)))
        except (TypeError, ValueError):
            failures = 0
        return WatchdogState(
            status=status,
            consecutive_failures=failures,
            last_reason=str(payload.get("last_reason", "尚未检查")),
            changed_at=str(payload.get("changed_at", "")),
        )

    def save(self, state: WatchdogState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps(asdict(state), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.replace(self.path)


class WatchdogController:
    """Turn health checks into at-most-once outage and recovery alerts."""

    def __init__(
        self,
        store: WatchdogStateStore,
        *,
        failure_threshold: int,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._failure_threshold = failure_threshold
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._state = store.load()

    @property
    def state(self) -> WatchdogState:
        return self._state

    def record(self, check: HealthCheck) -> WatchdogAlert | None:
        timestamp = self._now().astimezone().isoformat(timespec="seconds")

        if check.healthy:
            was_unhealthy = self._state.status == "unhealthy"
            self._state = WatchdogState(
                status="healthy",
                consecutive_failures=0,
                last_reason=check.reason,
                changed_at=timestamp,
            )
            self._store.save(self._state)
            if was_unhealthy:
                return WatchdogAlert(
                    title="Dice-Bot：QQ 已恢复在线",
                    description=(
                        f"检测时间：{timestamp}\n\n"
                        f"当前状态：{check.reason}\n\n"
                        "Dice-Bot 应会自动重新连接；如仍不回复，请检查 dice-bot.service。"
                    ),
                )
            return None

        failures = self._state.consecutive_failures + 1
        already_unhealthy = self._state.status == "unhealthy"
        confirmed = failures >= self._failure_threshold
        self._state = WatchdogState(
            status="unhealthy" if confirmed else self._state.status,
            consecutive_failures=failures,
            last_reason=check.reason,
            changed_at=timestamp,
        )
        self._store.save(self._state)

        if confirmed and not already_unhealthy:
            return WatchdogAlert(
                title="Dice-Bot：QQ 可能已经离线",
                description=(
                    f"检测时间：{timestamp}\n\n"
                    f"连续失败：{failures} 次\n\n"
                    f"原因：{check.reason}\n\n"
                    "监控器不会自动登录或重启 NapCat，请登录 VPS 检查 NapCat。"
                ),
            )
        return None


class ServerChanNotifier:
    """Send alerts through ServerChan without exposing the SendKey in logs."""

    def __init__(self, sendkey: str, *, timeout_seconds: float = 15.0) -> None:
        self._sendkey = sendkey
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def send(self, alert: WatchdogAlert) -> None:
        url = f"https://sctapi.ftqq.com/{self._sendkey}.send"
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.post(
                    url,
                    data={"title": alert.title, "desp": alert.description},
                ) as response:
                    status = response.status
                    try:
                        payload = await response.json(content_type=None)
                    except (aiohttp.ContentTypeError, json.JSONDecodeError):
                        payload = {}
        except asyncio.CancelledError:
            raise
        except Exception as error:
            raise NotificationError(
                f"Server酱请求失败（{type(error).__name__}）"
            ) from None

        code = payload.get("code") if isinstance(payload, Mapping) else None
        if status != 200 or str(code) != "0":
            raise NotificationError(
                f"Server酱未接受通知（HTTP {status}，code={code}）"
            )


async def run_watchdog(settings: WatchdogSettings) -> None:
    """Run health checks forever; notification failures never stop monitoring."""

    probe = NapCatStatusProbe(settings)
    controller = WatchdogController(
        WatchdogStateStore(settings.state_path),
        failure_threshold=settings.failure_threshold,
    )
    notifier = ServerChanNotifier(settings.serverchan_sendkey)

    log.info(
        "NapCat 监控器已启动：每 %.0f 秒检查一次，连续 %d 次失败后通知。",
        settings.interval_seconds,
        settings.failure_threshold,
    )
    while True:
        check = await probe.check()
        alert = controller.record(check)
        if alert is not None:
            try:
                await notifier.send(alert)
                log.info("已发送状态变化通知：%s", alert.title)
            except NotificationError as error:
                # The state transition is already persisted. This deliberately
                # chooses at-most-once delivery so a broken notification channel
                # cannot consume the free daily quota in a retry loop.
                log.error("%s；为避免重复扣额度，本次状态变化不会自动重发。", error)
        else:
            log.info("NapCat 状态检查：%s", check.reason)
        await asyncio.sleep(settings.interval_seconds)


async def send_test_notification(settings: WatchdogSettings) -> None:
    notifier = ServerChanNotifier(settings.serverchan_sendkey)
    await notifier.send(
        WatchdogAlert(
            title="Dice-Bot：监控通知测试成功",
            description=(
                "Server酱 SendKey 已正确配置。\n\n"
                "这是一条人工测试消息，不代表 QQ 当前离线。"
            ),
        )
    )


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="监控 NapCat 的 QQ 登录状态")
    parser.add_argument(
        "--test-notification",
        action="store_true",
        help="发送一条 Server酱测试通知后退出",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = _build_argument_parser().parse_args(argv)
    try:
        settings = load_watchdog_settings()
        if args.test_notification:
            asyncio.run(send_test_notification(settings))
            log.info("Server酱测试通知已发送。")
        else:
            asyncio.run(run_watchdog(settings))
    except WatchdogConfigurationError as error:
        log.error("NapCat 监控器未启动：%s", error)
        return 2
    except NotificationError as error:
        log.error("测试通知发送失败：%s", error)
        return 3
    except KeyboardInterrupt:
        log.info("NapCat 监控器已停止。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
