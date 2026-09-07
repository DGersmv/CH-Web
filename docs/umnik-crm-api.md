# Входящий API умника → CRM

Умник (процесс на `:7861`) ходит в Django, чтобы читать и менять сделки.
Это **не** плагин ArchiCAD (`/api/plugin/…`) и не исходящий lookup архива.

Исходящие вызовы CRM → умник: `GET {UMNIK_URL}/crm/lookup` и `POST {UMNIK_URL}/crm/chat`
(см. [umnik-chat-attachments.md](umnik-chat-attachments.md), `deals/services/umnik.py`).
Telegram-бот — отдельный вход в тот же чат: [telegram-bot.md](telegram-bot.md).

## Auth

Все эндпоинты `csrf_exempt`. Заголовок:

```
Authorization: Bearer <UMNIK_TOKEN>
```

`UMNIK_TOKEN` берётся из `.env`. **Пустой токен = все запросы 401**, даже с верным заголовком
(`deals/umnik_api.py`: сравнение только если `expected` непустой).

Кто действует в CRM — заголовок `X-Umnik-Actor` = **username** активного пользователя.
Если заголовка нет, берётся `admin`. Если такого пользователя нет или он неактивен —
ответ тот же 401 `unauthorized`, что и при плохом токене (отличить нельзя).

Права считаются от этого пользователя (`accounts.permissions.umnik_capabilities`):

| Флаг | Кто |
|---|---|
| `can_view` | любой валидный actor |
| `can_edit` | не `designer` / `production` (`can_edit_deals`) |
| `can_delete` | `admin` или `is_superuser` |

Скачивание вложения чата проверяет только Bearer, actor не нужен.

## Эндпоинты

| Метод | URL | Действие |
|---|---|---|
| GET | `/api/umnik/me/` | `{ ok, username, role, is_admin, can_view, can_edit, can_delete, can_copy_files }` |
| GET | `/api/umnik/deals/?q=&limit=` | поиск, `limit` 1..50 (дефолт 20) |
| GET | `/api/umnik/deals/lookup/?project_code=` | карточка по нормализованному коду |
| GET | `/api/umnik/deals/<id>/` | карточка по id |
| PATCH | `/api/umnik/deals/<id>/` | поля сделки |
| DELETE | `/api/umnik/deals/<id>/` | удалить сделку и папку на диске |
| PATCH | `/api/umnik/deals/<id>/config/` | поля конфигуратора + пересчёт |
| PATCH | `/api/umnik/deals/<id>/cost/` | ручные итоги материалов/работ |
| GET | `/api/umnik/chat-attachments/<id>/` | файл вложения как attachment |

Невалидный JSON в теле тихо становится `{}` (не 400).

Поиск (`q`) — `project_code`, `code_client_name`, `code_site_name`,
имя/фамилия/компания клиента. Lookup — `project_code_normalized`
(`lowercase` + схлопнутые пробелы).

## Карточка сделки (GET)

Тело `{ ok, deal }`. Поля `deal`: id, project_code, status, module_count,
margin_percent, code_client_name, code_site_name, manager, client, draft_version,
config_inputs, totals, url, summaries (версии, согласования, проектирование, санузлы).

**Побочный эффект:** GET с валидным actor вызывает `_draft()`.
Если draft-версии нет, создаётся пустая `ProjectVersion` (`source=manual`).
То же при PATCH.

## PATCH сделки

Разрешённые ключи (остальные игнорируются):

```json
{
  "status": "qualified",
  "margin_percent": 30,
  "module_count": 3,
  "project_code": "3МД-Иванов-Пулково",
  "code_client_name": "Иванов",
  "code_site_name": "Пулково",
  "assigned_manager": "manager1"
}
```

- `status` — одно из: `orphan`, `new`, `qualified`, `sent_quote`, `contract`,
  `prepayment`, `production`, `installation`, `delivered`, `lost`. Переходов нет.
