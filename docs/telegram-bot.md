# Телеграм-бот диспетчерской

Бот даёт доступ к чату с умником с телефона. Модель простая:

- **Группа `TELEGRAM_DISPATCH_CHAT_ID`** целиком — это один общий чат с умником.
  Любой привязанный к CRM сотрудник пишет в группу, бот отвечает reply в той же группе.
  Автор конкретного сообщения = actor: его роль и права (`can_edit`, `can_delete`)
  уходят умнику. История общая на группу (`TelegramGroupThread` → `UmnikChatThread`).
- **Личка с ботом** — только привязка аккаунта: `/start КОД`.
- Любые другие чаты бот игнорирует.

## Настройка

1. `.env` (в git не коммитится):
   ```
   TELEGRAM_BOT_TOKEN=<токен у @BotFather>
   TELEGRAM_DISPATCH_CHAT_ID=<id группы, напр. -1001234567890>
   TELEGRAM_PROXY=<если api.telegram.org недоступен напрямую — HTTP-прокси>
   ```
   ID группы: добавить бота, написать что-нибудь и посмотреть `chat.id` в
   `https://api.telegram.org/bot<TOKEN>/getUpdates`, либо @RawDataBot.
2. Сделать бота **администратором** группы — иначе privacy mode скрывает от него
   обычные сообщения.
3. `docker compose up -d telegram_bot` (сервис на том же образе, что `app`).
4. Каждый сотрудник: `Кабинет` → «Получить код привязки» → отправить боту в личку
   `/start КОД` (код живёт 15 минут).

## Эксплуатация

- Логи: `docker compose logs -f telegram_bot`.
- Смещение long polling хранится в БД (`TelegramBotState`, один ряд). Перезапуск
  контейнера не теряет апдейты и не читает старые повторно.
- Если группу повысят до супергруппы, её ID сменится на `-100…` — обновить
  `TELEGRAM_DISPATCH_CHAT_ID` и перезапустить сервис.
- Альбомы (несколько фото одним сообщением) собираются ~2 сек и уходят умнику
  одним запросом.
- Если умник кладёт файл в чат (`ATTACH_FILE:` / attach_file), бот шлёт его
  в группу как документ Telegram, а не только текстом.
- Бот **не** создаёт `ServiceRequest`. Источник `telegram` на обращении —
  ручная метка в форме `/service/`. См. [service-requests.md](service-requests.md).
- Сделки умник меняет через входящий API CRM, не через бота: [umnik-crm-api.md](umnik-crm-api.md).

## Файлы

| Файл | Роль |
|---|---|
| `core/settings.py` | чтение `TELEGRAM_*` из окружения |
| `deals/models.py` | `TelegramProfile`, `TelegramGroupThread`, `TelegramBotState` |
| `deals/services/telegram_api.py` | клиент Bot API на urllib (getUpdates / sendMessage / getFile) |
| `deals/services/telegram_bot.py` | разбор апдейта, вызов `ask_umnik_chat`, ответ |
| `deals/services/telegram_link.py` | одноразовые коды привязки |
| `deals/management/commands/run_telegram_bot.py` | long-polling цикл |
| `templates/cabinet.html` | UI привязки |
