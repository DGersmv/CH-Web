# Умный умник на VPS (роль query)

Умник **не в Docker**. Он systemd-сервис пользователя `admin` на хосте, пишет в `/home/admin/ch-crm` (тот же каталог, что смонтирован в контейнер `app`).

## Один раз

```bash
cd /home/admin/ch-crm/umnik
python3 -m venv .venv
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt
```

`umnik/.env`:

```
UMNIK_ROLE=query
MCP_CRM_MODE=1
MCP_TOKEN=<тот же, что UMNIK_TOKEN в ~/ch-crm/.env>
MCP_PORT=7861
MCP_HOST=0.0.0.0
CRM_API_URL=http://127.0.0.1:9090
CRM_ROOT=/home/admin/ch-crm
PLATFORM_OWNER_USERNAME=superadmin
INDEX_S3_BUCKET=ch-crm
INDEX_S3_PREFIX=umnik-index
INDEX_S3_ENDPOINT=https://s3.cloud.ru
INDEX_S3_REGION=ru-central-1
INDEX_S3_ACCESS_KEY=
INDEX_S3_SECRET_KEY=
```

Порт **7861 в группу безопасности не открывать**. CRM достукивается с контейнера через `host.docker.internal`.

В `~/ch-crm/.env`:

```
UMNIK_URL=http://host.docker.internal:7861
UMNIK_TOKEN=<тот же MCP_TOKEN>
PLATFORM_OWNER_USERNAME=superadmin
```

Сервис:

```bash
sudo cp /home/admin/ch-crm/umnik/deploy/ch-crm-umnik.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ch-crm-umnik
```

Пользователь `admin` должен быть в группе `docker`, иначе `restart_crm` не выполнит `docker compose restart app`.

Claude Code на этой машине (правки кода из чата):

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

Без `claude login` lookup и поиск по индексу работают, чат с правками кода — нет.

После смены Python в CRM владелец жмёт «Перезапустить CRM» в шапке чата. Пересобирать образ (`requirements.txt`, Dockerfile) кнопка не умеет.
