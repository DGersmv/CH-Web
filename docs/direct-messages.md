# Личные сообщения сотрудников (`DirectMessage`)

Это старый канал «сотрудник → сотрудник». Он не связан со сделкой и не заменяет живой мессенджер.

| Канал | Модель | Где в интерфейсе |
|-------|--------|------------------|
| Личные сообщения | `accounts.DirectMessage` | Форма есть, на Главную не подключена. Рабочий вход — `POST /dashboard/messages/send/` и `/api/messages/` |
| Комнаты | `rooms.RoomMessage` | `/app/` и `/rooms/` |
| Сообщения по сделке / кабинету | `deals.DealClientMessage` | Карточка сделки и кабинет заказчика |

Получатель — любой **активный** пользователь, кроме отправителя. Роль не проверяется: писать может и проектировщик, и производство. `superadmin` из выборки не исключается (`staff_users_qs` здесь не вызывается).

## Маршруты

| Метод | Путь | Кто | Что делает |
|-------|------|-----|------------|
| `POST` | `/dashboard/messages/send/` | Сессия сотрудника, CSRF | Письмо + уведомление + WebSocket + `AuditEvent` |
| `GET` | `/api/messages/` | Только DRF Token | Список диалогов или лента одного диалога |
| `POST` | `/api/messages/` | Только DRF Token | Создаёт письмо. Уведомление, сокет и аудит **не** пишет |
| `POST` | `/api/messages/<id>/read/` | Только DRF Token, и только получатель | Ставит `read_at` и закрывает связанное уведомление |

Сессионная кука и `IntegrationToken` на `/api/messages/` не принимаются: у вьюх стоит один `TokenAuthentication`. Токен — запись `rest_framework.authtoken.models.Token` (`Authorization: Token <key>`).

## Форма на Главной не показана

Шаблон `templates/includes/dashboard_messages_block.html` нигде не подключается. `home()` не кладёт в контекст `dialogs`, `dialog_user`, `dialog_messages`, `message_form`. Сотрудник на `/` видит уведомления и ленту событий, но не переписку.

`DashboardMessageForm` при этом живой:

- `recipient` — активные пользователи, кроме текущего; подпись — ФИО, иначе `username`.
- `body` — обязательное поле (`CharField` без `required=False`).
- `attachment` — необязательный файл.
- `clean()` готов принять текст **или** файл, но до него дело не доходит, если текст пустой: обязательное поле отсекает запрос раньше.

Невалидный `POST` делает `redirect('home')` без `messages` и без `?dialog_with=`. Ошибка в интерфейсе не появляется. Успех тоже уходит на `/` без открытого диалога.

Пример, который сохраняется (сессия и CSRF уже есть):

```bash
curl -s -o /dev/null -w "%{http_code}\n" \
  -b "sessionid=<session>" \
  -F "csrfmiddlewaretoken=<csrf>" \
  -F "recipient=12" \
  -F "body=Нужен чертёж к пятнице" \
  http://localhost:8001/dashboard/messages/send/
```

Ответ — `302` на `/`. В базе появляется строка `DirectMessage`, уведомление и аудит.

Пробелы в тексте плюс файл проходят проверку поля: в базу уходит пустой `body` и вложение. Файл без текста — `302` на `/` и ничего не создаётся.

## Что пишет сессионная отправка

Вьюха `dashboard_message_send` после успешной формы:

1. `DirectMessage.objects.create(...)`.
2. `create_notification` получателю: тип `message_received`, заголовок «Новое сообщение», `related_model='DirectMessage'`. Текст уведомления — тело письма или `Файл: <имя>`.
3. В сокет получателя (`user_<id>_events`) уходит `notification.created`, затем отдельно `message.created` (id, sender, recipient, body, created_at — без вложения).
4. `AuditEvent` с типом `message.sent`, payload `{recipient_id, has_attachment}`. IP и User-Agent берутся из запроса.

Общей транзакции нет. Если Redis недоступен, `group_send` падает уже после insert письма и уведомления: клиент видит 500, `AuditEvent` может не появиться, повторный `POST` создаёт второе письмо.

`message.sent` не входит в `FEED_EVENT_TYPES`, поэтому лента на Главной такие письма не показывает. Событие пишется через `log_audit_event`, не через `record_domain_event`.

## Уведомление не ведёт в диалог

Блок «Уведомления» на Главной — последние 20 строк текущего пользователя. Ссылка строится только для `task_assigned`. У `message_received` поле `target_url` пустое: заголовок «Новое сообщение», автор — `username`, текст рядом.

Бейдж в навбаре считает непрочитанные `Notification`, не `DirectMessage.read_at`.

«Отметить все прочитанными» (`POST /dashboard/notifications/read-all/`) ставит `Notification.is_read` и `read_at`. `DirectMessage.read_at` не трогает.

Сокет подключён в `templates/base.html` к `/ws/events/` (сессия, `AuthMiddlewareStack`). На `/` событие `notification.created` увеличивает бейдж и перезагружает страницу; `message.created` тоже перезагружает `/`. Оболочка `/app/` этот скрипт не грузит: пока человек в PWA, бейдж личных сообщений не обновляется.

