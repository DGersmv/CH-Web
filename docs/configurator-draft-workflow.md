# Конфигуратор: draft, сохранение и смета

Операционный гид по расчёту на сделке. Формулы Excel — в [`excel-formula-spec.md`](excel-formula-spec.md). Этот документ — про **где живёт draft**, чем «Пересчитать» отличается от «Сохранить», и какие ограничения уже есть в коде.

## Назначение

Менеджер правит входы конфигуратора (ячейки `D3`…`D37`), считает смету и сохраняет её в `ProjectVersion.frozen_data` черновика. Санузлы и доп. опции живут отдельными таблицами той же версии; итог для заказчика собирается на карточке сделки.

Кнопка «Зафиксировать и отправить» из `ARCHITECTURE.md` **не реализована**: статус версии не меняется, PDF КП не генерируется, иммутабельность `sent_to_client` не enforced.

## Где это в UI

| Экран | URL | Что делает |
| --- | --- | --- |
| Карточка сделки | `/deals/<id>/` | Компактная панель «Стоимость»; ссылка «Расчет»; ручная правка итогов |
| Конфигуратор | `/deals/<id>/cost-summary/` | Полная форма входов, пересчёт, сохранение draft |
| Санузлы | `/deals/<id>/bathrooms/` | Вкладки по D37; после save пересчитывает `frozen_data.calculation` |
| Доп. опции | `/deals/<id>/additional-options/` | Строки вне базового Excel-итога |

Роли `designer` и `production` (`is_file_only_role`) получают 403 на все эти маршруты.

## Маршруты

| Method | Path | View | Persist? |
| --- | --- | --- | --- |
| GET/POST | `/deals/<id>/cost-summary/` | `deals.views.cost_summary_page` | POST `action=save` пишет draft |
| POST | `/deals/<id>/cost-summary/update/` | `update_deal_cost_summary` | Только `calculation.totals` |
| POST | `/deals/<id>/config/recalc/` | `recalc_configurator` | Не пишет `config_inputs` |
| POST | `/deals/<id>/config/save/` | `save_configurator_draft` | Полная запись draft |
| POST | `/deals/<id>/bathrooms/<id>/save/` | `save_bathroom_tab` | Строки санузла + `_recalc_draft_calculation` |
| POST | `/deals/<id>/additional-options/save/` | `save_additional_options` | Строки опций + `_recalc_draft_calculation` |

HTMX-эндпоинты `config_recalc` / `config_save` и шаблон `templates/includes/configurator_block.html` **не подключены** ни к карточке сделки, ни к странице сметы. Рабочий UI — обычный POST-формы на `/cost-summary/`.

## Draft-версия

`_get_or_create_draft_version(deal, user)` берёт последнюю `ProjectVersion` со статусом `draft`. Если её нет — создаёт новую с `source='manual'`.

Побочный эффект: GET карточки сделки (`DealDetailView`) тоже создаёт пустой draft, если черновика ещё не было.

Plugin `POST /api/plugin/project-versions/` всегда создаёт **новую** версию (`source=archicad`, `status=draft`). После этого менеджерский save попадёт именно в неё.

`Deal.create_new_version()` не копирует предыдущий `frozen_data`.

## Что лежит в `frozen_data`

После успешного save конфигуратора:

```json
{
  "calc_schema_version": "excel-v1",
  "config_inputs": {
    "building_area": 120.0,
    "living_area": 90.0,
    "ceiling_height": 2.7,
    "bathrooms_count": 1
  },
  "calculation": {
    "schema_version": "excel-v1",
    "rows": [],
    "totals": {
      "material_total": 0,
      "work_total": 0,
      "subtotal": 0,
      "with_margin": 0,
      "margin_percent": 30
    },
    "additional_options": {
      "rows": [],
      "material_total": 0,
      "work_total": 0,
      "subtotal": 0
    }
  },
  "saved_at": "2026-08-31T16:00:00+00:00"
}
```

`config_inputs` — cleaned data `DealConfiguratorForm` (Decimal сериализуется в `float` через `_json_ready`).

Plugin пишет другой shape (`contract_version`, `objects`, `project_code`). См. ограничение ниже.

## Пересчитать vs Сохранить

На `/cost-summary/`:

1. **`action=recalc`** — считает `calculate_config(...)` по POST-форме и отдаёт HTML. **Не** пишет `config_inputs`.
2. **`action=save`** — валидирует форму, **заменяет** `frozen_data` целиком, вызывает `ensure_bathrooms`, пересчитывает, дописывает `calculation` и `saved_at`, пишет `ChangeLog` по каждому изменённому ключу `config.<field>`.
3. **`action=upload_archicad`** — заглушка: flash «интеграция Archicad будет добавлена следующим шагом», без записи файлов.

HTMX `recalc_configurator` дополнительно вызывает `ensure_bathrooms` по значению D37 из формы, даже без save. То есть «пересчёт» на этом эндпоинте **не read-only** для вкладок санузлов.

