# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` (рабочая структура строк из Excel-шаблона) и текущий код `deals/services/calculation_engine.py`.

## Назначение

`calculate_config(inputs, margin_percent, version=None)` воспроизводит расчёт обзорной Excel-таблицы для draft-версии сделки. В UI он используется:

- для живого пересчёта `/deals/<id>/config/recalc/`;
- для сохранения draft-конфигуратора `/deals/<id>/config/save/`;
- на странице полной сметы `/deals/<id>/cost-summary/`.

Денежные вычисления идут через `Decimal`, округление денег — `ROUND_HALF_UP` до 2 знаков.

## Входы конфигуратора

Форма `DealConfiguratorForm` хранит входы в `ProjectVersion.frozen_data.config_inputs`.

| Excel | internal key | Назначение |
| --- | --- | --- |
| D3 | `building_area` | Площадь застройки дома, кв.м |
| D4 | `living_area` | Жилая площадь без учёта сауны, кв.м |
| D5 | `ceiling_height` | Высота чистового потолка, м |
| D7 | `floor_150_qty` | Утепление пола 150 мм, кв.м |
| D8 | `floor_200_qty` | Утепление пола 200 мм, кв.м |
| D9 | `floor_250_qty` | Утепление пола 250 мм, кв.м |
| D10 | `floor_laminate_qty` | Чистовой пол, ламинат, кв.м |
| D11 | `floor_tile_qty` | Чистовой пол, керамогранит, кв.м |
| D13 | `facade_planken_lm` | Наружный фасад планкен, м.п. |
| D14 | `facade_combined_lm` | Наружный фасад комбинированный, м.п. |
| D17 | `partition_double_lm` | Сдвоенные перегородки 200 мм, м.п. |
| D18 | `partition_single_lm` | Одинарные перегородки 100 мм, м.п. |
| D20 | `finish_quarter_lm` | Интерьерная доска "в четверть", м.п. |
| D21 | `finish_ldsp_lm` | Отделка ЛДСП, м.п. |
| D22 | `finish_gkl_lm` | Отделка ГКЛ, м.п. |
| D23 | `finish_mdf_lm` | Отделка МДФ, м.п. |
| D24 | `finish_plywood_lm` | Отделка фанера/рейка, м.п. |
| D25 | `bathroom_tile_lm` | Отделка стен санузла керамогранитом, м.п. |
| D27 | `roof_gable_qty` | Кровля двускатная, кв.м |
| D28 | `roof_flat_qty` | Кровля плоская, кв.м |
| D30 | `interior_doors_count` | Межкомнатные двери, шт |
| D31 | `sauna_cost` | Стоимость сауны, руб |
| D32 | `sauna_installation_cost` | Монтаж сауны/печи, руб |
| D33 | `windows_count` | Окна, шт |
| D34 | `windows_total_cost` | Стоимость окон, руб |
| D35 | `panoramic_sections_count` | Панорамные секции, шт |
| D36 | `panoramic_sections_total_cost` | Стоимость панорамных секций, руб |
| D37 | `bathrooms_count` | Количество санузлов, шт |

Примечание: старый агрегированный вход `bathrooms_total_cost` не используется текущим кодом. Наполнение санузлов считается через отдельные вкладки `DealBathroomLine`.

