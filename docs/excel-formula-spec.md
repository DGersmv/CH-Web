# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` и `docs/excel_extract.json`
(рабочая структура строк из Excel-шаблона). Исполняемая реализация находится в
`deals/services/calculation_engine.py`; UI-сохранение draft-версии - в
`deals/views.py`.

## Исполняемый контракт

- Основная точка входа: `calculate_config(inputs, margin_percent, version=None)`.
- Текущая версия схемы: `excel-v1` (`CALC_SCHEMA_VERSION`).
- Draft-расчет сделки хранится в `ProjectVersion.frozen_data`:
  - `config_inputs` - последние сохраненные значения формы конфигуратора;
  - `calculation` - сериализованный результат `calculate_config(...)`;
  - `calc_schema_version` - версия схемы сохраненного draft-расчета.
- Денежные вычисления выполняются через `Decimal`; деньги округляются
  `ROUND_HALF_UP` до 2 знаков.

## Входы конфигуратора

Поля формы `DealConfiguratorForm` соответствуют листу Excel
`Таблица для заполнения`:

| Excel | internal key | Назначение |
| --- | --- | --- |
| D3 | `building_area` | Площадь застройки дома, кв.м |
| D4 | `living_area` | Жилая площадь, кв.м |
| D5 | `ceiling_height` | Высота чистового потолка, м |
| D7 | `floor_150_qty` | Утепление пола 150 мм, кв.м |
| D8 | `floor_200_qty` | Утепление пола 200 мм, кв.м |
| D9 | `floor_250_qty` | Утепление пола 250 мм, кв.м |
| D10 | `floor_laminate_qty` | Чистовой пол - ламинат, кв.м |
| D11 | `floor_tile_qty` | Чистовой пол - керамогранит, кв.м |
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
| D30 | `interior_doors_count` | Двери межкомнатные, шт |
| D31 | `sauna_cost` | Сауна, руб |
| D32 | `sauna_installation_cost` | Монтаж сауны/печи, руб |
| D33 | `windows_count` | Окна, шт |
| D34 | `windows_total_cost` | Стоимость окон, руб |
| D35 | `panoramic_sections_count` | Панорамные секции, шт |
| D36 | `panoramic_sections_total_cost` | Стоимость панорамных секций, руб |
| D37 | `bathrooms_count` | Количество санузлов, шт |

Формы принимают десятичные числа с точкой или запятой, пробелами-разделителями
тысяч и символом `₽`; перед расчетом значения нормализуются.

## Правила расчета строк

- Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id`
  в `calculate_config`.
- Для строк сохраняются ссылки на Excel-ячейки:
  - `excel_cell_qty` - ячейка количества;
  - `excel_cell_total` - ячейка итога строки.
- Строка считается как:
  - `material_total = quantity * price_material`;
  - `work_total = quantity * price_work`;
  - `line_total = material_total + work_total`.
- Ручные денежные строки (`sauna`, `windows_total`,
  `panoramic_sections_total`) используют количество `1`, если введенная сумма
  больше нуля; иначе количество `0`.
- Итого по основной смете:
  - `material_total` = сумма материалов всех основных строк;
  - `work_total` = сумма работ всех основных строк;
  - `subtotal` = `material_total + work_total`;
  - `with_margin` = `subtotal * (1 + margin_percent / 100)`.

## Санузлы

Источник кода: `deals/services/bathrooms.py`.

- Количество вкладок санузлов берется из `bathrooms_count` (D37).
- Верхняя граница для UI-вкладок - `MAX_BATHROOMS = 20`.
- Если D37 меньше `1`, страница санузлов перенаправляет обратно в смету.
- Новые вкладки создаются из секции каталога `bathroom_template_v1`:
  - 22 строки материалов;
  - 14 строк работ;
  - порядок повторяет Excel-шаблон.
- Строки вкладки являются снимком для конкретной версии проекта:
  `name_snapshot`, `kind`, `quantity`, `unit_price`, `selected_option`.
  Изменения каталога не переписывают уже созданные строки версии.
- В итог санузлов попадают только строки с `is_included=True`.
- Для строк `material` сумма идет в материалы, для `work` - в работы, для
  `mixed` сумма делится пополам между материалами и работами.
- Если у `calculate_config(...)` нет `version` или у версии нет вкладок
  санузлов, используются legacy-итоги Excel из `_bathroom_sheet_totals()`.
- Если передан `version` с вкладками санузлов, расчет берет точные суммы из
  `bathrooms_totals(version)`:
  - строка `bathroom_equipment` получает материалы из вкладок;
  - строка `plumbing` получает работы из вкладок;
  - legacy-материал `plumbing` в 60 000 руб. обнуляется, чтобы не было
    двойного учета.

Пример рабочего сценария:

1. Менеджер вводит `bathrooms_count = 2` в смете.
2. Переходит в `/deals/<deal_id>/bathrooms/?count=2`.
3. `ensure_bathrooms(...)` создает две вкладки из `bathroom_template_v1`.
4. Менеджер включает/выключает строки, меняет количество, цену или модель.
5. Сохранение вкладки вызывает пересчет `ProjectVersion.frozen_data.calculation`.

## Модели материалов санузла

Источник кода: `catalog/models.py`, `catalog/views.py`, `deals/forms.py`.

- `CostItemOption` хранит модели/комплектации для строки каталога:
  `name_ru`, `manufacturer`, `article`, `country`, `unit`, `price`,
  `description`.
- Для материальных строк санузла select получает активные опции текущего
  `CostItem`.
- При создании вкладки выбирается первая активная опция, кроме служебной
  `customer_material`.
- Если пользователь меняет выбранную модель и у нее `price > 0`, сохранение
  вкладки переносит цену модели в `DealBathroomLine.unit_price`.
- Если модель не менялась, ручная цена строки сохраняется.
- Создание/редактирование модели из модального окна возвращает JSON и обновляет
  select без перезагрузки страницы.

## Дополнительные опции

Источник кода: `deals/services/additional_options.py`.

- Шаблон берется из секции каталога `additional_options_template_v1`.
- Миграция `catalog.0009_seed_additional_options_template` создает 12 базовых
  строк (фундамент, терраса, навесы, сетка от грызунов и т.д.).
- При первом открытии страницы `/deals/<deal_id>/additional-options/`
  `ensure_additional_option_lines(version)` создает строки для draft-версии:
  `is_included=False`, `quantity=0`, цена из каталога.
- Менеджер может добавить свою строку; она сохраняется как
  `DealAdditionalOptionLine` с `cost_item_id=None`, `kind='material'`.
- В расчет попадают только включенные строки. Правило распределения по
  `material` / `work` / `mixed` такое же, как у санузлов.
- Важно: дополнительные опции возвращаются в блоке
  `calculation.additional_options` и отображаются отдельно. Они **не входят** в
  `calculation.totals.subtotal` и `calculation.totals.with_margin`.

## Автосверка с Excel

- `build_formula_reconciliation_report(...)` проверяет избранные формулы по
  `cell-id` в `docs/excel_extract.json`.
- Сейчас сверяются контрольные строки:
  `floor_insulation_150`, `finish_ldsp`, `roof_gable`, `plumbing`,
  `bathroom_equipment`, `overhead_costs`.

## Версия схемы

- `calc_schema_version = excel-v1`.
- Сохраняется в `ProjectVersion.frozen_data`.

