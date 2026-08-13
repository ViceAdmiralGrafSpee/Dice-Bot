# Dice-Bot 维护与开发约定

本仓库是基于 [Echoer009/Odysseia-Guidance](https://github.com/Echoer009/Odysseia-Guidance) 的衍生项目，继续遵循 AGPL-3.0。保留原项目的版权和许可证信息；新增代码和文档不得删除或弱化这些信息。

当前目标是渐进地把 Discord 平台层与聊天核心解耦，并在保留 Discord 支持的同时增加 QQ / OneBot 11 / NapCat 适配。不要一次性重写整个项目。

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

获取已经推送到 GitHub 的开发分支：

```powershell
git fetch origin
git switch --track origin/chore/phase-0-baseline
```

如果本地已经有同名分支，则使用：

```powershell
git switch chore/phase-0-baseline
git pull --ff-only
```

## 开始一个新开发目标

先让本地 `main` 与上游保持一致：

```powershell
git switch main
git fetch upstream
git merge --ff-only upstream/main
git push origin main
```

然后为单独目标建立新分支：

```powershell
git switch -c refactor/platform-message-boundary
```

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

## 测试

收集测试而不执行：

```powershell
python -m pytest --collect-only -q
```

运行当前确认不依赖 PostgreSQL 的小型基线：

```powershell
python -m pytest -q tests/test_message_processor_fakenitro.py tests/test_persona_preference.py::TestGetPersonaSystemPrompt tests/test_persona_preference.py::TestPersonaVariantsDataIntegrity
```

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

## 让 Codex / ChatGPT 在另一台电脑继续工作

打开克隆后的 `Dice-Bot` 目录，并先让助手阅读本文件。可以使用下面的开场要求：

```text
请先阅读 MAINTAINING.md，并检查当前分支、git status、origin 和 upstream。
不要在 main 上修改，不要读取或提交真实密钥。
修改前先说明范围，每次只完成一个小目标；修改后列出文件、行为影响和测试结果。
当前优先目标是让核心聊天流程逐渐不再依赖 discord.Message，同时保留 Discord 支持。
```

如果 GitHub 上还没有当前本地分支或最新 commit，另一台电脑无法取得这些工作。切换电脑前应先确认当前分支已经有意地 commit 并 push；不要用复制 `.env` 的方式同步秘密。
