# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` (рабочая структура строк из Excel-шаблона).

## Входы (excel -> internal_key)

Этот список должен совпадать с `EXCEL_INPUT_MAPPING` в `deals/services/calculation_engine.py`.

- Площадь застройки дома(наружные габариты) -> `building_area`
- Жилая площадь дома(без учета сауны) -> `living_area`
- Высота чистового потолка -> `ceiling_height`
- Погонные метры наружного фасада(доска/брусок, планкен) -> `facade_combined_lm`
- Погонные метры сдвоенных перегородок(200мм) -> `partition_double_lm`
- Погонные метры одинарных перегородок(100мм) -> `partition_single_lm`
- Двери межкомнатные с комплектом доборных элементов -> `interior_doors_count`
- Окна -> `windows_count`
- Большие панорамные секции (более 5 кв.м) -> `panoramic_sections_count`
- Стоимость больших панорамных секций -> `panoramic_sections_total_cost`
- Сауна -> `sauna_cost`
- Монтаж сауны, печи -> `sauna_installation_cost`
- Количество санузлов -> `bathrooms_count`

## Дополнительные поля формы конфигуратора

Эти поля участвуют в `calculate_config(...)`, но не входят в `EXCEL_INPUT_MAPPING`:

- `floor_150_qty`, `floor_200_qty`, `floor_250_qty`
- `floor_laminate_qty`, `floor_tile_qty`
- `facade_planken_lm`
- `finish_quarter_lm`, `finish_ldsp_lm`, `finish_gkl_lm`, `finish_mdf_lm`, `finish_plywood_lm`
- `bathroom_tile_lm`
- `roof_gable_qty`, `roof_flat_qty`
- `windows_total_cost`

## Правила расчёта

- Все денежные вычисления идут через `Decimal`.
- Округление денег: `ROUND_HALF_UP` до 2 знаков.
- Строки с `CostItem` считаются как:
  - `material_total = quantity * price_material`
  - `work_total = quantity * price_work`
  - `line_total = material_total + work_total`
- Ручные денежные строки (`Стоимость окон`, `Сауна`, `Монтаж сауны`, `Наполнение санузлов`) берутся напрямую из формы.
- Если для версии заведены вкладки санузлов, суммы сантехники/оборудования берутся из `DealBathroomLine`; legacy-материал сантехники `60000` обнуляется, чтобы не задвоить материалы.
- Итого:
  - `material_total` = сумма материалов всех строк
  - `work_total` = сумма работ всех строк
  - `subtotal` = `material_total + work_total`
  - `with_margin` = `subtotal * (1 + margin_percent / 100)`
- В `additional_options` отдельно возвращаются строки и итоги дополнительных опций; в текущем коде они не прибавляются к `totals.subtotal`.

## Строгий режим 1:1

- Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id` в `calculate_config`.
- Для строк сохраняются ссылки на Excel-ячейки:
  - `excel_cell_qty` (ячейка количества),
  - `excel_cell_total` (ячейка итога строки).
- Добавлена автосверка формул по `cell-id` через `build_formula_reconciliation_report(...)`.

## Версия схемы

- `calc_schema_version = excel-v1`
- Сохраняется в `ProjectVersion.frozen_data`.

