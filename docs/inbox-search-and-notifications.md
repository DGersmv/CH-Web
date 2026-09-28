# Поиск, уведомления и личные сообщения

В CRM живут **три разных канала**, их легко перепутать:

| Канал | Где смотрит сотрудник | Хранение непрочитанного |
|-------|------------------------|-------------------------|
| Мессенджер комнат | `/app/` и `/rooms/` | `RoomMember.last_read_at` |
| Колокольчик «Уведомления» | шапка CRM и блок на Главной | таблица `Notification` |
| Личные `DirectMessage` | HTTP API `/api/messages/`; шаблон диалогов на Главной **не подключён** | `DirectMessage.read_at` |

Комнаты — рабочий чат сотрудников (включая Умника). Этот документ — про поиск в шапке, колокольчик и старый API личных сообщений.

## Поиск в шапке

Поле в навбаре (`templates/base.html`) ходит в `GET /search/global/` через HTMX: `keyup changed delay:250ms`. Ответ — HTML-фрагмент `templates/includes/global_search_results.html`, не JSON. Нужна сессия сотрудника (`@login_required`). Роль не фильтрует выдачу.

Пустой `q` возвращает пустой фрагмент (строки «Ничего не найдено» нет).

| Что ищется | Поля | Лимит | Куда ведёт клик |
|------------|------|-------|-----------------|
| Сделка | только `project_code` (`icontains`), новые сверху (`-updated_at`) | 5 | карточка сделки |
| Клиент | фамилия, имя, отчество, `company_name` | 5 | последняя сделка клиента (`-updated_at`) или карточка клиента, если сделок нет |

Итог обрезается до 10 строк. Телефон, код проекта у клиента, задачи, комнаты и файлы шапка **не** ищет.

Список сделок (`GET /deals/?q=`) — отдельный фильтр: код проекта, ФИО, компания **и телефон**. Модули в фильтре списка — только 3, 5, 7, 9, 11, это не ограничение глобального поиска.

Пример: запрос `Иванов` найдёт сделку, только если подстрока есть в `project_code`. Клиента «Иванов» без этой подстроки в коде шапка найдёт по фамилии и откроет его последнюю сделку.

## Уведомления

Модель `accounts.Notification`. Типы только два:

- `task_assigned` — «Новая задача»
- `message_received` — «Новое сообщение» (и личка, и комната)

Поля: `user` (кому), `actor` (кто, может быть пустым), `title`, `body`, `is_read`, `read_at`, `related_model`, `related_id`. Сортировка — новые сверху.

### Кто создаёт

Общая точка — `accounts.events.create_notification`. Она пишет строку и сразу шлёт в WebSocket событие `notification.created`.

| Событие | Где | `related_model` | Заметки |
|---------|-----|-----------------|---------|
| Задача на сделке | `tasks/views.py` `create_task_for_deal` | `Task` | Пишется и если исполнитель — сам автор |
| Сообщение в комнате | `rooms/services.py` `_notify_room` | `Room` | Фоновый поток. Получают участники-сотрудники, кроме автора. Ошибка записи глотается |
| `POST /dashboard/messages/send/` | `core/views.py` `dashboard_message_send` | `DirectMessage` | Плюс отдельное WS-событие `message.created` и аудит `message.sent` |
| `POST /api/messages/` | `core/api_views.py` | — | **Уведомление не создаёт** и в сокет ничего не шлёт |

Открытие комнаты (`mark_read`) двигает только `last_read_at`. Строки `Notification` от комнат остаются непрочитанными, пока их не закроют вручную.

### Где видно

- Бейдж в шапке: `navigation_context` считает все `is_read=False` текущего пользователя.
- Главная: последние **20** записей. Ссылка есть только у `task_assigned`: карточка сделки задачи, либо `/tasks/`, если сделки нет. `message_received` (комната и личка) на Главной **без ссылки**.
- `POST /dashboard/notifications/read-all/` помечает все свои непрочитанные и возвращает на Главную. `DirectMessage.read_at` и `RoomMember.last_read_at` при этом не меняются.

Оболочка PWA (`templates/rooms/app_base.html`) колокольчик не показывает. Бейдж вкладки «Чаты» — число **комнат** с `unread > 0`, не сумма сообщений и не таблица `Notification`.

### WebSocket

`ws://` или `wss://` + хост + `/ws/events/`. Сессия Django через `AuthMiddlewareStack` (`core/asgi.py`). Анонима сокет закрывает. Группа: `user_<id>_events`.

Скрипт в `templates/base.html` (на страницах CRM, не в `/app/`):

