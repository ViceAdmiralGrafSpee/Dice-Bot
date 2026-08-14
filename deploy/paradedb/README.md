# Dice-Bot 数据库部署

这里的 Compose 只运行 ParadeDB/PostgreSQL。它不会启动 Discord Bot、QQ
Dice-Bot、NapCat、网页、Caddy、SearXNG 或 Ollama。

## 安全边界

- 数据库端口固定绑定 `127.0.0.1:5432`，不能改为 `0.0.0.0`。
- 镜像同时锁定版本与多架构 manifest digest，不使用 `latest`。
- 真实密码只保存在 VPS 的 `/home/ubuntu/apps/Dice-Bot/.env`。
- 不覆盖或删除 `/home/ubuntu/apps/Dice-Bot/.env`、`.venv/`、`data/`。
- PostgreSQL 使用独立 Docker volume `dice-bot-paradedb-data`。
- 停止服务时禁止使用 `docker compose down -v`。

QQ Dice-Bot 由宿主机 systemd 运行，因此生产 `.env` 中数据库地址应为：

```dotenv
DB_HOST=127.0.0.1
DB_PORT=5432
POSTGRES_DB=dice_bot
POSTGRES_USER=dice_bot
POSTGRES_PASSWORD=请在VPS上生成随机长密码
```

不要把上面的占位内容复制回仓库，也不要在终端截图或日志中显示真实密码。

## 启动数据库

源码镜像目录：`/home/ubuntu/repos/Dice-Bot`
生产运行目录：`/home/ubuntu/apps/Dice-Bot`

```bash
cd /home/ubuntu/repos/Dice-Bot
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  config --quiet
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  up -d
```

验证端口和健康状态：

```bash
ss -ltn | grep '127.0.0.1:5432'
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f /home/ubuntu/repos/Dice-Bot/deploy/paradedb/compose.yml \
  ps
```

若输出出现 `0.0.0.0:5432` 或 `[::]:5432`，立即停止数据库并检查 Compose，
不要继续迁移。

## 全新测试库迁移

首次生产迁移或更换镜像前，必须先运行：

```bash
cd /home/ubuntu/repos/Dice-Bot
/home/ubuntu/apps/Dice-Bot/.venv/bin/python \
  deploy/paradedb/verify_fresh_migrations.py \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  --source-dir /home/ubuntu/apps/Dice-Bot
```

验证器会建立随机命名的临时数据库、执行 `alembic upgrade head`、核对扩展、
迁移 head、长期记忆表和索引，然后删除临时数据库。它不会连接或修改生产库。
验证失败时不要启动 QQ Bot 的 PostgreSQL 能力。

## 外部 Embedding

长期记忆的聊天模型与 Embedding Provider 相互独立。DeepSeek 可以继续负责聊天，
Embedding 使用另一个兼容 OpenAI `/embeddings` 接口的外部 Provider。只在 VPS 私密
`.env` 中添加：

```dotenv
VECTOR_MODE=api
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_API_BASE_URL=https://你的Provider地址/v1
EMBEDDING_API_KEY=只保存在VPS的真实Key
EMBEDDING_MODEL=实际的1024维Embedding模型
EMBEDDING_DIMENSION=1024
EMBEDDING_API_TIMEOUT_SECONDS=30
EMBEDDING_SEND_DIMENSIONS=false
```

所选模型必须返回正好 1024 维向量。如果 Provider 需要请求中的 `dimensions`
参数，再把 `EMBEDDING_SEND_DIMENSIONS` 改为 `true`。程序会拒绝维度错误、非数字或
非有限数值，不会截断或填充向量，也不会改用 DeepSeek 伪造 embedding。

## 备份

建议每天执行一次自定义格式逻辑备份，并把至少一份副本保存在 VPS 之外。
备份目录不要放进 Git 仓库或应用的 `data/`：

```bash
install -d -m 700 /home/ubuntu/backups/dice-bot/postgres
BACKUP_FILE="/home/ubuntu/backups/dice-bot/postgres/dice-bot-$(date -u +%Y%m%dT%H%M%SZ).dump"
cd /home/ubuntu/repos/Dice-Bot
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner --no-acl' \
  > "$BACKUP_FILE"
chmod 600 "$BACKUP_FILE"
pg_restore --list "$BACKUP_FILE" > /dev/null
```

备份成功的最低条件是命令退出码为零、文件非空，并且 `pg_restore --list` 可以
读取。建议按“每日 7 份、每周 4 份”保留，并定期复制到另一台受控主机或私有对象
存储。不要只备份 Docker volume；逻辑备份更适合跨镜像恢复。

## 恢复演练

恢复必须先落到新建测试库，不要直接覆盖生产库：

```bash
cd /home/ubuntu/repos/Dice-Bot
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  exec -T db sh -c 'createdb -U "$POSTGRES_USER" dice_bot_restore_test'
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  exec -T db sh -c 'pg_restore -U "$POSTGRES_USER" -d dice_bot_restore_test --clean --if-exists --no-owner --no-acl' \
  < /home/ubuntu/backups/dice-bot/postgres/待验证备份.dump
```

核对表、记录数量和 Alembic revision 后，删除测试库：

```bash
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  exec -T db sh -c 'dropdb -U "$POSTGRES_USER" --if-exists dice_bot_restore_test'
```

正式灾难恢复时先停止 QQ Dice-Bot，再新建空生产库并恢复。恢复完成并验证后才
重启 systemd 服务。

## 回滚

在应用尚未启用 PostgreSQL 能力时，回滚只需停止数据库：

```bash
cd /home/ubuntu/repos/Dice-Bot
docker compose \
  --env-file /home/ubuntu/apps/Dice-Bot/.env \
  -f deploy/paradedb/compose.yml \
  stop
```

保留 `dice-bot-paradedb-data` volume 和备份。不要删除现有 SQLite 文件，也不要
让源码同步工具使用会删除目标目录额外文件的选项。
