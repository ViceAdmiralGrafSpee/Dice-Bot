# NapCat QQ 离线通知

这项监控独立于 `dice-bot.service` 运行。即使聊天机器人停止，它仍会通过一条单独的短连接查询 NapCat 的 `get_status`，因此不会和聊天连接争抢 QQ 消息。

默认行为：

- 每 60 秒检查一次；
- 连续 3 次异常后，通过 Server酱发送一次离线通知；
- QQ 恢复后发送一次恢复通知；
- 同一次异常不会重复通知；
- 只报警，不自动重启、不自动扫码或登录 QQ；
- 去重状态保存在 `data/napcat-watchdog.json`，不会提交到 Git。

NapCat 官方文档将 `get_status` 定义为“获取在线状态”，正常响应中的 `online` 和 `good` 均为 `true`。监控器只有在两者都为 `true` 时才认为状态健康。

## 1. 配置

在 VPS 的 `/home/ubuntu/apps/Dice-Bot/.env` 中保留以下配置：

```dotenv
SERVERCHAN_SENDKEY="你的 SCT 开头 SendKey"
NAPCAT_WATCHDOG_INTERVAL_SECONDS=60
NAPCAT_WATCHDOG_FAILURE_THRESHOLD=3
NAPCAT_WATCHDOG_TIMEOUT_SECONDS=10
NAPCAT_WATCHDOG_STATE_PATH="data/napcat-watchdog.json"
```

SendKey 是秘密。不要发到聊天、终端截图或日志中，也不要写进任何受 Git 跟踪的文件；`.env.example` 只能保留占位符。

## 2. 先发送一条人工测试通知

以下命令从 `.env` 读取 SendKey，不会在命令行中显示它：

```bash
cd /home/ubuntu/apps/Dice-Bot
./.venv/bin/python -m src.napcat_watchdog --test-notification
```

这会使用 Server酱的一次消息额度。微信收到“监控通知测试成功”后再安装长期服务。

## 3. 安装独立 systemd 服务

```bash
sudo cp /home/ubuntu/apps/Dice-Bot/deploy/systemd/napcat-watchdog.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now napcat-watchdog
```

检查服务：

```bash
systemctl status napcat-watchdog --no-pager
journalctl -u napcat-watchdog -n 50 --no-pager -l
```

正常时日志约每分钟出现一次状态检查。日志不会输出 SendKey 或 OneBot Token。

## 4. 停止或卸载

仅停止监控，不影响 Dice-Bot 和 NapCat：

```bash
sudo systemctl disable --now napcat-watchdog
```

如需重新安装，可再执行第 3 节命令。删除 `data/napcat-watchdog.json` 会清除通知去重状态；不要在故障期间随意删除，否则可能重复发送离线通知。

## 5. 能检测与不能检测的情况

可以检测：

- QQ 登录票据失效，NapCat 报告 `online=false`；
- NapCat 容器停止或 3001 端口无法连接；
- OneBot 状态接口超时或返回异常状态。

不能代替：

- 自动重新登录 QQ；
- 判断腾讯为什么让账号下线；
- 检查 DeepSeek 是否可用；
- 检查每一条聊天消息是否成功回复。

因此收到离线通知后，仍应登录 VPS 查看 NapCat 容器日志与 QQ 登录状态。
