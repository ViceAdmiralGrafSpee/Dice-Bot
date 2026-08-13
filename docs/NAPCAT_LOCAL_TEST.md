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

这个才是 QQ 骰娘的正式启动命令。它会连接 NapCat，并把私聊或群内明确 @机器人的消息交给共享聊天核心。第一版暂不加载图片和原 Discord 工具。

DeepSeek Key 和 OneBot Token 都只能保存在本机 `.env`。如果缺少必要设置，程序会直接说明缺少哪一项，并且不会连接 QQ 或误发消息。

PostgreSQL 现在是可选增强项。没有启动数据库时，机器人会跳过旧项目的档案、长期记忆、好感度、币和用户偏好，仍然可以进行基础 AI 对话；以后接入完整数据库后，这些功能会自动恢复。

QQ 的最近对话会保存在 `data/memory.sqlite3`。每个群聊或私聊最多保存最近 500 条原始文本，其中最近 35 条可以作为 AI 的短期上下文。群里没有 @机器人的普通消息也会被记录，但不会触发 AI 回复；不同群聊之间完全隔离。该数据库位于 Git 忽略的 `data/` 目录，不会被提交到 GitHub，迁移 VPS 时需要单独备份。

## 7. 使用骰子命令

群聊和私聊都可以直接发送骰子命令，不需要 @机器人，也不会调用 LLM：

```text
.r 1d100
.r 2d6+3
.r d20-1
```

机器人会展示每颗骰子的实际结果、加减值和总点数。一次最多 100 颗骰子，防止误输入造成过长回复。

也可以在私聊中直接说，或在群里 @机器人后说：

```text
帮我骰 2d6+3，并说得有气氛一点
```

这种自然语言方式会由 LLM 判断并调用 `roll_dice` 工具，Python 实际生成随机数，然后 LLM 按人设表述。最终回复始终先显示以 `🎲` 开头的 Python 权威结果，再显示人设化文字；即使第二次 LLM 表述失败，已经生成的骰子结果也不会丢失。

QQ 入口使用独立的平台无关工具注册表，目前只注册 `roll_dice`。以后 COC、DND 等规则模块可以注册新的工具定义，不需要修改 OneBot 收发层或 Dice Engine。

## 常见问题

### 一直显示连接失败

确认 NapCat 正在运行、WebSocket 服务已启用，并且双方端口都是 `3001`。

### 显示 401 或鉴权失败

确认 NapCat 与 `.env` 中的 Token 完全相同，注意不要多出空格。

### 群消息没有回复

AI 聊天只响应明确 @机器人的群消息；骰子命令不需要 @。确认你 @的是登录 NapCat 的机器人 QQ 号，并将 Message Post Format 设置为 `array`。

### 会读取图片吗

暂时不会。第一版只把图片标记成“`[图片]`”，不会下载或交给视觉模型。