- `notification.created` — бейдж +1; если открыта Главная (`pathname === '/'`), страница перезагружается.
- `message.created` — перезагрузка только на Главной. Бейдж сам не растёт (его уже увеличил `notification.created`, если уведомление создали).
- `room.message.created` навбар игнорирует. Бейдж всё равно растёт, потому что комната параллельно вызывает `create_notification`.

Канал — Redis (`CHANNEL_LAYERS`, `REDIS_URL`). Если слой недоступен, `push_user_event` выходит сразу только когда `get_channel_layer()` вернул `None`. Ошибка `group_send` не ловится: задача и отправка с дашборда уже сохранены, но ответ клиенту будет 500. Комнаты эту ошибку глотают.

## API личных сообщений

DRF, только `TokenAuthentication`. Заголовок: `Authorization: Token <key>`.

Сессионная кука сотрудника эти URL **не** открывает. Токен интеграции из «Настроек» (`IntegrationToken`, заголовок `Token` или `Bearer`) тоже не подходит: он принимается на `POST /api/plugin/project-versions/`, не здесь. Ключ DRF — модель `rest_framework.authtoken.models.Token` (админка Django). Отдельной кнопки выдачи в CRM нет.

| Метод | URL | Поведение |
|-------|-----|-----------|
| `GET` | `/api/messages/` | Диалоги текущего пользователя по последним 500 сообщениям. У каждого: собеседник, последнее сообщение, `unread_count` (только внутри этих 500) |
| `GET` | `/api/messages/?dialog_with=<id>` | До 100 сообщений с этим активным пользователем, новые сверху. Несуществующий или неактивный id — `404` |
| `POST` | `/api/messages/` | `recipient_id` обязателен. Нужен непустой `body` и/или файл `attachment` (multipart). Самому себе — `400`. Неактивный получатель — `400`. Ответ `201` |
| `POST` | `/api/messages/<id>/read/` | Только получатель. Ставит `read_at` и закрывает связанное уведомление `message_received` / `DirectMessage` / этот id. Чужое или своё исходящее — `404` |
| `GET` | `/api/notifications/` | До 50 своих. Плюс `unread_count` по всей таблице, не только по этим 50 |
| `POST` | `/api/notifications/read-all/` | Закрывает все свои непрочитанные. Ответ `{"updated": N}` |

`dialog_with` не из цифр молча игнорируется: вернётся список диалогов, не 400.

Пример:

```bash
curl -s -H "Authorization: Token <key>" \
  http://localhost:8001/api/notifications/

curl -s -X POST -H "Authorization: Token <key>" \
  -F "recipient_id=2" -F "body=Проверь смету" \
  http://localhost:8001/api/messages/
```

Вложение `DirectMessage.attachment` лежит в `MEDIA_ROOT` (`media/direct_messages/`), не в `crm_files`. Django отдаёт `/media/` только при `DEBUG=True` (`core/urls.py`). Caddy проксирует всё, кроме `/static/`, на приложение, отдельного file_server для media нет. На проде с `DEBUG=False` ссылка из API (`attachment_url`) не откроется, пока `/media/` не начнут раздавать отдельно.

`POST /dashboard/messages/send/` пишет ту же модель и **создаёт** уведомление, но форма `templates/includes/dashboard_messages_block.html` нигде не включена: `home()` не собирает `dialogs`. Поле `body` у `DashboardMessageForm` обязательное, хотя `clean()` допускает файл без текста — пустой текст форма не пропустит. API файл без текста принимает.

## Ограничения

- Типов уведомлений два. Смена статуса сделки, кабинет заказчика и сервис в колокольчик не пишут. Лента на Главной (`deals/services/activity_feed.py`) — отдельный журнал, не `Notification`.
- Прочтение комнаты не гасит колокольчик. Прочтение всех уведомлений не гасит бейдж чатов в `/app/`.
- `POST /api/messages/` не будит получателя ни колокольчиком, ни сокетом.
- Поиск шапки не совпадает с поиском списка сделок.
- У `Notification` нет ссылки на комнату: `related_id` — id комнаты, но Главная строит `target_url` только для задач.

## Куда смотреть

| Тема | Путь |
|------|------|
| Поиск и отметка уведомлений в UI | `core/views.py` (`global_search`, `notifications_mark_all_read`, `dashboard_message_send`) |
| JSON API | `core/api_views.py`, маршруты в `core/urls.py` |
| Модели | `accounts/models.py` (`DirectMessage`, `Notification`) |
| Создание и сокет | `accounts/events.py`, `accounts/consumers.py`, `core/routing.py` |
| Бейдж и WS в шапке | `core/context_processors.py`, `templates/base.html` |
| Задача → уведомление | `tasks/views.py` |
| Комната → уведомление | `rooms/services.py` (`_notify_room`, `unread_count`, `mark_read`) |
