# CH-CRM Platform Blueprint

## Domain vs Platform

### Domain modules
- `deals`: сделки, версии проекта, клиентский портал, файлы проекта, сметы, конфигуратор.
- `clients`: карточки клиентов и клиентские данные.
- `catalog`: справочник расчётных позиций и опций.
- `tasks`: задачи по сделкам и внутренние вложения.

Операционный цикл сделки (лиды с дашборда, `project_code`, claim,
`Deal.status`, вкладки этапов) описан в
[deal-lifecycle.md](deal-lifecycle.md).

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

Это intentionally small queue layer на базе БД. Следующий шаг, если нагрузка вырастет, — вынести worker в отдельный процесс/сервис.

## Integration Surface

### Current state
- Endpoint: `POST /api/plugin/project-versions/`
- Поддерживается аутентификация через `IntegrationTokenAuthentication` и DRF tokens.
- Управление токенами доступно в `/settings/integrations/`.

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