Прочтение одного письма есть только в API. Оно закрывает уведомление с тем же `related_id`, если тип `message_received`, модель `DirectMessage` и `is_read=False`.

## HTTP API

Список диалогов — последние 500 писем, где пользователь отправитель или получатель. На каждого собеседника остаётся самое новое письмо и счётчик непрочитанных **внутри этих 500**. Более старые непрочитанные в счётчик не попадают. Неактивный собеседник в списке остаётся.

```bash
curl -s -H "Authorization: Token <drf-token>" \
  http://localhost:8001/api/messages/
```

```json
{
  "dialogs": [
    {
      "user": {"id": 12, "username": "ivan", "full_name": "Иван Петров"},
      "last_message": {"id": 34, "body": "Нужен чертёж", "is_read": false},
      "unread_count": 1
    }
  ]
}
```

Лента одного диалога — 100 последних писем, новые сверху. `dialog_with` учитывается только если это цифры. Неактивный или неизвестный id даёт `404` и `{"detail": "User not found."}`.

```bash
curl -s -H "Authorization: Token <drf-token>" \
  "http://localhost:8001/api/messages/?dialog_with=12"
```

Создание. Нужны `recipient_id` и непустой `body` **или** файл `attachment`. Себе писать нельзя (`400`, `Cannot send message to yourself.`). Неактивный получатель — `400`, `Recipient not found or inactive.`

```bash
curl -s -H "Authorization: Token <drf-token>" \
  -F "recipient_id=12" \
  -F "body=Нужен чертёж к пятнице" \
  http://localhost:8001/api/messages/
```

Ответ `201` — одно письмо:

```json
{
  "id": 34,
  "sender": {"id": 3, "username": "maria", "full_name": "Мария Соколова"},
  "recipient": {"id": 12, "username": "ivan", "full_name": "Иван Петров"},
  "body": "Нужен чертёж к пятнице",
  "attachment_url": null,
  "attachment_name": null,
  "created_at": "2026-11-16T16:05:00+00:00",
  "read_at": null,
  "is_read": false
}
```

API не вызывает `create_notification`, `push_user_event` и `log_audit_event`. Письмо, отправленное токеном, не зажигает бейдж и не попадает в аудит.

Прочтение. Чужое письмо и письмо, где текущий пользователь только отправитель, — `404` `Message not found.` Повторный вызов не двигает уже стоящий `read_at`.

```bash
curl -s -X POST -H "Authorization: Token <drf-token>" \
  http://localhost:8001/api/messages/34/read/
```

Тестов на эти вьюхи нет.

## Файлы

Вложение — `FileField(upload_to='direct_messages/')`. Каталог `MEDIA_ROOT`, то есть `<корень репозитория>/media/direct_messages/`. В compose корень смонтирован в `/app`, файл оказывается в `/app/media/direct_messages/`. Это не `CRM_FILES_ROOT` и не `crm_files/`.

Ссылка в API и в шаблоне — `attachment.url` (`/media/direct_messages/<имя>`). Раздача `/media/` включается только при `DEBUG=True` (`core/urls.py`). В `.env.example` стоит `DEBUG=False`. Caddy отдельно отдаёт лишь `/static/` и остальное проксирует в Daphne, так что при выключенном DEBUG ссылка на файл отвечает 404, хотя файл на диске есть.

Отдельного лимита размера и проверки типа для этого поля нет. `body` в модели — `TextField` без `blank=True`, но API пишет через `objects.create` и пустой текст вместе с файлом сохраняет.

Удаление пользователя каскадом удаляет его входящие и исходящие письма.

В Django admin список `DirectMessage` есть (превью текста, флаг вложения, фильтр по дате и прочтению). Автодополнение пользователей идёт через `UserAdmin`, а тот скрывает роль `superadmin`.

## Если поведение не сходится с ожиданием

- На Главной нет блока «Сообщения» — шаблон не включён, это текущее состояние, не сломанный include.
- `POST /dashboard/messages/send/` всегда возвращает на `/` и молчит, когда форма невалидна (пустой текст, свой id, неактивный получатель).
- Файл без текста через форму не сохраняется. Через API — сохраняется, и уведомления при этом нет.
- Бейдж вырос, а открыть диалог некуда: у `message_received` нет `target_url`, экран диалога не рендерится.
- «Прочитать все» погасило бейдж, а `GET /api/messages/` всё ещё считает письмо непрочитанным — это разные поля.
- `401` на `/api/messages/` с кукой или токеном из «Интеграций» — нужен DRF Token.
- Ссылка на вложение 404 при `DEBUG=False` — файл лежит в `media/direct_messages/`, HTTP его не отдаёт.
- В ленте Главной письма нет — тип аудита `message.sent` в ленту не входит.
- `500` при живой базе и мёртвом Redis — сессионная отправка уже записала письмо и упала на `group_send`.
