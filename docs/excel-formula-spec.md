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
- Наполнение санузлов -> строки вкладок `DealBathroom` / `DealBathroomLine`

## Правила расчёта

- Все денежные вычисления идут через `Decimal`.
- Округление денег: `ROUND_HALF_UP` до 2 знаков.
- Строки с `CostItem` считаются как:
  - `material_total = quantity * price_material`
  - `work_total = quantity * price_work`
  - `line_total = material_total + work_total`
- Ручные денежные строки (`Стоимость окон`, `Сауна`, `Монтаж сауны`) берутся напрямую из формы.
- Наполнение санузлов считается через вкладки санузлов, см. ниже.
- Итого:
  - `material_total` = сумма материалов всех строк
  - `work_total` = сумма работ всех строк
  - `subtotal` = `material_total + work_total`
  - `with_margin` = `subtotal * (1 + margin_percent / 100)`

## Санузлы и дополнительные опции

### Назначение

Санузлы и дополнительные опции вынесены из простых ручных денежных полей в строки,
привязанные к draft-версии проекта. Это позволяет менеджеру менять состав и варианты
комплектации, а расчёт пересчитывает сохранённый `ProjectVersion.frozen_data.calculation`.

### Модели и снимки каталога

- `DealBathroom` — одна вкладка "Санузел N" внутри `ProjectVersion`.
- `DealBathroomLine` — строка наполнения санузла. Хранит снимок каталога:
  `name_snapshot`, `kind`, `quantity`, `unit_price`, `selected_option`.
- `DealAdditionalOptionLine` — строка раздела "Дополнительные опции" внутри
  `ProjectVersion`. Хранит `name_snapshot`, `unit_snapshot`, `quantity`,
  `unit_price`, `is_included`.
- `CostItemOption` — варианты комплектации для одной позиции каталога. Для материалов
  санузла при создании строк выбирается первый активный вариант, кроме
  `customer_material`; цена строки берётся из варианта, если она больше нуля.

Связь с каталогом остаётся только для происхождения строки и выбора вариантов. Уже
созданные строки считаются по сохранённым снимкам, поэтому изменение каталога не должно
молча переписывать старые draft-строки.

### Шаблоны каталога

- `bathroom_template_v1` — секция каталога для вкладок санузлов. Начальные строки
  повторяют вторую вкладку Excel: материалы и работы, флаг включения `1/0`, порядок как
  в шаблоне.
- `additional_options_template_v1` — секция каталога для типовых дополнительных опций.
  Все строки создаются выключенными (`is_included=False`) с количеством `0`.

### Жизненный цикл

1. Количество санузлов берётся из `frozen_data.config_inputs.bathrooms_count`
   (`D37`, максимум `MAX_BATHROOMS = 20`).
2. `ensure_bathrooms(version, count)` создаёт/удаляет вкладки `DealBathroom` и заполняет
   пустые вкладки строками из `bathroom_template_v1`.
3. Сохранение `/deals/<id>/bathrooms/<bathroom_id>/save/` обновляет строки вкладки и
   вызывает пересчёт draft-версии.
4. `ensure_additional_option_lines(version)` создаёт строки из
   `additional_options_template_v1` при первом открытии/сохранении страницы
   `/deals/<id>/additional-options/`.
5. Сохранение дополнительных опций или создание ручной строки также вызывает пересчёт
   draft-версии.

### Интеграция с `calculate_config()`

- Если у версии ещё нет вкладок санузлов, строки `plumbing` (`C33`) и
  `bathroom_equipment` (`C34`) используют эталонные суммы `_bathroom_sheet_totals()` из
  второй вкладки Excel.
- Если вкладки санузлов есть, `bathrooms_totals(version)` суммирует только включённые
  строки (`quantity * unit_price`) по всем санузлам.
- При наличии вкладок санузлов общая сумма делится на `bathrooms_count`, чтобы получить
  цену единицы для строк `C33`/`C34`.
- В этом режиме материальная часть `plumbing` принудительно равна `0`, чтобы не
  задвоить старую Excel-надбавку `60000`: все материалы уже учтены в
  `bathroom_equipment`.
- `additional_options_totals(version)` возвращает отдельные суммы материалов и работ.
  Они попадают в `calc_result.additional_options`, но не входят в
  `calc_result.totals.subtotal` и `calc_result.totals.with_margin`.

Пример структуры результата:

```json
{
  "totals": {
    "subtotal": "7140672.00",
    "with_margin": "9282873.60"
  },
  "additional_options": {
    "material_total": "150000.00",
    "work_total": "0.00",
    "subtotal": "150000.00",
    "rows": [
      {
        "name": "Свайно-винтовой фундамент под дом",
        "unit": "sqm",
        "quantity": "30.00",
        "unit_price": "5000.00",
        "line_total": "150000.00"
      }
    ]
  }
}
```

### Ограничения и частые ошибки

- Вкладки санузлов появляются только когда `bathrooms_count >= 1`.
- Если менеджер меняет количество санузлов в конфигураторе, нужно сохранить draft:
  только после этого `ensure_bathrooms()` синхронизирует вкладки версии.
- Дополнительные опции показываются в UI отдельным блоком "не входят в итог выше";
  это ожидаемое поведение, а не потеря строки расчёта.
- При изменении выбранного `CostItemOption` цена строки санузла обновляется из варианта
  только если у варианта задана положительная цена.

## Строгий режим 1:1

- Каждая строка `Таблица обзорная` в диапазоне 4..43 имеет отдельный `rule_id` в `calculate_config`.
- Для строк сохраняются ссылки на Excel-ячейки:
  - `excel_cell_qty` (ячейка количества),
  - `excel_cell_total` (ячейка итога строки).
- Добавлена автосверка формул по `cell-id` через `build_formula_reconciliation_report(...)`.

## Версия схемы

- `calc_schema_version = excel-v1`
- Сохраняется в `ProjectVersion.frozen_data`.

