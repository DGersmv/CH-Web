# Excel Formula Spec (v1)

Источник: `WEB/added/calculation_items.csv` (рабочая структура строк из Excel-шаблона).

## Входы (excel -> internal_key)

- Площадь застройки дома(наружные габариты) -> `building_area`
- Жилая площадь дома(без учета сауны) -> `living_area`
- Высота чистового потолка -> `ceiling_height`
- Утепление пола 150/200/250мм -> `floor_150_qty`, `floor_200_qty`, `floor_250_qty`
- Чистовое покрытие пола: ламинат / керамогранит -> `floor_laminate_qty`, `floor_tile_qty`
- Погонные метры наружного фасада: планкен / комбинированный -> `facade_planken_lm`, `facade_combined_lm`
- Погонные метры сдвоенных перегородок(200мм) -> `partition_double_lm`
- Погонные метры одинарных перегородок(100мм) -> `partition_single_lm`
- Отделка стен: четверть / ЛДСП / ГКЛ / МДФ / фанера-рейка -> `finish_quarter_lm`, `finish_ldsp_lm`, `finish_gkl_lm`, `finish_mdf_lm`, `finish_plywood_lm`
- Отделка стен санузла керамогранитом -> `bathroom_tile_lm`
- Кровля двускатная / плоская -> `roof_gable_qty`, `roof_flat_qty`
- Двери межкомнатные с комплектом доборных элементов -> `interior_doors_count`
- Окна -> `windows_count`
- Стоимость окон -> `windows_total_cost`
- Большие панорамные секции (более 5 кв.м) -> `panoramic_sections_count`
- Стоимость больших панорамных секций -> `panoramic_sections_total_cost`
- Сауна -> `sauna_cost`
- Монтаж сауны, печи -> `sauna_installation_cost`
- Количество санузлов -> `bathrooms_count`

## Правила расчёта

- Все денежные вычисления идут через `Decimal`.
- Округление денег: `ROUND_HALF_UP` до 2 знаков.
- Строки с `CostItem` считаются как:
  - `material_total = quantity * price_material`
  - `work_total = quantity * price_work`
  - `line_total = material_total + work_total`
- Ручные денежные строки (`Стоимость окон`, `Сауна`, `Монтаж сауны`, `Стоимость больших панорамных секций`) берутся напрямую из формы.
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

## UI-поток расчета

Основные codepath'ы:

- компактная карточка стоимости на странице сделки: `templates/includes/deal_cost_panel.html`;
- полная страница расчета: `templates/deal_cost_summary.html`;
- обработчики: `deals/views.py::cost_summary_page`, `update_deal_cost_summary`, `recalc_configurator`, `save_configurator_draft`;
- расчетный движок: `deals/services/calculation_engine.py::calculate_config`.

Поток:

1. `DealDetailView` берет последнюю draft-версию сделки или создает новую.
2. Если в `ProjectVersion.frozen_data` нет сохраненного расчета, используется набор initial-значений формы и вызывается `calculate_config(...)`.
3. Кнопка `Расчет` открывает полную страницу, где менеджер может `Пересчитать` или `Сохранить` конфигурацию.
4. `Сохранить` пишет в `frozen_data`:
   - `calc_schema_version = excel-v1`;
   - `config_inputs`;
   - `calculation`;
   - `saved_at`.
5. Компактная карточка сделки показывает totals из draft-версии. Ручное редактирование карточки меняет только `material_total` и `work_total`; `subtotal` и `with_margin` пересчитываются от этих двух значений и текущей `Deal.margin_percent`.

Ограничение: ручная правка компактной карточки не меняет исходные `config_inputs`. Если после нее открыть полный расчет и сохранить форму, totals будут пересчитаны движком из формы.

## Санузлы и дополнительные опции

Санузлы:

- страница: `deals/<deal_id>/bathrooms/`;
- шаблон строк каталога: секция `bathroom_template_v1`;
- модели: `DealBathroom`, `DealBathroomLine`;
- сервис: `deals/services/bathrooms.py`.

`bathrooms_count` берется из `frozen_data.config_inputs`. Если значение меньше 1,
страница санузлов возвращает менеджера к полному расчету. Новые вкладки санузлов
копируют строки шаблона; лишние вкладки удаляются при уменьшении количества.
В расчет попадают только строки с `is_included=True`, сумма строки =
`quantity * unit_price`.

Дополнительные опции:

- страница: `deals/<deal_id>/additional-options/`;
- шаблон строк каталога: секция `additional_options_template_v1`;
- модель: `DealAdditionalOptionLine`;
- сервис: `deals/services/additional_options.py`.

По умолчанию шаблонные дополнительные опции создаются выключенными. В итог для
заказчика на странице сделки добавляется `calculation.additional_options.subtotal`
поверх `totals.with_margin`.

## Версия схемы

- `calc_schema_version = excel-v1`
- Сохраняется в `ProjectVersion.frozen_data`.

