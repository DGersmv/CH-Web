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

Операционный runbook: [system-settings-and-library.md](system-settings-and-library.md).

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
- `GET /files/` редиректит на `/settings/library/`, поэтому пункт «Файлы» в навигации для не-leadership сейчас приводит к 403.

## First Automation Events

События, которые уже стоит считать платформенными:

1. `deal.status_changed`
2. `project_version.imported`
3. `project_file.uploaded`
4. `task.created`
5. `client_message.sent`

Они уже публикуются через `system_settings.events.record_domain_event()` и могут стать источником:
- outbound webhooks
- автоматических уведомлений
- фоновых обработчиков
- аналитики и аудита

## Async Jobs Scope

### What belongs in jobs first
- Очистка просроченных OTP и client portal sessions
- Напоминания по просроченным задачам
- Поиск “зависших” сделок
- Генерация производных артефактов по файлам
- Тяжёлые импорты из внешних систем

### Current implementation
- Таблица очереди: `system_settings.PlatformJob`
- Команда запуска: `python manage.py run_platform_jobs`
- Первый реальный handler: `cleanup_expired_portal_access`
- `domain_event_follow_up` можно поставить через `enqueue_follow_up=True`, но handler не зарегистрирован; текущие вызовы `record_domain_event` follow-up не включают.
- Cron/отдельный worker в `docker-compose.yml` не настроены.

Это intentionally small queue layer на базе БД. Следующий шаг, если нагрузка вырастет, — вынести worker в отдельный процесс/сервис.

## Integration Surface

### Current state
- Endpoint: `POST /api/plugin/project-versions/`
- Поддерживается аутентификация через `IntegrationTokenAuthentication` (`Bearer`/`Token`) и DRF `TokenAuthentication`.
- Управление токенами доступно в `/settings/integrations/`; полный ключ показывается один раз при создании.

### Near-term roadmap
1. Добавить отдельные inbound endpoints по типам интеграций.
2. Ввести журнал интеграционных вызовов.
3. Публиковать domain events как webhooks.
4. Разнести plugin-specific logic и generic integration contracts.

## Business Settings

Сейчас в `system_settings.SystemConfig` поддерживаются:
- `default_margin_percent` — используется при создании сделки/лида через `get_default_margin_percent()`
- `stale_deal_days` — сохраняется в UI, обработчиков пока нет
- `task_reminder_hours` — сохраняется в UI, обработчиков пока нет

Цель: параметры должны применяться ко всем новым процессам, а не зашиваться в form/view constants. Пока это верно только для маржи по умолчанию.

## File Library

- Модель: `deals.models.LibraryAsset` (секции layout/photo/video/contract_template/supplier_file).
- Хранение: `CRM_FILES_ROOT/library/...` через `ensure_library_dirs()`.
- Upload/download: `POST /files/upload/`, `GET /files/assets/<id>/download/` (login required).
- Browse UI: `/settings/library/` (leadership only).
