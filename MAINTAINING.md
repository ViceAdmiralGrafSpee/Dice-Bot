# Dice-Bot 维护与开发约定

本仓库是基于 [Echoer009/Odysseia-Guidance](https://github.com/Echoer009/Odysseia-Guidance) 的衍生项目，继续遵循 AGPL-3.0。保留原项目的版权和许可证信息；新增代码和文档不得删除或弱化这些信息。

当前项目采用 QQ 优先路线：通过 OneBot 11 / NapCat 接入 QQ，现有 Discord 代码暂时保留，QQ 正式入口不会启动 Discord 社区功能。项目定位是“以确定性 TRPG 后端为核心、LLM 作为自然语言 Agent 前端的群聊骰娘”，不是单纯把骰子命令与聊天模型拼在一起。不要一次性重写整个项目，也不要为了删除 Discord 而破坏已经可用的 QQ 链路。

## 不可破坏的原则

- `main` 只保存可追溯的稳定状态，不直接在 `main` 上开发。
- 一次只做一个小目标，一个 commit 只表达一个容易解释的变化。
- 修改前先说明范围；修改后列出文件、原因、行为影响和测试方法。
- LLM 负责意图理解、自然语言交互、工具选择、说明、角色扮演和总结。
- 骰子随机数、数值计算、规则状态机和数据库修改必须由 Python 程序执行。
- 传统命令和自然语言 Agent 必须共享同一套底层 Service，不得实现两套角色或规则系统。
- DeepSeek 暂时不可用时，传统骰娘命令仍应正常工作。
- AgentRuntime 必须通过现有 AIService / BaseProvider 边界调用模型，不得绑定 DeepSeek；模型特有协议只放在对应 Provider 或 Adapter。
- 不提交 `.env`、API Key、Discord/QQ Token、数据库密码或任何真实凭据。
- `.env.example` 只能包含占位符和安全默认值。
- 不为了代码风格或“更优雅”顺手重构与当前目标无关的模块。

## 主仓库、镜像与远程地址

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

GitHub `ViceAdmiralGrafSpee/Dice-Bot` 仍是最终主版本源。Gitee 已建立从 GitHub 拉取的 Pull 镜像，当前方向仅为：

```text
GitHub → Gitee
```

Gitee 用于国内网络环境下快速取得部署源码。不要假定存在双向同步，不要默认从 Gitee 回推 GitHub，也不要把 GitHub Personal Access Token 写入仓库、文档、命令历史或聊天。Gitee 镜像的实际 URL 应从 Gitee 页面或安全的服务器配置中核对，本文档不记录令牌化地址。

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

先获取远端状态并检查近期分支，不要根据旧文档硬猜最新开发分支：

```powershell
git fetch origin
git branch -r --sort=-committerdate
git log -5 --oneline origin/feat/character-archive
git switch --track origin/feat/character-archive
```

如果本地已经有同名分支，则使用：

```powershell
git switch feat/character-archive
git pull --ff-only
```

确认以下命令没有显示未提交改动，并且本地没有落后于远端：

```powershell
git status --short --branch
git log -3 --oneline
```

## VPS 生产环境

腾讯云 Ubuntu VPS 是当前生产运行环境：

```text
生产目录：/home/ubuntu/apps/Dice-Bot
systemd：dice-bot.service
启动命令：/home/ubuntu/apps/Dice-Bot/.venv/bin/python -m src.qq_bot
```

服务已设置开机启动和自动重启。常用检查命令：

```bash
sudo systemctl restart dice-bot
systemctl status dice-bot --no-pager
journalctl -u dice-bot -n 80 --no-pager -l
```

任何部署或同步操作都不得覆盖或删除：

```text
/home/ubuntu/apps/Dice-Bot/.env
/home/ubuntu/apps/Dice-Bot/.venv/
/home/ubuntu/apps/Dice-Bot/data/
```

其中 `.env` 保存 OneBot、DeepSeek 等私密配置，`.venv` 是生产 Python 环境，`data/` 包含 SQLite 聊天与运行数据。不要要求用户发送这些内容，也不要在日志或终端输出中显示密钥。

生产目录最初可能来自 ZIP 上传，不保证本身是 Git 仓库。在确认 `/home/ubuntu/apps/Dice-Bot/.git` 存在且远程、分支和工作树都正确之前，禁止直接在生产目录执行 `git pull`。

推荐逐渐采用源码仓库与运行目录分离：

```text
/home/ubuntu/repos/Dice-Bot  从 Gitee Pull 镜像取得的纯源码 Git 仓库
/home/ubuntu/apps/Dice-Bot   实际生产运行目录
```

从 `repos` 同步到 `apps` 时必须排除：

```text
.git/
.env
.venv/
data/
```

不要使用 `rsync --delete`，尤其是增量包只有 `src/` 和 `tests/` 时。此前的“本地代码 → ZIP 增量包 → 上传 VPS → rsync 覆盖指定目录 → 重启服务”仍可作为受控回退方式，但不能删除生产数据。

目标部署链路是：

```text
本地开发 → push GitHub → GitHub Pull 同步到 Gitee
→ VPS 在 repos 目录从 Gitee 拉取 → 排除生产数据后同步到 apps
→ 重启 dice-bot.service → 检查状态和日志
```

## 开始一个新开发目标

目前功能仍在叠加开发分支中，不要从本地旧 `main` 或旧 `feature/onebot-adapter` 直接继续开发。开始下一项工作前，必须先检查 GitHub 实际远端分支和源码；截至 2026-08-14，最新开发分支是：

```powershell
git fetch origin
git switch feat/character-archive
git pull --ff-only
```

然后从它建立一个只处理单独目标的新分支，例如：

```powershell
git switch -c feat/trpg-sqlite-foundation
```

`feat/character-archive` 基于 NapCat 离线监控、DND5e/DND5r、统一命令和角色导入分支继续发展。在整理现有叠加分支之前，不要擅自改写分支基线、rebase、force push，或把旧 `main` 与这些分支混合合并。先检查 GitHub 上的实际 PR 关系。

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

运行当前确认不依赖 PostgreSQL 的 QQ、平台、命令、骰子和 DND5e 回归测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_command_registry.py tests/test_dice_engine.py tests/test_dnd5e_rules.py tests/test_dnd5e_tool_calling.py tests/test_rule_system_registry.py tests/test_trpg_repository.py tests/test_character_draft_workflow.py tests/test_dnd5e_character_import.py tests/test_dnd5r_xlsx_import.py tests/test_onebot_event_mapper.py tests/test_onebot_file_transfer.py tests/test_dnd5r_qq_character_commands.py tests/test_sqlite_conversation_memory.py tests/test_qq_bot_entrypoint.py tests/test_platform_models.py
```

完成长期记忆实现后，不依赖真实 PostgreSQL 的轻量回归结果为 **166 passed**。以下 8 个文件要求真实 PostgreSQL、旧迁移核对数据或专用 fixture，不属于轻量套件：`test_affection_service_pg.py`、`test_coin_service_pg.py`、`test_economy_integration.py`、`test_economy_user_migration.py`、`test_economy_user_models.py`、`test_interaction_service_pg.py`、`test_persona_preference.py`、`test_warning_service_pg.py`。如果 Windows 测试环境拒绝使用系统临时目录，可在仓库内临时指定：

完整轻量套件可用 PowerShell 动态排除上述文件，避免新增测试被旧的显式列表漏掉：

```powershell
$postgresTests = @(
  "test_affection_service_pg.py", "test_coin_service_pg.py",
  "test_economy_integration.py", "test_economy_user_migration.py",
  "test_economy_user_models.py", "test_interaction_service_pg.py",
  "test_persona_preference.py", "test_warning_service_pg.py"
)
$lightTests = Get-ChildItem tests -Filter "test_*.py" |
  Where-Object { $_.Name -notin $postgresTests } |
  ForEach-Object { $_.FullName }
.\.venv\Scripts\python.exe -m pytest -q $lightTests
```

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

## 当前开发状态（更新至 2026-08-14）

本轮长期记忆工作建立在 GitHub `feat/character-archive@fcd4e30` 之上。本地按小目标形成以下提交；推送后仍应重新查询 GitHub 与 Gitee 的实际 SHA：

```text
2f85169 fix: gate optional postgres capabilities
56c938b fix: require secure embedding endpoints
b74a5cc feat: retrieve long-term memory during QQ chat
57a9fb8 feat: add external API embeddings for memory
21afa6f refactor: split optional PostgreSQL capabilities
f535fe4 feat: bootstrap platform user profiles for QQ
bcf8726 test: verify Alembic on a fresh ParadeDB
94cd80e infra: add database-only ParadeDB deployment
fcd4e30 feat: add safe character archiving
```

每次开发前仍必须查询远端，因为分支状态可能继续变化。整理合并顺序前不要把旧 `main` 强行混入这些分支。

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
- 平台无关的传统 `CommandRegistry`，现有 `.r` 已迁入统一命令框架。
- 平台无关的规则系统注册边界 `RuleSystemRegistry`。
- DND5e 2014 基础规则插件及确定性 d20 检定引擎。
- 传统命令 `.dnd5e check`，支持普通、优势、劣势和明确加减值。
- LLM Tool `dnd5e_check`；骰值、取高/取低和总值由 Python 锁定。
- QQ runtime 同时注册传统命令和 DND5e Tool。
- `CommandRegistry` 已支持异步 handler，传统命令可在未来安全等待 SQLite，而不会阻塞 QQ 事件循环。
- 已建立平台无关的 `ActionContext` / `ActionResult` / `Action` 边界。
- `.dnd5e check` 与 `dnd5e_check` Tool 已调用同一个 `Dnd5eCheckAction`；参数入口不同，但规则执行与结构化权威结果只有一份。
- 已建立独立的 `data/trpg.sqlite3` 数据边界、schema 版本记录和异步 Repository。
- Character 与 Campaign 通过多对多参团记录关联；同一角色可加入多个团并保留各团独立状态。
- 已建立 `CharacterServiceRegistry`，在写数据库前按 `ruleset_key` 选择规则专用 Character Service。
- 已建立共享 `ImportCharacterAction` 和首个 `Dnd5eCharacterService`；当前支持内部标准格式 `dice_bot_json_v1`，最小校验角色名、2014 版标识和可选的 1–20 级等级。
- DND5r XLSX 草稿流程已接入 QQ：同一用户在同一会话上传文件后可使用 `.pc import`，再以 `.pc preview <草稿ID>` 查看，并用精确口令 `确认 <草稿ID>` 入库。
- 正式角色卡可用 `.pc list` 按 QQ 身份列出；`.pc delete <角色ID>` 只生成删除预览，只有同一所有者继续发送精确口令 `确认删除 <角色ID>` 才会将角色归档。
- 腾讯云 Ubuntu VPS 已通过 `dice-bot.service` 生产运行，并设置开机启动和自动重启。
- GitHub 主仓库到 Gitee 的单向 Pull 镜像已建立。
- 已增加只启动 ParadeDB/PostgreSQL 的数据库专用 Compose；数据库固定绑定 `127.0.0.1:5432`，镜像锁定版本和 digest。
- 已提供临时空库 Alembic 验证器和备份/恢复演练说明；当前单一 migration head 为 `add_conv_api_embedding`。
- PostgreSQL 档案、长期记忆、记忆笔记、人格、好感度和金币已拆成独立能力，不再全开全关。
- `POSTGRES_CAPABILITIES` 可进一步显式限制应用能力；QQ 长期记忆部署使用 `profiles,conversation_memory`，即使旧迁移建立了其他社区表也不会调用金币、好感度、人格或记忆笔记路径。
- QQ 首次聊天会以 `qq:<用户ID>` 自动建立最小档案；Discord 保留历史原始 ID 兼容性。
- 外部 Embedding 使用独立 OpenAI-compatible Provider，不绑定 DeepSeek；向量使用专用 `api_embedding halfvec(1024)`。
- 长期记忆会在主聊天流程中自动生成对话块并进行向量 + BM25/RRF 检索，不要求 LLM 主动调用工具；Embedding 故障时普通聊天继续工作。

当前没有完成：

- 长期摘要、记忆候选人工审核，以及现有旧 PostgreSQL 社区档案的数据清理策略。
- Campaign Service / Action、Character 查询和修改，以及规则状态、成长和 Log 的业务逻辑。
- DND5e 2014 角色卡的 QQ 导入入口；当前 QQ XLSX 入口只面向独立的 DND5r / 2024 规则服务。
- 可持久化、可中断恢复的 Workflow / Session 多轮任务层。
- “自然语言启动并完成一张 DND5e 角色卡创建”的端到端 Agent 场景。
- `.pc` 的详情查询、修改、切换当前角色、恢复归档角色等日常管理命令，以及 `.st` 等传统角色卡命令；当前已有导入、预览、确认、列表和安全删除。
- COC、完整 DND5e 角色规则、WINNING GIRLS 等系统插件。
- QQ 规则资料 RAG / `search_rules` Tool；实际资料应只放本地或 VPS，不进入公开仓库。
- QQ 图片下载和多模态理解。
- OneBot 回复消息正文获取、撤回/编辑等高级事件。
- 在 VPS 临时空库实际运行完整 Alembic 链、备份恢复演练，并验证真实外部 Embedding Provider。
- VPS 自动化源码同步和 PostgreSQL 定时备份；NapCat 离线监控已经完成。
- 将叠加草稿 PR 整理、审查并合并到 `main`。

## 下一阶段架构重点

优先顺序：

1. 在 VPS 临时空库验证 ParadeDB 镜像、完整 Alembic 链和备份恢复，不直接试生产库。
2. 配置一个真实的 1024 维外部 Embedding Provider，验证多轮聊天写入与后续召回。
3. 为 DND5r 草稿增加人工纠正字段的交互入口，并补全 `.pc` 日常管理命令。
4. 建立规则分流的 Campaign Service 和对应 Action。
5. 建立可持久化 Workflow / Session 多轮任务层。
6. 完成首个 Agent 验收场景：“自然语言启动并完成一张 DND5e 角色卡创建”。

AgentRuntime 的目标依赖方向是：

```text
AgentRuntime → AIService → BaseProvider
                           ├─ GeminiProvider
                           ├─ GeminiCustomProvider
                           ├─ DeepSeekProvider
                           ├─ OpenAICompatibleProvider
                           └─ Grok / Custom 兼容路径
```

DeepSeek 特有的 `reasoning_content`、Tool Calling 协议差异或未来模型适配，只能进入 `DeepSeekProvider` 或专用 Adapter，不能写死到 AgentRuntime。

### TRPG SQLite 数据基础

本地已建立平台无关的 `src/trpg/` 数据层，默认使用独立的 `data/trpg.sqlite3`，不混入聊天记忆数据库：

1. `Campaign` 保存团名、规则系统、聊天位置和创建者等团级信息。
2. `Character` 是独立角色本体，不直接从属于某一个 Campaign。
3. `CampaignCharacter` 是角色与团之间的多对多参团记录；同一角色可以加入多个 Campaign，并分别保存本团别名和 `state_data`，避免把不同团的 HP 等临时状态互相覆盖。
4. `sheet_data` 和 `state_data` 均带版本号并以 JSON 保存，具体字段以后由 DND5e、COC、WINNING GIRLS 等规则插件校验，LLM 不得直接写数据库。
5. Repository 提供创建、读取、按所有者列出、建立参团关系、双向列出关系，以及角色导入草稿的持久化和原子确认；没有硬删除。用户删除采用 `status=archived`，保留角色数据、导入来源和参团历史。
6. 数据库当前为 schema v2，重复初始化不会清空数据；加入团时会拒绝规则系统不一致的角色。

#### 使用 DBeaver 查看 TRPG 数据

`data/trpg.sqlite3` 是标准 SQLite 文件，可以用 DBeaver 的 SQLite 连接打开。主要表的职责是：

- `characters`：一行一张正式角色卡；姓名、规则和所有者是普通列，完整卡数据位于 `sheet_data_json`。
- `character_import_drafts`：导入草稿、来源快照、映射和确认后的角色 ID。
- `campaigns`：团级记录。
- `campaign_characters`：角色与团的多对多关系，以及每个团独立的 `state_data_json`。
- `trpg_schema_migrations`：数据库结构版本，禁止手工改写。

DBeaver 适合只读检查、备份副本分析和受控的紧急修复。不要在机器人运行时直接编辑 VPS 上的正式 SQLite 文件；不要随意修改主键、所有者、迁移版本和关联字段。手工编辑 JSON 时必须保持合法 JSON，但即使格式合法也可能绕过对应规则系统的校验。日常维护优先使用 Bot 的 Command / Action / Service；必须人工修复时，先停止相关服务并备份整个 `data/trpg.sqlite3`。

Character 导入采用两级边界：Action 先交给 `CharacterServiceRegistry` 按规则系统分流，再由对应规则的 Character Service 校验和调用 Repository。DND5r 的 QQ XLSX 入口已经复用草稿 Action；DND5e 2014 暂无外部文件入口，不应将两个规则版本混用。

### DND5r / 2024 XLSX 草稿导入

现实样本已确认应按 D&D 2024 修订规则处理，项目内使用独立规则标识 `dnd5r`，不得与现有的 `dnd5e`（2014）服务混用。当前已完成安全的“XLSX → CharacterDraft → 预览 → 明确确认 → Character”后台流程：

1. 通用 `WorkbookInspector` 读取 Sheet、隐藏状态、非空单元格、公式、公式缓存、合并区域和基础诊断，不把 Excel 排版直接当数据库结构。
2. 模板通过 Sheet 和锚点单元格形成结构指纹；不按文件名识别。目前现实样本形成两类声明式 Profile：悲灵 2024 模板和中文标签相邻模板。
3. DND5r 规则插件提供最小 Character Schema，并只把确定性较高的姓名、职业、等级、种族、六项属性、HP、AC、先攻、速度等映射到草稿。
4. `.st` 中尚未解释的技能和熟练标记保存在 `extensions`；整个工作簿检查快照和未映射区域仍随草稿保留，不丢弃 Homebrew 或陌生字段。
5. 每个草稿字段保留原文件哈希、Sheet、Cell、公式缓存和来源片段。格式无法转换时记为 ERROR；合法但超出建议范围时记为 WARNING，程序不自动纠正。
6. Draft 完整内容持久化在 `data/trpg.sqlite3` 的独立草稿表，重启后仍可预览；只有草稿所有者可以查看和确认。
7. 存在 ERROR 时确认会被程序拒绝；WARNING 允许用户明确承担风险后保留原值。确认 Action 还要求用户提供精确口令 `确认 <草稿ID>`，确认前绝不会创建正式 Character。
8. `Dnd5rCharacterService` 在确认时再次校验 Schema，并在同一个 SQLite 事务中完成“创建角色 + 标记草稿已确认”。重复确认返回同一个角色，不会复制。
9. QQ 已有受限文件读取、草稿预览和明确确认入口。仍未完成 Agent Tool、字段修正界面和 TemplateProfile 数据库；确认 Action 仍不得注册成由 LLM 自主调用的 Tool。

QQ 文件流程是：NapCat 文件事件 → 平台无关 `MessageFile` → 受大小限制的临时下载 → XLSX Importer → 保存草稿 Action → 预览；用户发送精确确认口令后才调用确认 Action。最近文件只在内存中保留 5 分钟，并按平台、用户和会话隔离；临时 XLSX 分析后删除。六份私人 XLSX 只作为本地压力测试样本，不得提交到公开仓库。

## 重要文件地图

- `src/qq_bot.py`：QQ 正式启动入口和最小运行时初始化。
- `src/chat/platform/onebot/`：NapCat/OneBot 映射、传输、请求上下文和消息路由。
- `src/chat/platform/onebot/file_transfer.py`：通过 OneBot `get_file` 或 NapCat 提供的 URL 受限读取文件，并短时关联“先传文件、后发命令”的两条 QQ 消息。
- `src/chat/platform/`：平台无关消息与请求协议。
- `src/chat/services/chat_service.py`：共享聊天编排；不应重新绑定 `discord.Message`。
- `src/database/database.py`：PostgreSQL 连接和档案、长期记忆、人格、好感度、金币等独立能力探测。
- `src/database/identity.py`：平台命名空间用户身份；QQ 使用 `qq:<用户ID>`，Discord 兼容历史 ID。
- `src/database/services/member_profile_service.py`：QQ 首次聊天的最小档案冲突安全建档。
- `src/chat/services/external_embedding_service.py`：独立于聊天模型的外部 Embedding Provider 和 1024 维校验。
- `deploy/paradedb/`：数据库专用 Compose、空库迁移验证器、备份恢复和安全回滚说明。
- `src/chat/memory/conversation_repository.py`：SQLite 最近会话记录。
- `src/chat/dice/engine.py`：权威随机数和骰子计算。
- `src/chat/dice/commands.py`：`.r` 快速命令。
- `src/chat/dice/tool.py`：LLM 可调用的 `roll_dice` 定义。
- `src/chat/commands/runtime.py`：平台无关传统命令请求、结果、注册与分发。
- `src/chat/actions/runtime.py`：命令与 LLM Tool 共享的异步业务动作协议和权威结构化结果。
- `src/chat/actions/import_character.py`：所有命令和 Agent 共用的角色导入 Action；不直接识别 QQ 或模型协议。
- `src/chat/actions/character_draft.py`：保存、预览和确认草稿的共享 Action；未来命令与 Agent 必须复用。
- `src/chat/rules/runtime.py`：平台无关规则系统注册边界。
- `src/chat/rules/dnd5e/`：DND5e 2014 检定 Action、引擎、命令、Tool、规则插件及来源说明。
- `src/chat/rules/dnd5e/character_service.py`：DND5e 2014 标准角色卡的校验和持久化 Service。
- `src/chat/rules/dnd5r/character_schema.py`：DND5r / 2024 最小 Character Schema；与 2014 Schema 分离。
- `src/chat/rules/dnd5r/character_service.py`：确认后的 DND5r 二次校验和正式角色入库服务。
- `src/chat/rules/dnd5r/xlsx_importer.py`：将已识别 XLSX 确定性映射为待确认 CharacterDraft，不写数据库。
- `src/chat/rules/dnd5r/character_commands.py`：QQ 可用的 `.pc import`、草稿预览、角色列表、安全删除和精确确认路由，只调用共享 Action。
- `src/chat/tools/runtime.py`：通用工具注册、Provider 格式转换和执行边界；COC/DND 工具应复用这里。
- `src/trpg/importing/`：规则无关的 SourceSnapshot、WorkbookInspection、TemplateProfile、CharacterDraft、来源链、序列化、预览和确认服务。
- `src/trpg/models.py`：规则无关的 Campaign、Character 和多对多参团记录模型。
- `src/trpg/repository.py`：独立 TRPG SQLite 初始化、角色/团数据、按所有者列出与归档、草稿持久化和原子确认。
- `src/trpg/characters/management.py`：规则无关的角色所有权、列表和归档生命周期服务。
- `src/trpg/characters/runtime.py`：按规则系统分流 Character Service 的注册表和导入数据边界。
- `src/chat/platform/onebot/persistent_chat.py`：先记录 QQ 消息，再优先分发传统命令，未匹配且被 @ 时进入聊天核心。
- `docs/NAPCAT_LOCAL_TEST.md`：本地 NapCat、正式 QQ 入口、记忆和骰子测试说明。

## 不会随 Git 自动迁移的数据

以下内容被 Git 忽略，换电脑或迁移 VPS 时需要另行安全处理：

- `.env`：包含 OneBot Token 和 DeepSeek Key，只能安全地重新填写。
- `data/memory.sqlite3`：QQ 最近会话记录；需要记忆时单独备份。
- `data/chat.db`：本地聊天设置。
- `data/world_book.sqlite3`：旧世界书 SQLite 数据。
- `data/trpg.sqlite3`：正式角色、Campaign、参团状态、导入草稿及来源检查快照。
- 未来的 Workflow、RAG 索引数据库及 `data/rag_sources/` 私人规则资料。
- Docker volume `dice-bot-paradedb-data` 和 `/home/ubuntu/backups/dice-bot/postgres/` 中的 PostgreSQL 备份。
- NapCat 的 QQ 登录状态和本地配置目录。

不要把这些文件临时取消忽略后提交到 GitHub。

## 让 Codex / ChatGPT 在另一台电脑继续工作

打开克隆后的 `Dice-Bot` 目录，并先让助手阅读本文件。可以使用下面的开场要求：

```text
请先完整阅读 MAINTAINING.md 和 docs/NAPCAT_LOCAL_TEST.md，然后检查当前分支、git status、origin、upstream 和最近三个提交。
不要根据本段记录硬猜最新分支；先 fetch 并核对 GitHub 远端。截至 2026-08-14，本轮开发建立在 origin/feat/character-archive@fcd4e30，随后增加了数据库专用 ParadeDB、QQ 自动建档、能力拆分、外部 Embedding 和长期记忆召回提交。
不要从旧 main 或 feature/onebot-adapter 直接开发，不要 rebase 或 force push。
不要读取、显示或提交 .env 和 data 目录中的真实数据。
修改前先说明范围，一个 commit 只完成一个容易解释的目标，完成后运行相关回归测试。
LLM 负责意图理解、交互、工具选择和表述；骰子、规则状态、角色数据、数据库写入和结算必须由 Python 决定。
传统命令和自然语言 Agent 必须共享底层 Service；不要把规则写进 OneBot Adapter 或 Prompt。
AgentRuntime 必须保持 Provider 无关，DeepSeek 特有协议只放在 DeepSeekProvider 或专用 Adapter。
VPS 生产目录是 /home/ubuntu/apps/Dice-Bot；部署不得覆盖 .env、.venv/ 或 data/，不要在未确认其为正确 Git 仓库前直接 git pull。
GitHub 是主版本源，Gitee 仅是 GitHub → Gitee 的单向 Pull 部署镜像，不要默认从 Gitee 回推 GitHub。
```

如果 GitHub 上还没有当前本地分支或最新 commit，另一台电脑无法取得这些工作。切换电脑前应先确认当前分支已经有意地 commit 并 push；不要用复制 `.env` 的方式同步秘密。

## NapCat QQ 离线监控

`feat/napcat-watchdog` 分支在 `feat/dnd5e-command-tools@53b45bf` 上增加了独立的 NapCat 在线状态监控，入口为：

```bash
python -m src.napcat_watchdog
```

它通过单独的短连接调用 NapCat OneBot `get_status`，不会与 `src.qq_bot` 共用接收消息的 WebSocket。默认每 60 秒检查一次，连续 3 次失败后通过 Server酱通知一次，恢复后通知一次；只报警，不执行自动重启或自动登录。通知去重状态保存在 `data/napcat-watchdog.json`，部署时必须继续保留 `data/`。

完整配置、人工测试、systemd 安装与卸载步骤见仓库根目录的 `NAPCAT_WATCHDOG.md`。生产秘密 `SERVERCHAN_SENDKEY` 只能放在 `/home/ubuntu/apps/Dice-Bot/.env`；不得提交、打印或要求用户发送。systemd 示例位于 `deploy/systemd/napcat-watchdog.service`，监控进程应独立于 `dice-bot.service` 运行，这样聊天进程停止时仍能发出 NapCat/QQ 异常通知。
