# Согласования и проектирование

На карточке сделки (`/deals/<id>/`) вкладки **Согласования** и **Проектирование** —
живые чек-листы с гейтами, файлами-основаниями и страницами по пункту.
Они **не** меняют `Deal.status`: воронка (select на вкладке «Переговоры и КП»)
живёт отдельно. Гейты пишут только `Deal.approvals_passed_at` / `Deal.design_passed_at`.

Открыть вкладку по прямой ссылке: `/deals/<id>/#stage-approvals` или `#stage-design`
(хэш переключает Bootstrap-tab).

## Какие вкладки живые

Порядок в UI (`templates/deal_detail.html`):

| Вкладка | Состояние |
|---|---|
| Переговоры и КП | живая: клиент, договорная цена, файлы, задачи, журнал |
| Согласования | живой чек-лист + версии + гейт |
| Договор и оплата | заглушка |
| Проектирование | живой чек-лист разделов + гейт |
| Производство / Монтаж / Сдача | заглушки |
| Сервис / Рекламации | заглушка на карточке; рабочий UI — `/service/` |

Первый GET карточки **досевает** шаблонные пункты (`ensure_deal_approvals` /
`ensure_deal_design_sections`) и при отсутствии draft создаёт `ProjectVersion`.

Роли `designer` и `production` (`is_file_only_role`) видят вкладки на карточке,
но POST и отдельные страницы пункта отдают 403.

## Согласования

Шаблон: `deals/services/approvals.py` → `DEFAULT_APPROVAL_ITEMS` (10 обязательных).
Пользовательские пункты помечаются `is_custom=True`; шаблонные нельзя удалить,
но обязательность любого пункта можно переключить.

| slug | Заголовок | Связанная страница |
|---|---|---|
| `layout` | Планировка | смета (`deal_cost_summary_page`) |
| `cost_quote` | Стоимость / КП | смета |
| `bathrooms` | Комплектация санузлов | `/deals/<id>/bathrooms/` |
| `electrical` | Электрика | `/deals/<id>/electrical/` |
| `additional_options` | Дополнительные опции | `/deals/<id>/additional-options/` |
| `finishing` | Отделка / материалы | смета |
| `site` | Участок, подъезд, площадка | — |
| `foundation_geology` | Фундамент / геология | — |
| `timeline` | Сроки и график | — |
| `contract_data` | Данные для договора | — |

Связанные URL — только ссылки. Сейчас модуль расчётов выключен
(`CONFIGURATOR_ENABLED = False` в `deals/views.py`): переход на смету / санузлы /
электрика / допы редиректит на карточку с сообщением. Рабочая цена — поле
**Договорная цена** на вкладке «Переговоры и КП».

### Статусы пункта

`DealApproval.Status`: `not_started` · `waiting_client` · `approved` · `rejected` · `not_required`.

`is_satisfied` = `approved` **или** `not_required`. `rejected` и «ждём клиента»
гейт **не** закрывают.

Решение (`decided_by` / `decided_at`) пишется при `approved` / `rejected` /
`not_required` и сбрасывается, если вернуть в `not_started` / `waiting_client`.

### Маршруты

| Метод | URL | Имя |
|---|---|---|
| GET | `/deals/<id>/approvals/` | `deal_approvals` (HTMX-партиал) |
| POST | `/deals/<id>/approvals/update/` | `deal_approval_update` |
| POST | `/deals/<id>/approvals/manage/` | `deal_approval_manage` (`add` / `remove` / `toggle_required`) |
| GET | `/deals/<id>/approvals/<slug>/` | `deal_approval_detail` |
| POST | `/deals/<id>/approvals/<slug>/save/` | `deal_approval_detail_save` |
| POST | `/deals/<id>/approvals/<slug>/files/upload/` | `deal_approval_file_upload` |
| GET | `/deals/<id>/approvals/file/<file_id>/open/` | `deal_approval_file_open` |
| POST | `/deals/<id>/approvals/<slug>/files/<file_id>/delete/` | `deal_approval_file_delete` |
| POST | `/deals/<id>/approvals/version-status/` | `deal_version_status_update` |
| POST | `/deals/<id>/approvals/stage/` | `deal_approvals_stage` (`pass` / `reopen`) |

