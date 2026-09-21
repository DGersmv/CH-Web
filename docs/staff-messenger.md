# Мессенджер сотрудников (комнаты)

Внутренний чат сотрудников: личные и групповые беседы, вложения, голосовые и Умник в чате. Это **не** чат на карточке сделки (`/umnik/chats/`), не кабинет заказчика и не Telegram-диспетчерская.

## Зачем

- С телефона — PWA «как приложение» (`/app/`), без CRM-навигации.
- С компьютера — пункт **Комнаты** (`/rooms/`) внутри обычного навбара.
- Один код, два URL-пространства: одни и те же views, разные шаблоны.

## Два входа, один код

| Оболочка | Префикс | Namespace | Шаблон |
|----------|---------|-----------|--------|
| PWA / телефон | `/app/` | `app` | `templates/rooms/app_base.html` |
| CRM | `/rooms/` | `rooms` | `templates/base.html` |

Какой шаблон взять, решает `core/context_processors.py`: путь `/app/…` → `app_shell=True`, `rooms_ns='app'`. URL в JSON (отправка, опрос, файлы) строятся через тот же namespace, чтобы PWA не уводила в CRM-навигацию.

Манифест и «service worker» живут на корне, не в include:

- `GET /app/manifest.webmanifest` — standalone, scope `/app/`, иконка `/static/img/apple-touch-icon.png`
- `GET /app/sw.js` — **снимает** регистрацию (`unregister` на `activate`). Офлайн-кэш специально не делали: ломал iPhone.

## Как попасть в `/app/`

1. **Логин с телефона.** `StaffLoginView` смотрит `User-Agent`. Если есть `iPhone` / `iPad` / `Android` / `Mobile` и нет `next=`, редирект на `/app/` (`LOGIN_REDIRECT_URL` для десктопа остаётся `/`).
2. **Уже установленный PWA.** Если `display-mode: standalone` (или iOS `navigator.standalone`) и путь `/`, `templates/base.html` делает `location.replace('/app/')`.
3. Настройки PWA → «На экран Домой» (`/app/install/`). Инструкция: Safari на iPhone, Chrome на Android, нужен HTTPS.

Пункт CRM «Комнаты» всегда ведёт на `/rooms/`, даже с телефона.

## Модель

```
Room
  title, status (open|archived), deal (nullable), livekit_room_name (заготовка)
RoomMember
  kind: user | umnik
  role: host | member
  last_read_at
RoomMessage
  author_kind: user | umnik | system
  kind: text | file | voice_note | system | umnik
RoomMessageAttachment
  relative_path относительно CRM_FILES_ROOT
```

Ограничения в БД:

- один user-участник на комнату (`rooms_member_unique_user`);
- не больше одного Умника на комнату (`rooms_member_unique_umnik`).

Список контактов — `staff_users_qs`: активные сотрудники **без** роли `superadmin`. Самого себя в личный чат открыть нельзя (`/with/<id>/` редиректит на контакты).

Повторный набор тех же людей (+ флаг Умника) **не создаёт** новую комнату: `get_or_create_room` ищет точное совпадение участников среди `status=open`.

Чужак, который не в `RoomMember`, получает **404**, не 403.

`Room.status=archived` и `livekit_room_name` в UI не используются. Вкладка «Звонки» — заглушка (`templates/rooms/calls.html`).

## Связь со сделкой (важно)

У `Room` есть FK `deal`. Фильтр чатов **Клиенты** = «есть `deal_id`», **Рабочая** = «сделки нет».

Создание комнаты из UI (`/new/`, `/with/<user>/`, `/with/umnik/`) **поле `deal` не заполняет**. Папка «Клиенты» будет пустой, пока сделку не проставят вручную (admin) или пока этого не сделает будущий код. Умнику в комнате `deal_id`/`deal_code` уходят пустыми, пока FK пустой.

Это отдельный канал от виджета Умника на карточке сделки (`UmnikChatThread`).

## Маршруты

Префикс ниже — `/rooms/` или `/app/`.

