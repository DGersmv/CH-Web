# Collaboration API

Документ описывает интерфейсы сообщений и уведомлений, которые используются внутренними клиентами CRM.

Источник поведения:
- `core/urls.py`
- `core/api_views.py`
- `accounts/events.py`
- `accounts/consumers.py`
- `core/routing.py`

## Auth

REST endpoints используют DRF Token auth:

```http
Authorization: Token <token>
```

WebSocket использует обычную Django-сессию через `AuthMiddlewareStack`. Клиент должен быть залогинен в CRM и отправлять session cookie при подключении.

## REST: messages

### Список диалогов

```http
GET /api/messages/
```

Ответ:

```json
{
  "dialogs": [
    {
      "user": {"id": 2, "username": "manager", "full_name": "Ivan Manager"},
      "last_message": {
        "id": 10,
        "sender": {"id": 1, "username": "admin", "full_name": ""},
        "recipient": {"id": 2, "username": "manager", "full_name": "Ivan Manager"},
        "body": "Привет",
        "attachment_url": null,
        "attachment_name": null,
        "created_at": "2026-05-18T16:00:00+00:00",
        "read_at": null,
        "is_read": false
      },
      "unread_count": 1
    }
  ]
}
```

Ограничение: endpoint просматривает последние 500 сообщений пользователя и группирует их по собеседнику.

### Сообщения конкретного диалога

```http
GET /api/messages/?dialog_with=2
```

Ответ:

```json
{
  "dialog_with": {"id": 2, "username": "manager", "full_name": "Ivan Manager"},
  "items": []
}
```

Если пользователь не найден или неактивен, возвращается `404 {"detail": "User not found."}`.

### Отправить сообщение

```http
POST /api/messages/
Content-Type: multipart/form-data
```

Поля:

- `recipient_id` — обязательный id активного пользователя;
- `body` — текст сообщения;
- `attachment` — необязательный файл.

Нужно передать хотя бы `body` или `attachment`. Нельзя отправить сообщение самому себе.

Успех: `201 Created` и payload сообщения. Ошибки валидации возвращают `400` с `detail`.

### Отметить сообщение прочитанным

```http
POST /api/messages/<message_id>/read/
```

Доступно только получателю сообщения. Если сообщение найдено, выставляется `read_at`; связанное непрочитанное уведомление `message_received` по этому `DirectMessage` также помечается прочитанным.

## REST: notifications

### Список уведомлений

```http
GET /api/notifications/
```

Ответ содержит последние 50 уведомлений текущего пользователя:

```json
{
  "unread_count": 2,
  "items": [
    {
      "id": 15,
      "type": "task_assigned",
      "title": "Новая задача",
      "body": "Проверить план",
      "is_read": false,
      "read_at": null,
      "created_at": "2026-05-18T16:00:00+00:00",
      "actor": {"id": 1, "username": "admin", "full_name": ""},
      "related_model": "Task",
      "related_id": 44
    }
  ]
}
```

Текущие типы из модели:

- `task_assigned`
- `message_received`

### Отметить все уведомления прочитанными

```http
POST /api/notifications/read-all/
```

Ответ:

```json
{"updated": 2}
```

## WebSocket: user events

```text
ws://<host>/ws/events/
wss://<host>/ws/events/
```

Подключение принимается только для аутентифицированного пользователя. После подключения канал добавляется в группу `user_<id>_events`.

Сервер только отправляет события клиенту; входящие команды от клиента в consumer не обрабатываются.

### Event: notification.created

Создаётся через `accounts.events.create_notification(...)`.

```json
{
  "type": "notification.created",
  "notification": {
    "id": 15,
    "title": "Новая задача",
    "body": "Проверить план",
    "notification_type": "task_assigned",
    "created_at": "2026-05-18T16:00:00+00:00"
  }
}
```

### Event: message.created

Отправляется dashboard workflow после создания `DirectMessage`.

```json
{
  "type": "message.created",
  "message": {
    "id": 10,
    "sender_id": 1,
    "recipient_id": 2,
    "body": "Привет",
    "created_at": "2026-05-18T16:00:00+00:00"
  }
}
```

## Operational notes

- Redis обязателен для Channels backend (`REDIS_URL`, по умолчанию `redis://redis:6379/0` в Compose).
- Если WebSocket не подключается, сначала проверьте, что пользователь залогинен и cookie отправляется на тот же host/scheme.
- Если события не приходят при живом WebSocket, проверьте `docker compose logs redis --tail=80` и `docker compose logs app --tail=120`.