Инлайн-форма на карточке меняет статус, привязку к версии и `comment`.
Рабочие заметки `notes` — **только** на странице пункта.

### Гейт этапа

Кнопка «Завершить этап» активна, если:

1. все **обязательные** пункты `is_satisfied`;
2. есть `ProjectVersion` со статусом `accepted`.

Иначе POST → 400 `Gate not passed`. Успех пишет `approvals_passed_at`,
ChangeLog `approvals_passed_at` на принятой версии, audit `deal.approvals_passed`.
«Вернуть на доработку» обнуляет timestamp (`deal.approvals_reopened`), статусы
пунктов не трогает.

### Версии проекта на этой вкладке

Не путать с целевым сценарием ARCHITECTURE («зафиксировать КП → PDF → новая draft»).
Живые кнопки только меняют `ProjectVersion.status`:

- `send_to_client` → `sent_to_client`, один раз ставит `quote_sent_at`; PDF КП не генерируется, новая draft не создаётся.
- `client_accepted` → эта версия `accepted`, остальные `accepted` той же сделки → `superseded`.
- `back_to_draft` → `draft` с любого статуса, в том числе с `accepted`.

Иммутабельность не-draft версий **не** enforced. Можно принять версию без отправки клиенту.

## Проектирование

Шаблон: `deals/services/design.py` → `DEFAULT_DESIGN_SECTIONS` (14 обязательных +
необязательные `low_voltage`, `stairs`).

| slug | Заголовок | Связанная страница |
|---|---|---|
| `layout` | Планировка | смета |
| `facades` | Фасады | — |
| `kr_floor` / `kr_walls` / `kr_ceiling` | КР-ПОЛ / СТЕНЫ / ПОТОЛОК | — |
| `cassettes` | Кассеты | — |
| `module_dimensions` | Размеры модулей | — |
| `openings` | Окна / двери | смета |
| `electrical` | Электрика | `/deals/<id>/electrical/` |
| `plumbing` | ВК | санузлы |
| `hvac` | ОВ | — |
| `finishing` | Отделка | смета |
| `foundation` | Фундамент | — |
| `spec` | Спецификации | смета |
| `low_voltage` | Слаботочка | — (необязательный) |
| `stairs` | Лестница | — (необязательный) |

### Статусы раздела

`DealDesignSection.Status`: `not_started` · `in_progress` · `review` · `released` · `on_hold` · `not_required`.

`is_satisfied` = `released` **или** `not_required`. `on_hold` гейт не закрывает.

Решение пишется при `released` / `on_hold` / `not_required`.

Гейт этапа **не** требует принятой версии проекта — достаточно обязательных разделов.
`pass` / `reopen` → `design_passed_at` и события `deal.design_passed` / `deal.design_reopened`.
ChangeLog на pass **не** пишется (в отличие от согласований).

Маршруты зеркалят согласования: `/deals/<id>/design/`… и `/deals/<id>/design/<slug>/`.

Этапы независимы: проектирование можно закрыть, не проходя согласования, и наоборот.

## Файлы пункта / раздела

Путь на диске относительно корня сделки (`get_deal_root`):

- согласования: `approvals/<slug>/<YYYYMMDD_HHMMSS>_<имя>`
- проектирование: `design/<slug>/...`

`ProjectFile.source = system`, FK на `approval` или `design_section`,
`project_version` копируется с пункта на момент загрузки.

«Убрать» — `_archive_file`: файл переезжает в `archive/`, `is_archived=True`.
Физически не удаляется.

UI `accept` — PDF и картинки; сервер тип **не** валидирует, категория по расширению
(`_detect_category`: jpg/png/webp/gif → photo, pdf, dwg/dxf, иначе other).

Эти файлы **не** попадают в блоки «файлы клиента / проектировщика / продаж»
на вкладке переговоров (там фильтр по `source`).

Миниатюра планировки на «Переговоры и КП» берёт последний неархивный файл
пункта `layout` и открывает его через `deal_file_open`. Для `source=system`
`can_access_file_source` пропускает только `head`/`admin` — у менеджера превью
может быть 403. Просмотр с страницы пункта идёт через
`deal_approval_file_open` / `deal_design_file_open` (запрет только file-only).

