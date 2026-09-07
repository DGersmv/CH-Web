# Сервис / Рекламации

Отдельный контур обращений **после сдачи объекта**: гарантия, платная доработка, вопрос клиента.
Живёт вне воронки сделок (`Deal.status`). Привязка к сделке и клиенту необязательна.

Рабочий UI — пункт меню **Сервис** (`/service/`), не вкладка на карточке сделки.
Вкладка «Сервис / Рекламации» на `/deals/<id>/` сейчас заглушка («раздел в разработке») и к этой модели не подключена.

## Зачем

Менеджер заводит обращение по звонку / сообщению в группу и ведёт его до закрытия,
не смешивая с продажной воронкой. На главной (`/`) видны до 8 открытых обращений,
отсортированных по приоритету (срочно → высокий → обычный → низкий), затем по дате.

## Маршруты

| Метод | URL | Имя | Кто |
|---|---|---|---|
| GET | `/service/` | `service_list` | любой залогиненный |
| GET/POST | `/service/new/` | `service_create` | `can_edit_deals` |
| GET | `/service/<id>/` | `service_detail` | любой залогиненный |
| GET/POST | `/service/<id>/edit/` | `service_edit` | `can_edit_deals` |
| POST | `/service/<id>/status/` | `service_status_update` | `can_edit_deals` |
| POST | `/service/<id>/comment/` | `service_comment_add` | `can_edit_deals` |

Права: `accounts.permissions.can_edit_deals` — все активные роли, кроме `designer` и `production`.
Без права редактирования кнопки скрыты; POST редиректит на список/карточку без ошибки.

Предзаполнить сделку при создании: `/service/new/?deal=<id>`.

## Модель

`deals.models.ServiceRequest` — карточка. Номер `SR-<n>` выдаётся при первом `save()`:
`max(number) + 1`. Поле уникальное, в UI не редактируется.

`deals.models.ServiceRequestEvent` — журнал (комментарий / смена статуса / система).

| Поле | Значения | Примечание |
|---|---|---|
| `kind` | `reclamation` / `service` / `question` | по умолчанию `service` |
| `status` | `new` / `in_progress` / `waiting` / `done` / `rejected` | открытые: первые три (`OPEN_STATUSES`) |
| `priority` | `low` / `normal` / `high` / `urgent` | по умолчанию `normal` |
| `source` | `phone` / `telegram` / `email` / `portal` / `other` | только метка формы, автозаведения нет |
| `deal`, `client`, `assignee` | необязательные FK | если клиент пуст, а сделка есть — копируется `deal.client` |
| `resolution` | текст | пишется при закрытии / отклонении |
| `resolved_at` | datetime | ставится на `done`/`rejected`, сбрасывается при возврате в открытый статус |

Поиск списка (`?q=`) ищет по заголовку, описанию, имени/телефону заявителя,
`deal.project_code`, фамилии и компании клиента. **Номер `SR-n` в поиск не входит.**

Фильтры: `?status=open` (дефолт, если параметр не передан), `?status=` — все,
либо конкретный статус; `?kind=reclamation|service|question`.

Список без пагинации — отдаёт весь queryset.

## Жизненный цикл

1. Создание: форма → `created_by = request.user` → системное событие
   «Обращение заведено (…)» → audit `service_request.created`.
2. Редактирование полей (тип, приоритет, сделка, ответственный и т.д.) —
   **без** строки журнала и **без** domain event.
3. Комментарий — `ServiceRequestEvent.kind=comment`, трогает только `updated_at`.
   Domain event не пишется. Уведомление назначенному не создаётся.
4. Смена статуса — любое значение из enum в любое другое (валидации переходов нет).
   При `done`/`rejected` пишется `resolved_at` и опционально `resolution`.
   При возврате в открытый статус `resolved_at` обнуляется.
   Журнал: `старый → новый`. Audit: `service_request.status_changed`.

## События и главная

`service_request.created` и `service_request.status_changed` попадают в ленту
главной (`deals.services.activity_feed.FEED_EVENT_TYPES`).

Их **нет** в `system_settings.events.TOP_DOMAIN_EVENTS` (это список-roadmap,
не фильтр записи). Follow-up job не ставится (`enqueue_follow_up=False`).

Типы уведомлений (`Notification.Type`) — только `task_assigned` и `message_received`.
Назначение ответственного по обращению колокольчик не создаёт.

## Чего нет

- Вложений и связи с `ProjectFile`.
- Автосоздания из Telegram, портала клиента или умника: `source` — ручная метка.
- Связи вкладки сделки с `/service/` (нет списка обращений объекта на карточке).
- Проверки уникальности номера под concurrent create (два параллельных save
  могут столкнуться на `number`).
- Ограничения «только свои» — видят и правят все, у кого есть право редактировать сделки.

## Файлы

| Файл | Роль |
|---|---|
| `deals/models.py` | `ServiceRequest`, `ServiceRequestEvent` |
| `deals/forms.py` | `ServiceRequestForm`, `ServiceRequestCommentForm` |
| `deals/service_views.py` | список, создание, карточка, статус, комментарий |
| `deals/services/activity_feed.py` | лента главной |
| `core/views.py` | виджет открытых обращений на `/` |
| `templates/service_*.html`, `templates/home.html` | UI |
| `accounts/permissions.py` | `can_edit_deals` |

## Пример

Завести рекламацию по уже сданному дому:

1. **Сервис** → «Новое обращение» (или `/service/new/?deal=42`).
2. Тип `Рекламация (гарантия)`, приоритет `Высокий`, источник `Телефон`.
3. Суть: «Скрипит пол в спальне». Сделку выбрать, клиента можно не трогать —
   подтянется с объекта.
4. На карточке `SR-12` менять статус в «В работе» / «Ожидание» / «Закрыта».
   При закрытии заполнить поле «Итог».
