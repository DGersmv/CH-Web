# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` (рабочая структура строк из Excel-шаблона).

## Входы (excel -> internal_key)

- Площадь застройки дома(наружные габариты) -> `building_area`
- Жилая площадь дома(без учета сауны) -> `living_area`
- Высота чистового потолка -> `ceiling_height`
- Погонные метры наружного фасада(доска/брусок, планкен) -> `facade_combined_lm`
- Погонные метры сдвоенных перегородок(200мм) -> `partition_double_lm`
- Погонные метры одинарных перегородок(100мм) -> `partition_single_lm`
- Двери межкомнатные с комплектом доборных элементов -> `interior_doors_count`
- Окна -> `windows_count`
- Стоимость окон -> `windows_total_cost`
- Большие панорамные секции (более 5 кв.м) -> `panoramic_sections_count`
- Стоимость больших панорамных секций -> `panoramic_sections_total_cost`
- Сауна -> `sauna_cost`
- Монтаж сауны, печи -> `sauna_installation_cost`
- Количество санузлов -> `bathrooms_count`
- Наполнение санузлов -> вкладки `DealBathroom` / `DealBathroomLine`

## Правила расчёта

- Все денежные вычисления идут через `Decimal`.
- Округление денег: `ROUND_HALF_UP` до 2 знаков.
- Строки с `CostItem` считаются как:
  - `material_total = quantity * price_material`
  - `work_total = quantity * price_work`
  - `line_total = material_total + work_total`
- Ручные денежные строки (`Стоимость окон`, `Сауна`, `Монтаж сауны`) берутся напрямую из формы.
- Наполнение санузлов считается отдельными вкладками версии проекта. Если вкладок ещё нет,
  `calculate_config` использует эталонные суммы Excel; если вкладки есть, их итоги
  подставляются в строки `plumbing` и `bathroom_equipment` без задвоения legacy-материалов.
- Дополнительные опции версии возвращаются отдельным блоком `additional_options` и не входят
  в массив базовых Excel-строк 4..43. Подробнее: `docs/deal-pricing-modules.md`.
- Итого:
  - `material_total` = сумма материалов всех строк
  - `work_total` = сумма работ всех строк
  - `subtotal` = `material_total + work_total`
  - `with_margin` = `subtotal * (1 + margin_percent / 100)`

## Строгий режим 1:1

- Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id` в `calculate_config`.
- Для строк сохраняются ссылки на Excel-ячейки:
  - `excel_cell_qty` (ячейка количества),
  - `excel_cell_total` (ячейка итога строки).
- Добавлена автосверка формул по `cell-id` через `build_formula_reconciliation_report(...)`.

## Версия схемы

- `calc_schema_version = excel-v1`
- Сохраняется в `ProjectVersion.frozen_data`.

