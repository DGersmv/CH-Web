# Collaboration Events and Notifications

Этот документ описывает текущую реализацию внутренних сообщений, уведомлений,
аудита и realtime-доставки. Источник правды по коду:
`accounts/models.py`, `accounts/events.py`, `accounts/consumers.py`,
`core/api_views.py`, `core/views.py`, `tasks/views.py`, `core/asgi.py`.

## Назначение

Подсистема нужна, чтобы сотрудники видели рабочие события без ручного
обновления страницы:

- личные сообщения между пользователями;
- уведомления о новых сообщениях и назначенных задачах;
- аудит действий, важных для расследования проблем;
- WebSocket-сигналы для обновления бейджа уведомлений и dashboard.

## Модель данных

| Модель | Что хранит | Важные поля |
| --- | --- | --- |
| `DirectMessage` | Личное сообщение между двумя пользователями | `sender`, `recipient`, `body`, `attachment`, `created_at`, `read_at` |
| `Notification` | Уведомление для одного пользователя | `user`, `actor`, `notification_type`, `title`, `body`, `is_read`, `related_model`, `related_id` |
| `AuditEvent` | Журнал бизнес-событий | `actor`, `event_type`, `entity_model`, `entity_id`, `payload`, `ip_address`, `user_agent` |

Поддерживаемые типы уведомлений сейчас ограничены
`task_assigned` и `message_received`.

## Потоки событий

### Сообщение с dashboard

Форма на главной странице (`dashboard_message_send`) делает полный цикл:

1. Создаёт `DirectMessage`.
2. Создаёт `Notification` типа `message_received` для получателя.
3. Через `create_notification(...)` отправляет WebSocket-событие
   `notification.created`.
4. Дополнительно отправляет WebSocket-событие `message.created`.
5. Пишет `AuditEvent` с `event_type = message.sent`.
6. Возвращает пользователя на `/?dialog_with=<recipient_id>`.

Открытие диалога на dashboard помечает входящие сообщения этого диалога как
прочитанные и закрывает связанные непрочитанные уведомления
`message_received`.

### Назначение задачи

`create_task_for_deal` в `tasks/views.py`:

1. Создаёт `Task` для сделки.
2. Если указан исполнитель, создаёт уведомление `task_assigned`.
3. Через `create_notification(...)` отправляет `notification.created`.
4. Пишет аудит `task.created`.
5. Возвращает HTMX-фрагмент списка задач и заголовок
   `HX-Trigger: taskCreated`.

`toggle_task` помечает задачу выполненной и пишет аудит `task.completed`.
Отдельное уведомление о завершении задачи сейчас не создаётся.

## REST API

Все API ниже явно используют DRF Token Auth:
`Authorization: Token <token>`.

### `GET /api/messages/`

Возвращает список диалогов текущего пользователя по последним 500 сообщениям.

```json
{
  "dialogs": [
    {
      "user": {"id": 2, "username": "manager2", "full_name": "Ivan Petrov"},
      "last_message": {
        "id": 10,
        "body": "Проверьте файл",
        "attachment_url": null,
        "created_at": "2026-07-13T12:00:00+00:00",
        "read_at": null,
        "is_read": false
      },
      "unread_count": 1
    }
  ]
}
```

### `GET /api/messages/?dialog_with=<user_id>`

Возвращает до 100 последних сообщений в диалоге с активным пользователем.
Если пользователь не найден, вернётся `404`.

### `POST /api/messages/`

Создаёт сообщение через API.

Поля:

- `recipient_id` — обязательный id активного пользователя;
- `body` — текст сообщения;
- `attachment` — файл;
- нужно передать хотя бы `body` или `attachment`;
- отправка самому себе запрещена.

Важно: текущая API-ветка только создаёт `DirectMessage` и возвращает payload.
Она не создаёт `Notification`, не пишет `AuditEvent` и не отправляет
WebSocket-события. Для полного realtime-цикла сейчас используется dashboard
форма `dashboard_message_send`.

### `POST /api/messages/<message_id>/read/`

Доступно только получателю сообщения. Проставляет `read_at` у сообщения и
помечает связанные непрочитанные уведомления `message_received` как
прочитанные.

### `GET /api/notifications/`

Возвращает последние 50 уведомлений текущего пользователя и общий счётчик
непрочитанных.

### `POST /api/notifications/read-all/`

Помечает все непрочитанные уведомления текущего пользователя как прочитанные и
возвращает количество обновлённых строк.

## WebSocket-доставка

Endpoint: `ws://<host>/ws/events/` или `wss://<host>/ws/events/`.

Аутентификация идёт через обычную Django-сессию браузера
(`AuthMiddlewareStack`). DRF token для WebSocket сейчас не используется.
Неаутентифицированное подключение закрывается.

Каждый пользователь подписывается на группу:

```text
user_<user.id>_events
```

Текущие payload:

```json
{
  "type": "notification.created",
  "notification": {
    "id": 15,
    "title": "Новая задача",
    "body": "Позвонить клиенту",
    "notification_type": "task_assigned",
    "created_at": "2026-07-13T12:00:00+00:00"
  }
}
```

```json
{
  "type": "message.created",
  "message": {
    "id": 10,
    "sender_id": 1,
    "recipient_id": 2,
    "body": "Проверьте файл",
    "created_at": "2026-07-13T12:00:00+00:00"
  }
}
```

`templates/base.html` открывает WebSocket для авторизованных пользователей.
При `notification.created` бейдж уведомлений увеличивается на 1; если
пользователь находится на dashboard (`/`), страница перезагружается. При
`message.created` dashboard тоже перезагружается.

## Операционные зависимости

- `CHANNEL_LAYERS` использует `channels_redis` и `REDIS_URL`
  (по умолчанию `redis://redis:6379/0`).
- `docker-compose.yml` запускает отдельный сервис `redis:7`.
- Контейнер `app` стартует через Daphne:
  `daphne -b 0.0.0.0 -p 8000 core.asgi:application`.
- HTTP и WebSocket маршруты собираются в `core/asgi.py`.

Если Redis или Daphne недоступны, записи `Notification` и `DirectMessage`
могут создаваться в БД, но realtime-бейдж и автообновление dashboard работать
не будут.

## Проверка и troubleshooting

Быстрая проверка контейнеров:

```bash
docker compose ps
docker compose logs app --tail=120
docker compose logs redis --tail=120
```

Проверка из браузера:

1. Войти двумя пользователями в разных браузерах или профилях.
2. Открыть DevTools -> Network -> WS и убедиться, что `/ws/events/`
   подключён без `403`/закрытия сразу после connect.
3. Отправить сообщение через dashboard.
4. У получателя должен увеличиться бейдж уведомлений; если он на dashboard,
   страница перезагрузится.

Проверка данных:

```bash
docker compose exec app python manage.py shell
```

```python
from accounts.models import DirectMessage, Notification, AuditEvent

DirectMessage.objects.order_by("-created_at").first()
Notification.objects.filter(is_read=False).count()
AuditEvent.objects.order_by("-created_at").values("event_type", "entity_model").first()
```

Частые причины проблем:

- нет активной Django-сессии в браузере для WebSocket;
- приложение запущено не через Daphne/ASGI;
- Redis недоступен или `REDIS_URL` указывает не туда;
- REST-запросы к `/api/messages/` выполнены без DRF token;
- сообщение отправлено через REST API, поэтому уведомление и WebSocket-событие
  не создались.