- `module_count` — целое `0..15` (не 1..15 как у плагина).
- `margin_percent` — неотрицательный decimal; запятая и пробелы допустимы.
- `assigned_manager` — username активного пользователя или пустая строка (снять).
- `project_code` пишется как есть. Нормализация (`project_code_normalized`)
  срабатывает в `Deal.save()`. Код из частей (`{n}МД-{клиент}-{участок}`)
  **не пересобирается**.

Пишется `ChangeLog` (status / margin / module_count).
**`record_domain_event` на PATCH не вызывается** — лента главной статус от умника не покажет.
`deal.deleted` пишется только на DELETE.

Ошибки: `403` + `forbidden`, если нет `can_edit`; `400` на невалидное поле.

## PATCH конфигуратора

Тело — подмножество полей `DealConfiguratorForm` (неизвестные ключи → 400 `unknown config fields`).

Разрешённые ключи: `building_area`, `living_area`, `ceiling_height`,
`floor_150_qty`, `floor_200_qty`, `floor_250_qty`, `floor_laminate_qty`, `floor_tile_qty`,
`facade_planken_lm`, `facade_combined_lm`, `partition_double_lm`, `partition_single_lm`,
`finish_quarter_lm`, `finish_ldsp_lm`, `finish_gkl_lm`, `finish_mdf_lm`, `finish_plywood_lm`,
`bathroom_tile_lm`, `roof_gable_qty`, `roof_flat_qty`, `interior_doors_count`,
`sauna_cost`, `sauna_installation_cost`, `windows_count`, `windows_total_cost`,
`panoramic_sections_count`, `panoramic_sections_total_cost`, `bathrooms_count`.

Поведение как у сохранения сметы в UI:

1. Мержит присланные поля с текущим draft.
2. **Заменяет весь `frozen_data`** на `{ calc_schema_version, config_inputs, saved_at }` —
   объекты плагина (`objects`) и прочие ключи теряются.
3. `ensure_bathrooms` по `bathrooms_count`.
4. `calculate_config` → `frozen_data.calculation`.
5. `ChangeLog` по изменённым ключам `config.<field>`.

## PATCH сумм

Обязательны оба поля:

```json
{ "materials_total": 1200000, "work_total": 400000 }
```

Пересчитываются `subtotal` и `with_margin` от `deal.margin_percent`.
Строки сметы не трогаются — только `calculation.totals`.
`ChangeLog.field_path = cost_summary_manual_edit`.

## DELETE

Только admin. Удаляет ряд `Deal` (каскад версий) и, если получится,
`shutil.rmtree` корня папки сделки. Ошибки диска глотаются.

## Чат в CRM (не этот API)

Виджет в шапке доступен **любому активному залогиненному** пользователю
(`can_use_umnik_chat`), не только admin.

| Метод | URL | Назначение |
|---|---|---|
| GET | `/umnik/chats/` | список тредов текущего пользователя |
| POST | `/umnik/chats/new/` | новый тред |
| GET | `/umnik/chats/<id>/` | история |
| POST | `/umnik/chat/` | отправить сообщение → `ask_umnik_chat` |
| POST | `/umnik/chats/upload/` | загрузить файл в тред |

Треды изолированы по `user`. Telegram-группа — отдельный `TelegramGroupThread`,
не тред сотрудника.

## Ограничения и ловушки

- Пустой `UMNIK_TOKEN` выключает API целиком.
- Несуществующий `X-Umnik-Actor` выглядит как «не авторизован».
- GET карточки может создать пустой draft.
- PATCH config затирает `frozen_data` целиком.
- Смена статуса через умника не попадает в ленту главной.
- Чат умника не создаёт `ServiceRequest` (см. [service-requests.md](service-requests.md)).

## Файлы

| Файл | Роль |
|---|---|
| `deals/umnik_api.py` | HTTP-обёртка, токен, actor |
| `deals/services/umnik_actions.py` | поиск, сериализация, PATCH/DELETE |
| `deals/services/umnik.py` | исходящие lookup/chat |
| `deals/services/umnik_chat.py` | хранение тредов и вложений |
| `accounts/permissions.py` | `can_use_umnik_chat`, `umnik_capabilities` |
| `core/urls.py` | маршруты `/api/umnik/` и `/umnik/chats/` |