## Правила строк обзорной таблицы

Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id` в `calculate_config`. Для каждой строки сохраняются:

- `excel_cell_qty` — ячейка количества;
- `excel_cell_total` — ячейка итога строки;
- `quantity`, `unit`, `price_material`, `price_work`;
- `material_total`, `work_total`, `line_total`;
- `source = "excel_rule"`.

Базовая формула строки:

```text
material_total = quantity * price_material
work_total = quantity * price_work
line_total = material_total + work_total
```

Ручные денежные строки (`sauna`, `windows_total`, `panoramic_sections_total`) используют количество `1`, если соответствующая сумма больше нуля, иначе `0`.

## Производные количества

Часть строк использует входы напрямую, часть пересчитывает площадь из погонных метров и высоты:

- `facade_planken`: `facade_planken_lm * (ceiling_height + 0.95)`;
- `facade_combined`: `facade_combined_lm * (ceiling_height + 0.95)`;
- `outer_wall`: `facade_combined_lm * (ceiling_height + 0.15)`;
- `partition_double`, `partition_single`: погонные метры `* (ceiling_height + 0.15)`;
- внутренние отделки и плитка санузла: погонные метры `* (ceiling_height + 0.05)`;
- `roof_gable`: `roof_gable_qty * 1.15`;
- `roof_flat` и `roof_flat_weld`: `roof_flat_qty`.

## Санузлы

Количество санузлов берётся из `bathrooms_count` (D37).

Связанный код:

- `deals/services/bathrooms.py`;
- модели `DealBathroom`, `DealBathroomLine`;
- страницы `/deals/<id>/bathrooms/` и `/deals/<id>/bathrooms/<bathroom_id>/save/`.

Поведение:

1. При сохранении конфигуратора `ensure_bathrooms(draft, bathrooms_count)` создаёт или удаляет вкладки санузлов.
2. Новая вкладка копирует строки из секции каталога `bathroom_template_v1`.
3. Включённые строки суммируются как `quantity * unit_price`.
4. `kind=material` попадает в материалы, `kind=work` — в работы, `kind=mixed` делится пополам.
5. Для материалных строк можно выбрать `CostItemOption`; если у опции есть цена, она подставляется в `unit_price`.

Если у версии есть вкладки санузлов (`has_bathroom_data(version)`), расчёт заменяет legacy-значения Excel:

- C33 `plumbing`: количество = `bathrooms_count`, материал = `0`, работа = средняя работа санузлов;
- C34 `bathroom_equipment`: количество = `bathrooms_count`, материал = средние материалы санузлов, работа = `0`.

Если вкладок нет, C33/C34 используют эталонные значения из `_bathroom_sheet_totals()` и legacy-материал сантехники `60000`.

## Дополнительные опции

Связанный код:

- `deals/services/additional_options.py`;
- модель `DealAdditionalOptionLine`;
- страницы `/deals/<id>/additional-options/`, `/save/`, `/create/`.

Поведение:

1. `ensure_additional_option_lines(draft)` создаёт строки из секции `additional_options_template_v1`, если у версии их ещё нет.
2. В расчёт попадают только строки с `is_included=True`.
3. Суммы считаются так же, как санузлы: `quantity * unit_price`, затем распределение по `kind`.
4. Результат возвращается отдельным блоком `calculation.additional_options`.

Дополнительные опции **не входят** в базовый `subtotal` и `with_margin`. Итог для клиента на страницах сделки считается как:

```text
total_for_customer = calculation.totals.with_margin + calculation.additional_options.subtotal
```

## Итоги

Базовый блок `calculation.totals`:

- `material_total` — сумма материалов всех строк обзорной таблицы;
- `work_total` — сумма работ всех строк обзорной таблицы;
- `subtotal = material_total + work_total`;
- `with_margin = subtotal * (1 + margin_percent / 100)`;
- `margin_percent` — значение с `Deal`.

Страница `/deals/<id>/cost-summary/update/` позволяет вручную заменить `material_total` и `work_total` в draft-версии; изменение пишется в `ChangeLog` с `field_path = "cost_summary_manual_edit"`.

## Сохранённый JSON

После сохранения draft-конфигуратора `ProjectVersion.frozen_data` имеет вид:

```json
{
  "calc_schema_version": "excel-v1",
  "config_inputs": {
    "building_area": 120.0,
    "living_area": 90.0,
    "ceiling_height": 2.7,
    "facade_planken_lm": 0.0,
    "facade_combined_lm": 48.0,
    "bathrooms_count": 1.0
  },
  "calculation": {
    "schema_version": "excel-v1",
    "rows": [
      {
        "rule_id": "project_design",
        "excel_cell_qty": "C4",
        "excel_cell_total": "I4",
        "quantity": 120.0,
        "line_total": 60000.0,
        "source": "excel_rule"
      }
    ],
    "totals": {
      "material_total": 0.0,
      "work_total": 0.0,
      "subtotal": 0.0,
      "with_margin": 0.0,
      "margin_percent": 30.0
    },
    "additional_options": {
      "rows": [],
      "material_total": 0.0,
      "work_total": 0.0,
      "subtotal": 0.0
    }
  },
  "saved_at": "2026-06-22T16:01:27.719000+00:00"
}
```

`Decimal` значения сериализуются через `_json_ready(...)`, поэтому в сохранённом JSON это числа.

## Строгий режим 1:1

- `build_formula_reconciliation_report(...)` сверяет выбранные формулы по `cell-id` с извлечённым Excel JSON.
- Это инструмент проверки соответствия Excel, а не runtime-часть UI.

## Версия схемы

- `CALC_SCHEMA_VERSION = "excel-v1"`.
- В `frozen_data` сохраняется как `calc_schema_version`.
- В результате `calculate_config` также возвращается `schema_version`.

