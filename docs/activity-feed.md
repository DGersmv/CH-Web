# Лента событий на Главной

Лента «что происходит» на `/` — общий журнал для сотрудников, которые ведут сделки. Это не личные уведомления и не список на странице интеграций.

Строки читаются из `accounts.AuditEvent`. Пишет их `system_settings.events.record_domain_event()` (тонкая обёртка над `accounts.events.log_audit_event`). Отдельной очереди, вебхука и фильтра «только мои сделки» нет.

## Где это на экране

`home()` в `core/views.py` собирает ленту для любого вошедшего пользователя, но шаблон `templates/home.html` рисует её только если роль не файловая (`designer` и `production`). У этих ролей на Главной остаётся блок «Режим проектных файлов» и личные уведомления сверху. Самой ленты они не видят.

Ленту видят все остальные роли. Состав один и тот же: последние события по всей CRM, не по назначенному менеджеру. Проверка в шаблоне — `is_file_only_role`, не «руководитель».

Над лентой — личные `Notification` (до 20). Это другой механизм: типы только `task_assigned` и `message_received`, получатель один. Лента их не дублирует.

Рядом, тем же `home()`, но не из `AuditEvent`:

| Блок | Откуда | Правило |
|---|---|---|
| Сделок в работе | `Deal` | статусы `new`, `qualified`, `sent_quote`, `contract`, `prepayment`, `production`, `installation`. `orphan`, `delivered`, `lost` не входят |
| Задач сегодня / просрочено | `Task` | только задачи текущего пользователя, `is_done=False`, `due_date` ≤ сегодня |
| Открытых обращений | `ServiceRequest` | статусы `new`, `in_progress`, `waiting`. Счётчик — все, карточка справа — первые 8 (срочные выше, затем новее) |
| Новые лиды | `Deal` | статусы `orphan` и `new`, без лимита, новее сверху |

## Как собирается строка

`build_activity_feed(limit=25)` берёт `AuditEvent` с `event_type` из `FEED_EVENT_TYPES`, сортировка `-created_at`, срез `limit`. Главная вызывает её с `limit=30`. Других вызовов нет.

Дальше для пачки один запрос кодов сделок. Код берётся так:

1. `payload.deal_id`, иначе `entity_id`, если `entity_model == 'Deal'`;
2. живая сделка с этим id → `project_code`;
3. иначе `payload.project_code`;
4. иначе пустая строка.

Автор в подписи — `actor.username`. Если актор уже удалён (`SET_NULL`), подпись «система». Время — `created_at` в `TIME_ZONE` проекта, сейчас `UTC`, формат `d.m.Y H:i`. IP и User-Agent в строку не попадают; модели `AuditEvent` нет в Django admin.

Ссылка: карточка сделки `/deals/<id>/`. Для сервисных событий — `/service/<id>/` (id обращения, не номер `SR-`). Для `deal.deleted` ссылка принудительно пустая.

Пример строки смены статуса, пока сделка жива:

```text
➡️  3МД-Иванов-Пулково: статус New → Qualified
    manager1 · 09.11.2026 16:04
```

Подписи статусов сделки — английские ярлыки `Deal.Status` (`New`, `Sent quote`, …), не русские названия вкладок. Статусы сервиса русские: `Новая`, `В работе`, `Ожидание (клиент / поставщик)`, `Закрыта`, `Отклонена`.

## Что попадает в ленту

| Событие | Кто пишет | Текст | Ссылка |
|---|---|---|---|
| `deal.created` | `POST /dashboard/leads/create/` | `Новый лид: {код}` | сделка |
| `deal.status_changed` | `POST /deals/<id>/status/`, только если статус реально сменился | `{код}: статус {старый} → {новый}` | сделка |
| `deal.approvals_passed` | `POST /deals/<id>/approvals/stage/`, действие не `reopen` | `{код}: согласования пройдены` | сделка |
| `deal.design_passed` | `POST /deals/<id>/design/stage/`, действие не `reopen` | `{код}: проектирование завершено` | сделка |
| `project_version.imported` | `POST /api/plugin/project-versions/` | `{код}: пришла версия из ArchiCAD` | сделка |
| `project_file.uploaded` | `POST /files/upload/` — файл библиотеки (`LibraryAsset`), не файл сделки. Вход достаточен, отдельной проверки роли нет | `загружен файл «{original_name}»` | нет |
| `task.created` | `POST /deals/<id>/tasks/new/` | `{код}: задача «{title}»` | сделка |
| `task.completed` | `POST /tasks/<id>/toggle/`, только первый переход в «сделано» | `{код}: задача выполнена` | сделка, если у задачи есть `deal_id` |
| `client_message.sent` | три POST сотрудника: `/deals/<id>/client-messages/send/`, `.../attach-existing/`, `.../upload/` | `{код}: сообщение клиенту` | сделка |
| `service_request.created` | `POST /service/new/` | `Сервис SR-{number}: {title}` | карточка обращения |
| `service_request.status_changed` | `POST /service/<id>/status/`, только если статус сменился | `Сервис SR-{number}: {старый} → {новый}` | карточка обращения |
| `deal.deleted` | удаление сделки умником, только `can_delete_deals` (admin, superadmin или Django superuser) | `Удалена сделка {код из payload}` | нет |

