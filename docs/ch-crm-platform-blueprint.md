# CH-CRM Platform Blueprint

## Domain vs Platform

### Domain modules
- `deals`: сделки, версии проекта, клиентский портал, файлы проекта, сметы, конфигуратор.
- `clients`: карточки клиентов и клиентские данные.
- `catalog`: справочник расчётных позиций и опций.
- `tasks`: задачи по сделкам и внутренние вложения.

### Platform modules
- `accounts`: пользователи, роли, личные сообщения, уведомления, аудит, WebSocket events.
- `system_settings`: системные настройки, integration tokens, platform jobs, административные справочники.
- `core`: маршрутизация, глобальная навигация, общие страницы.

### Coupling to reduce over time
- Роли и доступ сейчас проверяются прямо в views через `is_file_only_role()` и `is_leadership()`.
- Справочник каталога частично редактируется внутри deal-flow.
- Интеграционный API живёт в `deals.api_views`, хотя это уже platform surface.
- Долгие и периодические задачи пока выполняются внутри web-процесса или вручную.

## System Settings IA

### Current routes
- `/settings/employees/`
- `/settings/library/`
- `/settings/catalog/`
- `/settings/catalog/items/new/`
- `/settings/catalog/items/<id>/`
- `/settings/business/`
- `/settings/integrations/`

### Ownership
- Доступ ко всему разделу получают только `head` и `admin`.
- Основной guard: `system_settings.decorators.leadership_required`.

## First Automation Events

`TOP_DOMAIN_EVENTS` в `system_settings/events.py` — пять имён, которые страница `/settings/integrations/` показывает подписью «Поддерживаются события»:

1. `deal.status_changed`
2. `project_version.imported`
3. `project_file.uploaded`
4. `task.created`
5. `client_message.sent`

Это не фильтр ленты Главной и не контракт плагина. Плагин пишет только `project_version.imported`. Лента читает более широкий `FEED_EVENT_TYPES` и отбрасывает остальные записанные типы. Что именно попадает на экран, какие тексты и ссылки, и какие действия журнал не видит: `docs/activity-feed.md`.

Сама запись — `record_domain_event()` → строка `AuditEvent`. Исходящих вебхуков и автоматических уведомлений из этих событий сейчас нет. Флаг `enqueue_follow_up` ни один вызов не передаёт.

## Async Jobs Scope

### What belongs in jobs first
- Очистка сессий кабинета заказчика (почту и OTP клиентам не шлём)
- Напоминания по просроченным задачам
- Поиск “зависших” сделок
- Генерация производных артефактов по файлам
- Тяжёлые импорты из внешних систем

### Current implementation
- Таблица очереди: `system_settings.PlatformJob`
- Команда запуска: `python manage.py run_platform_jobs`
- Первый реальный handler: `cleanup_expired_portal_access`

Это intentionally small queue layer на базе БД. Следующий шаг, если нагрузка вырастет, — вынести worker в отдельный процесс/сервис.

## Integration Surface

### Current state
- Endpoint: `POST /api/plugin/project-versions/`
- Поддерживается аутентификация через `IntegrationTokenAuthentication` и DRF tokens.
- Управление токенами доступно в `/settings/integrations/`.
- Outbound к умнику: `GET {UMNIK_URL}/crm/lookup` — комнаты и м² по сделке. `UMNIK_URL` — облачный query-умник, не офисный индексатор. Настройки: `UMNIK_URL`, `UMNIK_TOKEN` в `.env`.

### Near-term roadmap
1. Добавить отдельные inbound endpoints по типам интеграций.
2. Ввести журнал интеграционных вызовов.
3. Публиковать domain events как webhooks.
4. Разнести plugin-specific logic и generic integration contracts.

## Business Settings

Сейчас в `system_settings.SystemConfig` поддерживаются:
- `default_margin_percent`
- `stale_deal_days`
- `task_reminder_hours`

Эти параметры должны применяться ко всем новым процессам, а не зашиваться в form/view constants.