Сохранения санузлов и доп. опций идут через `_recalc_draft_calculation`: мержат `calculation` и `saved_at` в существующий JSON, не затирая остальные ключи.

## Итоги на карточке сделки

`DealDetailView` собирает `cost_summary`:

- `subtotal` / `with_margin` — из `calculation.totals` (базовые Excel-строки + наценка сделки).
- `additional_options_total` — из `calculation.additional_options.subtotal` (**не** входит в `with_margin`).
- `total_for_customer` = `with_margin + additional_options_total`.
- `cost_per_m2` = `with_margin / building_area` (без доп. опций).

Ручная правка на панели «Редактировать» принимает только `materials_total` и `work_total` (≥ 0). Подытог и «с наценкой» пересчитываются на сервере; поле `subtotal` в форме readonly и игнорируется. `ChangeLog.field_path = cost_summary_manual_edit`. Следующий полный save конфигуратора **перезапишет** эти итоги из формул.

## Цены

`deals.services.calculation_engine.calculate_config` использует **зашитые** Excel-цены в `_rule(...)`, не строки `catalog.CostItem`. Справочник каталога влияет на вкладки санузлов и доп. опции, не на базовые C4…C43.

Наценка берётся с `Deal.margin_percent` в момент расчёта и кладётся в `totals.margin_percent`.

Если у версии есть вкладки санузлов (`has_bathroom_data`), строки `plumbing` / `bathroom_equipment` берут суммы с вкладок; иначе — эталон Excel (`_bathroom_sheet_totals`).

## Примеры

Сохранить draft после правок D3/D4:

```bash
# внутри контейнера app, после логина сессией менеджера
curl -X POST "http://localhost:8001/deals/1/cost-summary/" \
  -H "Cookie: sessionid=..." \
  --data "csrfmiddlewaretoken=...&action=save&building_area=120&living_area=90&ceiling_height=2.7&..."
```

Ожидание: `ProjectVersion.frozen_data.config_inputs.building_area == 120`, `calculation.totals` заполнен, `ChangeLog` с `field_path` вида `config.building_area`.

Ручная правка итогов:

```bash
curl -X POST "http://localhost:8001/deals/1/cost-summary/update/" \
  -H "Cookie: sessionid=..." \
  --data "csrfmiddlewaretoken=...&materials_total=5391912.00&work_total=1748760.00"
```

Отрицательные суммы → HTTP 400. Дизайнер → HTTP 403.

## Troubleshooting

| Симптом | Почему | Что проверить |
| --- | --- | --- |
| «Рассчитать» санузлы disabled, хотя в форме D37 = 1 | На карточке сделки кнопка смотрит на **сохранённый** `config_inputs`, не на default формы | Сначала «Сохранить» на `/cost-summary/` |
| После save пропали `objects` от ArchiCAD | `cost_summary_page` / `save_configurator_draft` присваивают `frozen_data = {calc_schema_version, config_inputs, saved_at}` целиком | Не сохранять конфигуратор в ту же draft-версию, куда писал плагин, пока это не исправлено |
| Итог на карточке «съехал» после save сметы | Ручная правка `calculation.totals` затирается полным пересчётом | Повторно править панель или не жать «Сохранить» в конфигураторе |
| Доп. опции не в «С наценкой» | Так задумано в движке: `additional_options` отдельно; карточка складывает их только в `total_for_customer` | Смотреть блок «Дополнительные опции» в результате расчёта |
| Открыл сделку — появилась пустая vN | GET `DealDetailView` создаёт draft | Это side effect, не импорт ArchiCAD |
| «Загрузить из Archicad» ничего не грузит | Заглушка в `cost_summary_page` | Реальный ingest — `POST /api/plugin/project-versions/` |
| Числа с пробелами/запятыми не валидятся | Форма нормализует `1 200,50` → Decimal; пустые обязательные поля падают | Смотреть `DealConfiguratorForm.ConfigDecimalField` |

## Текущие ограничения (проверено по коду)

- Нет freeze / send quote / генерации `quote_pdf_path`.
- Нет проверки иммутабельности версий `sent_to_client` / `accepted` / `superseded` (см. `TODO.md`).
- Цены базовых строк не из `CostItem` и не копируются снэпшотом каталога.
- Save конфигуратора затирает чужие ключи `frozen_data`.
- HTMX live-recalc (`configurator_block.html`) не используется текущими страницами.
- `create_new_version()` без транзакции: гонка по `version_number` возможна (см. `TODO.md`).

## Код

- `deals/views.py` — `_get_or_create_draft_version`, `cost_summary_page`, `save_configurator_draft`, `recalc_configurator`, `update_deal_cost_summary`
- `core/views.py` — `DealDetailView` (панель стоимости, создание draft на GET)
- `deals/forms.py` — `DealConfiguratorForm`
- `deals/services/calculation_engine.py` — `calculate_config`
- `deals/services/bathrooms.py`, `deals/services/additional_options.py`
- `templates/deal_cost_summary.html`, `templates/includes/deal_cost_panel.html`, `templates/includes/configurator_result.html`