| Метод | Путь | Что делает |
|-------|------|------------|
| GET | `/` | список чатов, `?folder=all\|new\|work\|clients` |
| GET/POST | `/new/` | новая беседа: `user_ids` + опционально `with_umnik` |
| GET | `/contacts/` | коллеги; отдельная строка «Умник» |
| GET | `/calls/` | заглушка звонков |
| GET | `/settings/` | имя, выход, ссылка в CRM, установка на Домой |
| GET | `/with/umnik/` | личный чат только с Умником |
| GET | `/with/<user_id>/` | личный чат с коллегой |
| GET | `/install/` | инструкция PWA |
| GET | `/<id>/` | лента; помечает прочитанным |
| GET | `/<id>/messages/?after=<id>` | JSON `{items: [...]}` — новые сообщения |
| POST | `/<id>/send/` | текст и/или файлы (`files` или `file`) |
| POST | `/<id>/umnik/` | `action=add\|remove` |
| GET | `/<id>/files/<att_id>/` | файл inline (`FileResponse`, не `as_attachment`) |

Все, кроме манифеста/SW, требуют логин.

## Отправка и Умник

`rooms.services.post_message`:

1. Пустой текст **и** нет файлов → `ValueError('empty')` → HTTP 400 `{ok:false,error:"empty"}`.
2. Только аудио (mime `audio/*` или `.ogg/.webm/.m4a/.mp3/.wav/.aac`) без текста → `kind=voice_note`.
3. Файлы без текста → `kind=file`, иначе `text`.
4. Файлы пишутся в `{CRM_FILES_ROOT}/rooms/<room_id>/<YYYYMMDD_HHMMSS>__<имя>`.
5. Если заголовок комнаты пустой / «Умник» / «Чат», берётся первые 72 символа текста.
6. Соседям в фоне: Channels `room.message.created` и `Notification` типа `message_received`. PWA **не** слушает `/ws/events/` (сокет есть только в `templates/base.html`) — лента в `/app/` живёт опросом.
7. Нужно ли звать Умника — `should_ask_umnik` **и** `can_use_umnik_chat` (любой активный вошедший пользователь):

| Ситуация | Звать Умника? |
|----------|----------------|
| Умника нет в комнате | нет |
| Голосовое (`voice_note`) | да |
| Чат «только я + Умник» | каждое сообщение и файл |
| Группа, текст начинается с `умник` / `umnik` / `@умник` (регистр не важен) | да |
| Группа, файл(ы) без текста | да |
| Группа, обычный текст | нет |

HTTP-ответ **не ждёт** модель. `schedule_umnik_reply` стартует daemon-поток; в JSON `umnik_message` обычно `null`, `asked_umnik: true`. UI пишет «Умник отвечает…» и опрашивает ленту: каждые 2.5 с всегда, плюс 12 раз раз в секунду сразу после отправки.

Тесты могут вызвать `post_message(..., wait_umnik=True)` — тогда ответ Умника синхронный.

### Что уходит модели

`run_umnik_reply` → `ask_umnik_chat` (`deals/services/umnik.py`):

- `message` — текст; для голоса сначала `transcribe_room_voice` (`deals/services/transcribe.py`, те же `SPEECH_TO_TEXT_*`, что у Telegram). Удачная расшифровка дописывается в тело сообщения как `Расшифровка голосового: …`.
- Если STT пустой: «Голосовое сообщение: речь распознать не удалось…». Файл без текста: «(файл без комментария)».
- `history` — последние 20 сообщений без system, роли `user`/`assistant`.
- `actor` — username автора, `capabilities` — `umnik_capabilities(author)` (права править CRM / класть файлы проекта).
- `attachments` — как в `docs/umnik-chat-attachments.md`: `download_url` от `UMNIK_CRM_BASE_URL`, опционально `shared_path`, `content_b64` если файл ≤ `UMNIK_CHAT_INLINE_MAX_MB`.
- `deal_id` / `deal_code` — только если у комнаты заполнен FK.

Ответ Умника создаёт `RoomMessage` с `author_kind=umnik`. Пути из `attachments` ответа копируются через `resolve_server_path` (разрешённые корни, см. вложения чата умника).

## PWA UI (факт из шаблонов)

