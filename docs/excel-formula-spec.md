# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` и текущая реализация в `deals/services/calculation_engine.py`.

## Runtime-контракт

- Публичная функция расчёта: `calculate_config(inputs, margin_percent, version=None)`.
- Версия схемы: `CALC_SCHEMA_VERSION = "excel-v1"`.
- Все денежные вычисления идут через `Decimal`.
- Округление денег: `ROUND_HALF_UP` до 2 знаков.
- В форме допускаются пробелы, `₽`, запятая или точка как десятичный разделитель; отрицательные значения не проходят валидацию.

## Входы формы

| Excel | internal key | Назначение |
| --- | --- | --- |
| D3 | `building_area` | Площадь застройки дома, кв.м |
| D4 | `living_area` | Жилая площадь, кв.м |
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
| D27 | `roof_gable_qty` | Двускатная кровля, кв.м |
| D28 | `roof_flat_qty` | Плоская кровля, кв.м |
| D30 | `interior_doors_count` | Межкомнатные двери, шт |
| D31 | `sauna_cost` | Стоимость сауны, руб |
| D32 | `sauna_installation_cost` | Монтаж сауны/печи, руб |
| D33 | `windows_count` | Количество окон, шт |
| D34 | `windows_total_cost` | Стоимость окон, руб |
| D35 | `panoramic_sections_count` | Большие панорамные секции, шт |
| D36 | `panoramic_sections_total_cost` | Стоимость панорамных секций, руб |
| D37 | `bathrooms_count` | Количество санузлов, шт |

`calculate_config(...)` также возвращает `excel_input_mapping` для части исходных русских названий из Excel. Полный набор полей формы см. в `DealConfiguratorForm`.

## Правила строк

Каждая строка результата имеет:

- `rule_id` / `code`;
- `excel_cell_qty` и `excel_cell_total`;
- `label`, `quantity`, `unit`;
- `price_material`, `price_work`;
- `material_total`, `work_total`, `line_total`;
- `source = "excel_rule"`.

Базовая формула строки:

```text
material_total = quantity * price_material
work_total = quantity * price_work
line_total = material_total + work_total
```

Некоторые количества пересчитываются из входов:

- фасад и стены используют высоту потолка с коэффициентами `+0.95`, `+0.15` или `+0.05`;
- двускатная кровля умножается на `1.15`;
- строки `windows_total`, `panoramic_sections_total` и `sauna` используют ручную сумму как цену при количестве `1`, если сумма больше нуля.

## Санузлы

Источник: `deals/services/bathrooms.py`.

- Количество вкладок санузлов берётся из `D37` / `bathrooms_count` и ограничено `MAX_BATHROOMS = 20`.
- Новые вкладки заполняются из активных строк каталожной секции `bathroom_template_v1`.
- Для строки санузла сумма считается как `quantity * unit_price`, но только если `is_included=True`.
- Если для версии уже есть данные санузлов, `calculate_config(...)` использует точные суммы вкладок:
  - `bathroom_equipment` получает среднюю стоимость материалов на один санузел;
  - `plumbing` получает среднюю стоимость работ на один санузел;
  - legacy-материал сантехники `60000` отключается, чтобы не задвоить материалы из вкладок.
- Если вкладок ещё нет, применяется эталонная сумма из Excel-вкладки санузла.

## Дополнительные опции

Источник: `deals/services/additional_options.py`.

- Шаблонные строки берутся из секции каталога `additional_options_template_v1`.
- При первом открытии страницы строки создаются выключенными: `is_included=False`, `quantity=0`.
- Пользователь может включить шаблонную строку или создать ручную строку.
- Включённые строки суммируются отдельно в `calculation.additional_options`.
- Детальная страница расчёта показывает дополнительные опции отдельно, "не входят в итог выше"; карточка сделки показывает общий итог для заказчика как `with_margin + additional_options.subtotal`.

## Сохранение черновика

Источник: `deals/views.py`.

- `POST /deals/<id>/config/recalc/` пересчитывает форму для HTMX-ответа.
- `POST /deals/<id>/config/save/` сохраняет входы в последнюю draft-версию, создаёт/обновляет вкладки санузлов, пересчитывает результат и пишет изменённые поля в `ChangeLog` с `field_path="config.<key>"`.
- Сохранённая структура `ProjectVersion.frozen_data`:

```json
{
  "calc_schema_version": "excel-v1",
  "config_inputs": {
    "building_area": 120,
    "bathrooms_count": 1
  },
  "calculation": {
    "schema_version": "excel-v1",
    "rows": [],
    "totals": {},
    "additional_options": {}
  },
  "saved_at": "2026-06-29T16:00:00+00:00"
}
```

## Итоги

- `material_total` = сумма материалов всех основных строк.
- `work_total` = сумма работ всех основных строк.
- `subtotal` = `material_total + work_total`.
- `with_margin` = `subtotal * (1 + margin_percent / 100)`.
- `additional_options.subtotal` считается отдельно и не входит в `with_margin`.

## Строгий режим 1:1

- Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id` в `calculate_config`.
- Для строк сохраняются ссылки на Excel-ячейки:
  - `excel_cell_qty` (ячейка количества),
  - `excel_cell_total` (ячейка итога строки).
- Автосверка формул по `cell-id` выполняется через `build_formula_reconciliation_report(...)`.

