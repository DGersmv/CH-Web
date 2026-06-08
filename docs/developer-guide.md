# Developer Guide

Краткий справочник для ежедневной разработки CH-Web. Операционные команды здесь
дополняют быстрый старт из `README.md`, а доменные правила остаются в
`ARCHITECTURE.md`.

## Карта документации

| Документ | Когда читать |
| --- | --- |
| `README.md` | Запуск Docker, миграции, демо-данные, файловое хранилище, проверки после деплоя. |
| `ARCHITECTURE.md` | Роли, бизнес-правила, ключевые сущности CRM. |
| `docs/excel-formula-spec.md` | Правила расчета стоимости и UI-поток калькулятора. |
| `docs/plugin-api-contract.md` | Контракт REST API для ArchiCAD-плагина. |
| `IMPLEMENTATION_PLAN.md` | Исторический план фаз и незавершенные работы. |

## Runtime stack

`docker-compose.yml` поднимает три сервиса:

| Сервис | Назначение | Порт на хосте |
| --- | --- | --- |
| `app` | Django ASGI через Daphne (`core.asgi:application`) | `8001` |
| `db` | PostgreSQL 16 | `5433` |
| `redis` | Channel layer для WebSocket-уведомлений | `6379` |

Контейнер `app` перед запуском Daphne выполняет `migrate --noinput` и
`collectstatic --noinput`. Если `DJANGO_SEED_DEMO_DATA=1` или `true`, после
миграций также запускается `python manage.py seed_demo_data`.

## Ежедневный цикл разработки

```bash
docker compose up -d
docker compose logs app --tail=120
docker compose exec app python manage.py test
docker compose exec app python manage.py showmigrations
```

- После изменений Python-кода, URL-ов, ASGI/Channels или настроек перезапусти
  `app`: `docker compose restart app`.
- После изменений шаблонов и статики обычно достаточно обновить страницу
  браузера; при сомнениях используй Ctrl+F5.
- Для команд `manage.py` предпочитай контейнер `app`, потому что внутри него БД
  доступна как `db`, а Redis как `redis`.

## Переменные окружения

Базовый набор смотри в `.env.example`. Частые флаги:

- `REDIS_URL` - адрес Redis для `channels_redis` (`redis://redis:6379/0` в Compose).
- `CRM_FILES_ROOT` - корень локального файлового хранилища; по умолчанию
  `crm_files` в корне репозитория.
- `DJANGO_SEED_DEMO_DATA` - автозапуск демо-сида при старте `app`, если значение
  `1`, `true` или `True`.
- `USE_HTTPS` - включает secure cookies и `SECURE_SSL_REDIRECT`.

Если в значении для Compose есть символ `$`, экранируй его как `$$`.

## Карта кода

| Область | Основные файлы |
| --- | --- |
| Настройки, URL, ASGI | `core/settings.py`, `core/urls.py`, `core/asgi.py`, `core/routing.py` |
| Dashboard, списки, detail page | `core/views.py`, `templates/home.html`, `templates/deal_detail.html` |
| Сделки и расчеты | `deals/models.py`, `deals/views.py`, `deals/services/` |
| Клиенты | `clients/models.py`, `clients/forms.py`; UI-view функции сейчас в `core/views.py` |
| Задачи | `tasks/models.py`, `tasks/views.py`, `templates/includes/deal_tasks_block.html` |
| Каталог цен | `catalog/models.py`, `catalog/views.py`, `catalog/admin.py` |
| Пользователи, роли, уведомления | `accounts/models.py`, `accounts/permissions.py`, `accounts/events.py`, `accounts/consumers.py` |

## WebSocket-уведомления

Realtime-слой использует Django Channels:

- клиент открывает `/ws/events/` из `templates/base.html`;
- `UserEventsConsumer` подписывает авторизованного пользователя на группу
  `user_{id}_events`;
- события отправляются через `accounts.events.push_user_event(...)`;
- сейчас используются payload-типы `notification.created` и `message.created`.

Для диагностики проверь, что контейнер `redis` healthy, `REDIS_URL` указывает на
Redis, а приложение запущено через Daphne/ASGI, а не `runserver`.

## Файлы проекта

Сделочный workspace хранится в `CRM_FILES_ROOT` и создается через
`deals.services.storage_paths.ensure_deal_dirs(...)`.

Основные операции:

- загрузка: `deals/<id>/files/upload/`;
- открыть/preview: `deals/files/<file_id>/open/`;
- массовая загрузка ZIP или архивирование: `deals/<id>/files/<source>/bulk/`;
- архивирование одного файла: `deals/files/<file_id>/archive/`.

Права доступа задает `accounts.permissions.can_access_file_source(...)`:

- `designer` видит файлы проектировщика;
- `production` относится к file-only ролям и не может менять сделку/стоимость;
- `head` и `admin` видят клиентские, sales и системные источники.

## Plugin API local check

Полный контракт описан в `docs/plugin-api-contract.md`. Для локального smoke
test нужен DRF token:

```bash
docker compose exec app python manage.py drf_create_token <username>
curl -X POST http://localhost:8001/api/plugin/project-versions/ \
  -H "Authorization: Token <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "project_code":"3МД-Иван-Пулково",
    "module_count":3,
    "source":"archicad",
    "objects":[{"guid":"wall-001","type":"wall","params":{"area":12.5}}]
  }'
```

API принимает только аутентифицированные запросы и создает новую
`ProjectVersion` для переданного `project_code`. Если сделки с таким кодом нет,
она создается в статусе `orphan`.

## Troubleshooting

- Контейнер `app` перезапускается: `docker compose logs app --tail=200`.
- Миграции не применились: `docker compose exec app python manage.py showmigrations`.
- Не приходят уведомления: проверь `redis`, `REDIS_URL`, WebSocket `/ws/events/`
  в браузере и события из `accounts/events.py`.
- Файлы не открываются: проверь `CRM_FILES_ROOT`, относительный путь
  `ProjectFile.relative_path` и права роли на `source`.
- Стоимость выглядит устаревшей: открой полный расчет сделки, нажми
  `Пересчитать`/`Сохранить`; ручное редактирование компактной панели пишет
  только totals draft-версии.