- Телефон: нижние вкладки Контакты / Звонки / Чаты / Настройки; широкий экран — левая колонка (`static/css/messenger.css`).
- Композер: `+` (файлы), textarea, микрофон. Enter без Shift отправляет; Shift+Enter — новая строка.
- Голос пишется в браузере (`MediaRecorder`, предпочтение `audio/mp4` → `aac` → `webm;opus` → `webm` → `ogg`). Safari спросит микрофон.
- Поиск на списке чатов — клиентский фильтр по `data-search`, не поиск по телам сообщений.
- В PWA нет ссылок `/deals/` (тест `test_app_shell_has_no_crm_nav`). В Настройках есть «Открыть CRM» → Главная.

## Примеры

Личный чат с Умником (PWA):

```http
POST /app/new/
Content-Type: application/x-www-form-urlencoded

with_umnik=on
```

Редирект на `/app/<id>/`. Дальше каждое сообщение зовёт модель.

Группа, Умника зовут явно:

```http
POST /rooms/12/send/
body=умник, поставь задачу на фасады
```

Ответ (модель ещё в фоне):

```json
{
  "ok": true,
  "asked_umnik": true,
  "umnik_message": null,
  "message": {
    "id": 81,
    "author_kind": "user",
    "kind": "text",
    "body": "умник, поставь задачу на фасады",
    "attachments": []
  }
}
```

Догнать ответ:

```http
GET /rooms/12/messages/?after=81
```

```json
{ "items": [{ "id": 82, "author_kind": "umnik", "kind": "umnik", "body": "Записал.", "attachments": [] }] }
```

## Эксплуатация

```bash
# тесты мессенджера
docker compose exec app python manage.py test rooms.tests

# файлы комнат на диске
ls crm_files/rooms/

# HTTPS для установки на iPhone (профиль caddy)
docker compose --profile https up -d
```

Голосовые на проде: тот же volume `whisper_cache`, что у `telegram_bot`. Первый запрос после пустого кэша качает модель HuggingFace (см. `docs/telegram-bot.md`).

## Типичные сбои

| Симптом | Что проверить |
|---------|----------------|
| После логина с телефона Главная, не чаты | UA без `Mobile`/`Android`/`iPhone`, или в форме был `next=` |
| Чёрный экран / нет иконки PWA | HTTP без TLS; DNS на старый IP (см. `PROJECT_STATUS.md`); ярлык iPhone кэширует иконку — удалить и добавить снова |
| Кнопка «висит» минуту на Умнике | Не должно: `wait_umnik` в HTTP выключен. Если висит — смотреть сеть/JS, не синхронный вызов |
| Умник молчит на голос | `SPEECH_TO_TEXT_BACKEND`, логи `rooms`, volume `whisper_cache`; в группе голос зовёт Умника только если он **участник** |
| Умник молчит на обычный текст в группе | Нужен префикс `умник,` / `umnik` или файл без подписи |
| 404 на чужой комнате | Так задумано: нет членства → 404 |
| Папка «Клиенты» пустая | `Room.deal` из UI не ставится |
| Стили пропали | Bootstrap/HTMX лежат в `static/vendor/`, не на CDN. `collectstatic`, Caddy отдаёт `/static/` из `./staticfiles` |
| Старый service worker кэширует UI | `/app/sw.js` и `app_base.html` сами снимают регистрацию |

## Где код

| Файл | Роль |
|------|------|
| `rooms/models.py` | Room / Member / Message / Attachment |
| `rooms/services.py` | создать чат, файлы, STT, фон Умника, уведомления |
| `rooms/views.py` | HTTP + манифест + SW |
| `rooms/urls.py` | маршруты include |
| `core/urls.py` | `/rooms/` и `/app/` + манифест |
| `core/views.py` | `StaffLoginView` |
| `core/context_processors.py` | `rooms_ns`, `app_shell` |
| `accounts/permissions.py` | `can_use_umnik_chat`, `staff_users_qs`, `umnik_capabilities` |
| `templates/rooms/` | PWA и CRM-вид |
| `static/css/messenger.css` | вёрстка |
| `rooms/tests.py` | 14 тестов оболочки, Умника, голоса, 404 |
