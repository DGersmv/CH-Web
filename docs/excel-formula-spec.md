# Excel Formula Spec (v1)

Источник структуры строк: `WEB/added/calculation_items.csv`. Исполняемый расчёт, цены и ограничения — в `docs/calculation-engine.md`. Этот файл только фиксирует входы и то, что сверяется с Excel.

## Входы

Имена полей — `DealConfiguratorForm` / `config_inputs`. Ключей `facade_lm` и `bathrooms_total_cost` в коде нет.

| Смысл в Excel | Поле |
|---|---|
| Площадь застройки (наружные габариты) | `building_area` |
| Жилая площадь (без сауны) | `living_area` |
| Высота чистового потолка | `ceiling_height` |
| Фасад планкен, м.п. | `facade_planken_lm` |
| Фасад комбинированный, м.п. | `facade_combined_lm` |
| Сдвоенные перегородки 200 мм, м.п. | `partition_double_lm` |
| Одинарные перегородки 100 мм, м.п. | `partition_single_lm` |
| Двери межкомнатные, шт | `interior_doors_count` |
| Окна, шт | `windows_count` |
| Стоимость окон, руб | `windows_total_cost` |
| Панорамные секции, шт | `panoramic_sections_count` |
| Стоимость панорамных секций, руб | `panoramic_sections_total_cost` |
| Сауна, руб | `sauna_cost` |
| Монтаж сауны и печи, руб | `sauna_installation_cost` |
| Количество санузлов | `bathrooms_count` |

Наполнение санузлов в форму не вводится. Без записей `DealBathroom` движок берёт зашитый эталон листа, со строками — суммы этих строк.

Площади полов, отделки и кровель — отдельные поля (`floor_200_qty`, `finish_ldsp_lm`, `roof_gable_qty`, …). Полный список и коэффициенты (`+ 0.95`, `+ 0.15`, `+ 0.05`, `× 1.15`) — в `docs/calculation-engine.md`.

## Правила расчёта

- Деньги — `Decimal`, `ROUND_HALF_UP` до 2 знаков, построчно, затем по итогам.
- Строка обзорки: `material_total = quantity * price_material`, `work_total = quantity * price_work`. Цены строк 4–43 — литералы в `calculate_config`, не `CostItem`.
- Сауна, стоимость окон и стоимость панорам — суммы из входов. Количество такой строки 1, только если сумма больше нуля.
- Итого обзорки:
  - `material_total` и `work_total` — сумма строк 4–43;
  - `subtotal` = материал + работа;
  - `with_margin` = `subtotal * (1 + margin_percent / 100)`.
- Доп. опции в `subtotal` / `with_margin` не входят.

## Строгий режим 1:1

- Каждая строка «Таблица обзорная» 4..43 имеет свой `rule_id` в `calculate_config`.
- У строки сохраняются `excel_cell_qty` и `excel_cell_total`.
- `build_formula_reconciliation_report` сверяет **текст** формулы (не посчитанные деньги) для C5, C16, C20, C33, C34, C43.

## Версия схемы

- Константа `CALC_SCHEMA_VERSION = excel-v1`.
- В ответе движка поле называется `schema_version`.
- Полный save пишет в черновик ключ `calc_schema_version` и объект `calculation`.