## Электрика — параметры проекта

`GET/POST /deals/<id>/electrical/` пишет плоский dict в
`draft.frozen_data['electrical']` (поля `_ELECTRICAL_FIELDS`: мощность, фазы,
ввод, щит, розетки, слаботочка, схема щита и т.д. + `updated_at` / `updated_by`).

Это **не** статус пункта согласования и не файл схемы. Статус и PDF щита —
на `/deals/<id>/approvals/electrical/`.

Пока `CONFIGURATOR_ENABLED` ложен, страница недоступна (редирект на карточку).
Чтобы включить только электрику, этого флага недостаточно: он общий со сметой
и санузлами.

GET электрики при отсутствии draft **создаёт** ручную draft-версию.

## События и журналы

| Действие | ChangeLog `field_path` | Domain event | Лента главной |
|---|---|---|---|
| смена статуса пункта | `approval.<slug>` | `deal.approval_changed` | нет |
| добавление / удаление своего пункта | — | `deal.approval_item_added` / `_removed` | нет |
| `toggle_required` | — | — | — |
| файл пункта | `files.event` | `deal.approval_file_added` | нет |
| pass / reopen согласований | `approvals_passed_at` только на pass | `deal.approvals_passed` / `_reopened` | только pass |
| смена статуса версии | `version.status` | `project_version.status_changed` | нет |
| смена статуса раздела | `design.<slug>` | `deal.design_section_changed` | нет |
| pass / reopen проектирования | — | `deal.design_passed` / `_reopened` | только pass |
| сохранение электрики | — | `deal.electrical_updated` | нет |

ChangeLog по статусу пишется **только** если статус реально изменился
(комментарий / notes / версия без смены статуса — тишина).
История на странице пункта: последние 50 ChangeLog с этим `field_path`.

`TOP_DOMAIN_EVENTS` эти типы не включает. Follow-up job не ставится.

## Чего нет / ловушки

- Гейт не двигает `Deal.status` и не проверяет, что согласования пройдены до проектирования.
- Шаблонные slug при обновлении кода досеваются; title/hint/sort_order шаблонных
  перезаписываются, `is_required` и статусы — нет.
- Свой пункт с кириллическим названием: `slugify(..., allow_unicode=False)` даёт
  пустую строку → slug `custom-item`, затем `custom-item-2`, …
- Нет проверки «только свой менеджер».
- Нет тестов на гейт, статусы и файлы (есть только наличие вкладки в HTML).
- `manage` entity_id в add/remove — это `deal.id`, не id пункта.

## Пример

Закрыть согласования по объекту `5МД-Иванов-Пулково`:

1. Карточка → `#stage-approvals`. При первом заходе появятся 10 пунктов.
2. Для планировки открыть пункт → прикрепить PDF → статус «Согласовано»,
   выбрать версию.
3. Остальные обязательные — «Согласовано» или «Не требуется».
4. Справа у версии: «Клиент принял» (появится `vN accepted`).
5. «Завершить этап «Согласования»». На главной: «✅ … согласования пройдены».
6. Проектирование — по тому же принципу, без шага «принятая версия».

## Файлы

| Файл | Роль |
|---|---|
| `deals/models.py` | `Deal.approvals_passed_at` / `design_passed_at`, `DealApproval`, `DealDesignSection`, `ProjectFile.approval` / `design_section` |
| `deals/services/approvals.py` | шаблон, `ensure_*`, `approvals_gate`, контекст |
| `deals/services/design.py` | то же для разделов РД |
| `deals/views.py` | маршруты вкладок, detail, файлы, гейт, электрика, `CONFIGURATOR_ENABLED` |
| `core/views.py` | `DealDetailView` подмешивает оба контекста |
| `core/urls.py` | маршруты |
| `templates/includes/deal_approvals_block.html` | чек-лист + версии + гейт |
| `templates/includes/deal_design_block.html` | разделы + гейт |
| `templates/deal_approval_detail.html`, `deal_design_section_detail.html`, `deal_electrical.html` | страницы пункта |
| `deals/services/activity_feed.py` | pass-события на главной |
| `accounts/permissions.py` | `is_file_only_role` |
