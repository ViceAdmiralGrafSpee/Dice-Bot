# Dice-Bot 维护与开发约定

本仓库是基于 [Echoer009/Odysseia-Guidance](https://github.com/Echoer009/Odysseia-Guidance) 的衍生项目，继续遵循 AGPL-3.0。保留原项目的版权和许可证信息；新增代码和文档不得删除或弱化这些信息。

当前项目采用 QQ 优先路线：渐进地把 Discord 平台层与聊天核心解耦，并通过 OneBot 11 / NapCat 接入 QQ。现有 Discord 代码暂时保留，QQ 正式入口不会启动 Discord 社区功能。不要一次性重写整个项目，也不要为了删除 Discord 而破坏已经可用的 QQ 链路。

## 不可破坏的原则

- `main` 只保存可追溯的稳定状态，不直接在 `main` 上开发。
- 一次只做一个小目标，一个 commit 只表达一个容易解释的变化。
- 修改前先说明范围；修改后列出文件、原因、行为影响和测试方法。
- LLM 只负责理解、表达、角色扮演、规则解释、总结和建议。
- 骰子随机数、数值计算、规则状态机和数据库修改必须由 Python 程序执行。
- 不提交 `.env`、API Key、Discord/QQ Token、数据库密码或任何真实凭据。
- `.env.example` 只能包含占位符和安全默认值。
- 不为了代码风格或“更优雅”顺手重构与当前目标无关的模块。

## 仓库与远程地址

建议保持以下结构：

```text
origin    https://github.com/ViceAdmiralGrafSpee/Dice-Bot.git
upstream  https://github.com/Echoer009/Odysseia-Guidance.git
```

`origin` 是自己的仓库，可以推送；`upstream` 只用于获取原项目更新。为了避免误推上游，可执行：

```powershell
git remote set-url --push upstream DISABLED
```

用以下命令随时核对：

```powershell
git remote -v
git branch --show-current
git status --short --branch
```

## 在另一台 Windows 电脑上接手

先安装 Git、GitHub CLI 和标准 Python。然后登录 GitHub：

```powershell
gh auth login
gh auth status
```

克隆自己的仓库：

```powershell
gh repo clone ViceAdmiralGrafSpee/Dice-Bot
cd Dice-Bot
```

确认或补充上游地址：

```powershell
git remote -v
git remote add upstream https://github.com/Echoer009/Odysseia-Guidance.git
git remote set-url --push upstream DISABLED
```

如果 `upstream` 已经存在，不要重复执行 `git remote add upstream`。

获取当前已经推送到 GitHub 的开发分支：

```powershell
git fetch origin
git switch --track origin/feature/onebot-adapter
```

如果本地已经有同名分支，则使用：

```powershell
git switch feature/onebot-adapter
git pull --ff-only
```

确认以下命令没有显示未提交改动，并且本地没有落后于远端：

```powershell
git status --short --branch
git log -3 --oneline
```

## 在 Linux 电脑或 VPS 上接手代码

以下只负责取得和运行代码，不等于完整的 VPS 生产部署方案：

```bash
git clone https://github.com/ViceAdmiralGrafSpee/Dice-Bot.git
cd Dice-Bot
git switch --track origin/feature/onebot-adapter
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

Linux 上启动 Dice-Bot 的命令是：

```bash
./.venv/bin/python -m src.qq_bot
```

NapCat 仍需作为另一个进程或容器运行。正式 VPS 部署尚未设计完成；以后应单独处理 Docker Compose 或 systemd、自动重启、日志轮转、健康检查、数据卷和端口防护。

## 开始一个新开发目标

目前功能仍在叠加开发分支中，不要从本地旧 `main` 直接继续开发。开始下一项工作前，先更新当前 QQ 功能分支：

```powershell
git switch feature/onebot-adapter
git pull --ff-only
```

然后从它建立一个只处理单独目标的新分支，例如：

```powershell
git switch -c feat/coc-basic-checks
```

在合并现有草稿 PR 之前，不要擅自改写分支基线、rebase、force push，或把 `main`、`refactor/platform-message-model`、`feature/onebot-adapter` 混合合并。先检查 GitHub 上的 PR 关系。

分支名建议使用：

- `chore/...`：环境、文档、维护工作
- `refactor/...`：不改变功能的结构调整
- `feat/...`：新增功能
- `fix/...`：修复缺陷

提交前至少检查：

```powershell
git status --short
git diff
git diff --cached
```

只有确认没有密钥、数据库文件和无关改动后再提交。

## 本地环境

不要使用编辑器、绘图软件或其他应用自带的 Python。应使用标准 Python 创建仓库专用虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

`.venv` 和 `.env` 已被 `.gitignore` 排除。可以这样核对：

```powershell
git check-ignore -v .venv .env
```

需要本地配置时，从示例复制，但不要提交生成的 `.env`：

```powershell
Copy-Item .env.example .env
```

QQ 本地运行至少需要在 `.env` 中填写：

```dotenv
ONEBOT_WS_URL="ws://127.0.0.1:3001"
ONEBOT_ACCESS_TOKEN="与 NapCat 相同的 Token"
DEEPSEEK_API_KEY="自己的 DeepSeek API Key"
QQ_AI_MODEL="deepseek:deepseek-chat"
```

真实值不得写入本文档或 `.env.example`。换电脑时不要通过 Git 同步 `.env`；应使用密码管理器或其他安全方式重新填写。

Windows 本地运行分成两个进程：

1. 用 NapCat 的 `launcher-user.bat` 启动机器人 QQ。
2. 在仓库目录启动 Dice-Bot：

```powershell
.\.venv\Scripts\python.exe -m src.qq_bot
```

NapCat 是 QQ 收发层，`src.qq_bot` 是机器人聊天、记忆和规则工具进程；关闭任意一边都会下线。

## 测试

收集测试而不执行：

```powershell
.\.venv\Scripts\python.exe -m pytest --collect-only -q
```

运行当前确认不依赖 PostgreSQL 的 QQ/平台/骰子回归测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_platform_models.py tests/test_platform_chat_boundary.py tests/test_discord_message_mapper.py tests/test_discord_request_context.py tests/test_message_processor_fakenitro.py tests/test_onebot_event_mapper.py tests/test_onebot_transport.py tests/test_onebot_chat_gateway.py tests/test_qq_bot_entrypoint.py tests/test_optional_postgres_chat.py tests/test_sqlite_conversation_memory.py tests/test_dice_engine.py tests/test_dice_tool_calling.py
```

截至提交 `561f4f8`，上述回归结果为 **62 passed**。如果 Windows 测试环境拒绝使用系统临时目录，可在仓库内临时指定：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_dice_engine.py -q --basetemp=.local-test-temp
```

测试后只删除确认位于仓库内的 `.local-test-temp`；不要删除正式的 `data/`。

完整测试套件中的多数用例会连接 PostgreSQL。没有独立测试数据库时，不要运行会截断表数据的数据库测试；`tests/conftest.py` 包含 `TRUNCATE ... CASCADE`。测试数据库绝对不能指向生产数据库。

## Phase 0 基线（2026-08-13）

- 基线提交：`81cf9091eebe8012859a4655ee22cac0ed01c51f`
- 上游、Fork 和本地 `main` 在建立分支时指向同一提交。
- Phase 0 分支：`chore/phase-0-baseline`
- `origin` 指向个人 Fork；`upstream` 已禁用推送。
- 仓库未创建 `.env`，未写入任何真实凭据。
- Python 3.12.10 可以安装当前 `requirements.txt`。
- 共收集到 98 个测试。
- 上述非数据库小型基线结果：13 passed，1 个来自 `discord.py` 的弃用警告。
- 本机没有 Docker 和 PostgreSQL，因此数据库集成测试尚未建立通过基线。

当前上游存在一个需要以后单独处理的环境矛盾：README 标注 Python 3.13，`.devcontainer/Dockerfile` 使用 Python 3.11.5，而 `requirements.txt` 固定 `numpy==1.26.4`。该 NumPy 版本无法在 Python 3.13 上直接安装。Phase 0 不修改依赖，只记录事实。

## 当前开发状态（更新至 2026-08-13）

当前工作分支：`feature/onebot-adapter`

当前已推送提交：`561f4f8 feat: expose dice through modular tool calling`

草稿 PR：[PR #3](https://github.com/ViceAdmiralGrafSpee/Dice-Bot/pull/3)

当前采用叠加分支：`feature/onebot-adapter` 建立在 `refactor/platform-message-model` 之上。PR #3 的前置是平台消息边界 [PR #2](https://github.com/ViceAdmiralGrafSpee/Dice-Bot/pull/2)。在 GitHub 上整理合并顺序前，不要把本地旧 `main` 强行合入这两个分支。

已经完成：

- 平台无关的消息、会话和请求上下文边界。
- Discord 事件转换到共享聊天边界；原 Discord 入口暂未删除。
- NapCat OneBot 11 正向 WebSocket 收发和断线重连。
- QQ 正式入口：`python -m src.qq_bot`。
- DeepSeek Provider 环境变量配置；QQ 业务没有绑定死某个 Provider。
- PostgreSQL 变为可选增强项；没有 PostgreSQL 也能基础聊天。
- QQ 群聊和私聊最近消息保存在 `data/memory.sqlite3`。
- 普通群消息进入上下文但不触发 LLM；群聊明确 @机器人时回复。
- 每个会话保存最近 500 条原始消息，最近 35 条进入短期上下文；会话互相隔离，重启后仍保留。
- Python Dice Engine 和不经过 LLM 的 `.r 1d100`、`.r 2d6+3` 命令。
- 平台无关工具注册表，以及由 LLM 调用的 `roll_dice`。
- 工具随机数和总数由 Python 锁定；LLM 只负责表述。LLM 二次表述失败时仍返回权威骰子结果。

当前没有完成：

- SQLite 用户长期档案、长期摘要和记忆候选审核。
- COC、DND、WINNING GIRLS 等规则系统工具。
- Campaign、Character、规则状态、成长和 Log 数据结构。
- QQ 图片下载和多模态理解。
- OneBot 回复消息正文获取、撤回/编辑等高级事件。
- VPS 生产部署、自动启动、备份和监控。
- 将叠加草稿 PR 整理、审查并合并到 `main`。

## 重要文件地图

- `src/qq_bot.py`：QQ 正式启动入口和最小运行时初始化。
- `src/chat/platform/onebot/`：NapCat/OneBot 映射、传输、请求上下文和消息路由。
- `src/chat/platform/`：平台无关消息与请求协议。
- `src/chat/services/chat_service.py`：共享聊天编排；不应重新绑定 `discord.Message`。
- `src/chat/memory/conversation_repository.py`：SQLite 最近会话记录。
- `src/chat/dice/engine.py`：权威随机数和骰子计算。
- `src/chat/dice/commands.py`：`.r` 快速命令。
- `src/chat/dice/tool.py`：LLM 可调用的 `roll_dice` 定义。
- `src/chat/tools/runtime.py`：通用工具注册、Provider 格式转换和执行边界；COC/DND 工具应复用这里。
- `docs/NAPCAT_LOCAL_TEST.md`：本地 NapCat、正式 QQ 入口、记忆和骰子测试说明。

## 不会随 Git 自动迁移的数据

以下内容被 Git 忽略，换电脑或迁移 VPS 时需要另行安全处理：

- `.env`：包含 OneBot Token 和 DeepSeek Key，只能安全地重新填写。
- `data/memory.sqlite3`：QQ 最近会话记录；需要记忆时单独备份。
- `data/chat.db`：本地聊天设置。
- `data/world_book.sqlite3`：旧世界书 SQLite 数据。
- NapCat 的 QQ 登录状态和本地配置目录。

不要把这些文件临时取消忽略后提交到 GitHub。

## 让 Codex / ChatGPT 在另一台电脑继续工作

打开克隆后的 `Dice-Bot` 目录，并先让助手阅读本文件。可以使用下面的开场要求：

```text
请先完整阅读 MAINTAINING.md 和 docs/NAPCAT_LOCAL_TEST.md，然后检查当前分支、git status、origin、upstream 和最近三个提交。
当前工作基线是 origin/feature/onebot-adapter，提交 561f4f8；不要从旧 main 直接开发，不要 rebase 或 force push。
不要读取、显示或提交 .env 和 data 目录中的真实数据。
修改前先说明范围，一个 commit 只完成一个容易解释的目标，完成后运行相关回归测试。
LLM 只负责自然语言理解与表述；骰子、规则状态和数据库修改必须由 Python 决定。
新增 COC/DND/WINNING GIRLS 功能时，优先作为独立规则工具模块注册到 src/chat/tools，不要把规则写进 OneBot Adapter 或 Prompt。
```

如果 GitHub 上还没有当前本地分支或最新 commit，另一台电脑无法取得这些工作。切换电脑前应先确认当前分支已经有意地 commit 并 push；不要用复制 `.env` 的方式同步秘密。