Повтор того же статуса сделки или обращения событие не пишет. Закрытие согласований без пройденного гейта или без принятой версии отвечает 400 и строку не пишет; для проектирования 400, если гейт не пройден. Файловые роли получают 403 на смену статуса, лид, согласования, проектирование и сообщение клиенту — этих строк от них нет. Создать и сменить статус обращения может тот, у кого `can_edit_deals` (все активные, кроме `designer` / `production`); остальным форма редиректит на список, без 403. Задачу создать и закрыть может любой вошедший, не только исполнитель и не только нефайловая роль. В текст «задача выполнена» заголовок не подставляется.

`kind` у сообщения клиенту (`text`, `project_file`, `voice`, `uploaded_file`) в payload есть, в текст ленты не входит. Номер принятой версии (`accepted_version`) в `deal.approvals_passed` тоже только в payload.

## Пишется в AuditEvent, в ленту не входит

Эти типы создаются через `record_domain_event` или `log_audit_event`, но их нет в `FEED_EVENT_TYPES`:

- пункт согласования: `deal.approval_changed`, `deal.approval_item_added`, `deal.approval_item_removed`, `deal.approval_file_added`, `deal.approvals_reopened`;
- раздел проектирования: `deal.design_section_changed`, `deal.design_section_added`, `deal.design_section_removed`, `deal.design_file_added`, `deal.design_reopened`;
- `deal.electrical_updated`, `project_version.status_changed` (кнопки статуса версии, включая «отправить клиенту»);
- `message.sent` — личное сообщение с Главной (`log_audit_event`, не лента);
- `crm.restart_requested` — перезапуск от владельца системы.

`enqueue_follow_up` у `record_domain_event` ни один вызов не передаёт. Запись в ленту сама по себе задачу `PlatformJob` не ставит.

Кортеж `TOP_DOMAIN_EVENTS` (`deal.status_changed`, `project_version.imported`, `project_file.uploaded`, `task.created`, `client_message.sent`) — подпись на `/settings/integrations/` («Поддерживаются события»). Это не фильтр ленты и не список того, что умеет плагин. Плагин пишет только `project_version.imported`.

## Чего в журнале нет совсем

Действие меняет CRM, но `AuditEvent` этого типа не создаётся:

- сделка с формы `/deals/new/` (`DealCreateView`) — не `deal.created`. В ленте «Новый лид» есть только лид с модалки Главной;
- смена статуса, кода, маржи и менеджера через умника (`update_deal`) — ChangeLog есть, `deal.status_changed` нет;
- плагин, создавший сделку со статусом `orphan`, пишет только «пришла версия из ArchiCAD». Отдельной строки «Новый лид» нет. Такая сделка видна в блоке «Новые лиды»;
- файл на карточке сделки (`upload_project_file`), PDF плагина, файл согласования и файл раздела — не `project_file.uploaded`. Этот тип сейчас означает файл библиотеки (`LibraryAsset`): в payload секция и имя, `deal_id` нет, ссылки нет;
- сообщение и файл из кабинета заказчика — `DealClientMessage` создаётся, `client_message.sent` нет;
- комментарий к обращению и правка карточки обращения без смены статуса;
- открытие уже выполненной задачи обратно не реализовано, повторного `task.completed` нет.

После удаления сделки код в старых строках остаётся только если он был в payload: `deal.created` и `project_version.imported`. У `deal.status_changed`, `deal.approvals_passed` и `deal.design_passed` кода в payload нет, а сделка уже не находится, поэтому текст начинается с двоеточия: `: статус New → Qualified`, `: согласования пройдены`. У задач и `client_message.sent` префикс с кодом в этом случае не пишется (`задача выполнена`, `сообщение клиенту`). Ссылка на `/deals/<id>/` при этом остаётся и ведёт на уже удалённую сделку. У строки `deal.deleted` ссылки нет, код берётся из её payload. Сервисные строки от удаления сделки не зависят: номер и заголовок лежат в payload, ссылка идёт на обращение.

## Куда смотреть в коде

| Файл | Роль |
|---|---|
| `deals/services/activity_feed.py` | фильтр типов, тексты, иконки, ссылки |
| `core/views.py` `home` | лимит 30 и соседние блоки Главной |
| `templates/home.html` | скрытие ленты для файловых ролей |
| `system_settings/events.py` | `record_domain_event`, `TOP_DOMAIN_EVENTS` |
| `accounts/models.py` `AuditEvent` | хранение |
| `accounts/events.py` `log_audit_event` | запись, IP и User-Agent из `request` |
