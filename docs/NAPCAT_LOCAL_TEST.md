# NapCat / OneBot 本地联机测试

本页用于第一次验证 QQ 消息能否到达 Dice-Bot。此阶段不需要 VPS、数据库或 DeepSeek API。

## 它们分别是什么

- NapCat：登录 QQ、接收和发送 QQ 消息。
- OneBot 11：NapCat 对外提供的通信格式，不是另一个需要安装的软件。
- Dice-Bot：连接 NapCat，理解 OneBot 事件并运行机器人逻辑。

三者在第一次测试时都运行在同一台 Windows 电脑上：

```text
QQ 群 → NapCat → OneBot WebSocket → Dice-Bot
```

## 0. 账号提醒

NapCat 不是腾讯官方 QQ Bot API。建议第一次测试使用单独的机器人 QQ 号，不要使用重要的主账号。请遵守 QQ 平台规则，并自行承担协议端登录可能带来的账号限制风险。

## 1. 安装并启动 NapCat

1. 打开 [NapCatQQ 官方 Releases](https://github.com/NapNeko/NapCatQQ/releases)。
2. Windows 64 位可以下载官方文档推荐的 `NapCat.Shell.Windows.OneKey.zip`。
3. 解压到一个单独目录，不要解压进 Dice-Bot 仓库。
4. 运行 `NapCatInstaller.exe`，等待配置完成。
5. 进入生成的 `NapCat.XXXX.Shell` 目录，运行 `napcat.bat`。
6. 按控制台提示登录准备作为机器人的 QQ 号。

如果一键包名称或启动步骤发生变化，以 [NapCat Shell 官方安装文档](https://napneko.github.io/guide/boot/Shell) 为准。

## 2. 打开 NapCat WebUI

NapCat 启动日志会显示类似下面的地址：

```text
http://127.0.0.1:6099/webui?token=……
```

在浏览器打开日志中的真实地址。不要把 WebUI token 发给别人，也不要提交到 GitHub。

## 3. 开启 OneBot WebSocket 服务

在 NapCat WebUI 的网络配置中，新建一个 WebSocket 服务端：

- 启用：是
- Host：`127.0.0.1`
- Port：`3001`
- Message Post Format：`array`
- Token：生成一段只在本机使用的随机字符串
- Report Self Message：关闭（如果界面提供此选项）

保存并启用。第一次本地测试不要把 Host 设置为 `0.0.0.0`，避免同一网络中的其他设备连接这个接口。

## 4. 配置 Dice-Bot

在仓库根目录的 `.env` 中加入：

```dotenv
ONEBOT_WS_URL="ws://127.0.0.1:3001"
ONEBOT_ACCESS_TOKEN="这里填写与 NapCat 相同的 Token"
```

真实 Token 只能放在 `.env`，不能填写进 `.env.example`，也不能提交到 GitHub。

## 5. 启动固定回声测试

在 Dice-Bot 仓库目录运行：

```powershell
python -m src.chat.platform.onebot.echo_bot
```

看到“`OneBot WebSocket 已连接`”后：

1. 把机器人 QQ 号拉进一个测试群。
2. 在群里发送 `@机器人 测试`。
3. 机器人应该回复：`收到。QQ / NapCat / OneBot 通道已经连通。`
4. 也可以给机器人发私聊；私聊不需要 @。

这个回声程序不会调用 LLM，也不会修改数据库。

## 6. 启动正式 AI 聊天入口

固定回声测试通过后，再在本机 `.env` 中加入：

```dotenv
DEEPSEEK_API_KEY="这里填写你自己的 DeepSeek API Key"
QQ_AI_MODEL="deepseek:deepseek-chat"
```

然后在仓库目录运行：

```powershell
python -m src.qq_bot
```

这个才是 QQ 骰娘的正式启动命令。它会连接 NapCat，并把私聊或群内明确 @机器人的消息交给共享聊天核心。第一版暂不加载图片、骰子和原 Discord 工具。

DeepSeek Key 和 OneBot Token 都只能保存在本机 `.env`。如果缺少必要设置，程序会直接说明缺少哪一项，并且不会连接 QQ 或误发消息。

PostgreSQL 现在是可选增强项。没有启动数据库时，机器人会跳过旧项目的档案、长期记忆、好感度、币和用户偏好，仍然可以进行基础 AI 对话；以后接入完整数据库后，这些功能会自动恢复。

## 常见问题

### 一直显示连接失败

确认 NapCat 正在运行、WebSocket 服务已启用，并且双方端口都是 `3001`。

### 显示 401 或鉴权失败

确认 NapCat 与 `.env` 中的 Token 完全相同，注意不要多出空格。

### 群消息没有回复

第一版只响应明确 @机器人的群消息。确认你 @的是登录 NapCat 的机器人 QQ 号，并将 Message Post Format 设置为 `array`。

### 会读取图片吗

暂时不会。第一版只把图片标记成“`[图片]`”，不会下载或交给视觉模型。
