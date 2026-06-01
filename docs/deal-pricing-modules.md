# Deal Pricing Modules

Документ описывает дополнительные модули сметы, которые живут рядом с базовым
Excel-расчетом версии проекта: вкладки наполнения санузлов и дополнительные
опции. Базовая таблица строк 4..43 описана в `docs/excel-formula-spec.md`.

## Область действия

- Модули относятся к черновой `ProjectVersion`, а не ко всей сделке.
- UI расположен на странице сметы сделки:
  - `/deals/<deal_id>/bathrooms/`
  - `/deals/<deal_id>/additional-options/`
- Сохранение модулей пересчитывает `frozen_data["calculation"]` через
  `calculate_config(..., version=draft)`.
- Все денежные вычисления используют `Decimal` и округление до 2 знаков через
  `ROUND_HALF_UP`.

## Наполнение санузлов

### Источник данных

Каталог хранит шаблон в секции `bathroom_template_v1`:

- `Section.code = "bathroom_template_v1"`;
- строки шаблона: `CostItem` с `kind = material|work|mixed`;
- варианты моделей материалов: `CostItemOption`.

Секция наполняется миграциями каталога. Ожидаемый состав шаблона по умолчанию
проверяется тестами: 22 строки материалов и 14 строк работ. Для каждой
материальной строки есть вариант `customer_material` с ценой `0`: он означает,
что материал предоставляет заказчик.

### Создание вкладок

Количество вкладок берется из сохраненного конфигуратора:
`frozen_data["config_inputs"]["bathrooms_count"]` (поле D37 в Excel). Значение
ограничено `MAX_BATHROOMS = 20`.

`ensure_bathrooms(version, count)` приводит вкладки к этому количеству:

1. удаляет лишние вкладки с индексом больше `count`;
2. создает недостающие `DealBathroom`;
3. если вкладка пустая, копирует строки шаблона в `DealBathroomLine`.

Кнопка перехода к вкладкам активна, когда текущее или сохраненное значение
`bathrooms_count` не меньше 1. Если вкладок нет, переход возвращает пользователя
к странице сметы.

### Строки и цены

`DealBathroomLine` хранит снимок строки на момент создания вкладки:

- `name_snapshot` - название из каталога;
- `kind` - материал, работа или смешанная строка;
- `is_included` - участвует ли строка в расчете;
- `quantity` и `unit_price` - количество и цена;
- `selected_option` - выбранная модель материала.

Для материалов при создании вкладки выбирается первый активный вариант,
кроме `customer_material`. Если у выбранного варианта цена больше 0, сохранение
вкладки обновляет `unit_price` этой строки на цену варианта.

Итоги санузлов считаются только по включенным строкам:

```text
line_total = quantity * unit_price
```

Материалы попадают в материальную сумму, работы - в сумму работ, смешанные
строки делятся пополам между материалами и работами.

### Встраивание в основную смету

Без данных вкладок калькулятор использует эталонные суммы второй вкладки Excel:

- материалы санузла -> строка `bathroom_equipment` (`C34/I34`);
- работы санузла -> строка `plumbing` (`C33/I33`);
- дополнительный legacy-материал сантехники - `60000` на санузел.

Когда у версии есть `DealBathroom`, `calculate_config()` берет точные суммы из
`bathrooms_totals(version)` и делит их на количество санузлов, чтобы сохранить
формат строк Excel с количеством `bathrooms_count`. В этом режиме
`price_material` строки `plumbing` принудительно равен `0`, потому что материалы
уже учтены во вкладках санузлов и не должны задваиваться.

Пример:

```python
result = calculate_config(inputs, margin_percent="30", version=draft)
rows = {row["rule_id"]: row for row in result["rows"]}

rows["bathroom_equipment"]["material_total"]  # материалы всех санузлов
rows["plumbing"]["work_total"]                # работы всех санузлов
rows["plumbing"]["material_total"]            # 0 при использовании вкладок
```

## Дополнительные опции

### Источник данных

Шаблон дополнительных опций хранится в секции
`additional_options_template_v1`. Миграция каталога создает типовые строки
например для фундамента, террасы, навесов, сетки от грызунов и дополнительных
инженерных элементов.

`ensure_additional_option_lines(version)` создает строки
`DealAdditionalOptionLine` для версии только один раз. По умолчанию строки
исключены из расчета (`is_included = False`) и имеют количество `0`.

### Работа в UI

На странице `/deals/<deal_id>/additional-options/` пользователь может:

- включать или выключать шаблонные строки;
- менять количество и цену;
- добавлять ручную строку через форму создания.

Ручные строки создаются без привязки к `CostItem`, с выбранной единицей
измерения (`sqm`, `pcs`, `lm`, `rubles`, `complex`) и сортируются после
шаблонных строк.

### Встраивание в расчет

Дополнительные опции не добавляются в массив `result["rows"]`, потому что этот
массив повторяет базовые Excel-строки 4..43. Вместо этого калькулятор возвращает
отдельный блок:

```python
result = calculate_config(inputs, margin_percent="30", version=draft)

result["additional_options"] == {
    "rows": [...],
    "material_total": Decimal("..."),
    "work_total": Decimal("..."),
    "subtotal": Decimal("..."),
}
```

Итог блока считается так же, как у санузлов: учитываются только включенные
строки, `quantity * unit_price`, с разделением по `kind`.

Важно: текущий `totals.subtotal` и `totals.with_margin` считают базовые
Excel-строки. Блок `additional_options` возвращается отдельно для отображения и
дальнейшей интеграции в коммерческое предложение.

## Поддержка каталога

При изменении шаблонов учитывайте ограничения:

- меняйте `CostItem`/`CostItemOption` через миграции или админку, чтобы новые
  версии получали актуальный снимок;
- уже созданные `DealBathroomLine` и `DealAdditionalOptionLine` хранят свои
  `name_snapshot`, `quantity` и `unit_price`; изменение каталога не переписывает
  существующие версии автоматически;
- для новых вариантов материалов санузла задавайте положительную цену, если
  выбор варианта должен обновлять цену строки;
- `customer_material` должен оставаться нулевым вариантом для материалов
  заказчика.

## Основные codepaths

- Модели: `deals/models.py` (`DealBathroom`, `DealBathroomLine`,
  `DealAdditionalOptionLine`).
- Каталог: `catalog/models.py` (`Section`, `CostItem`, `CostItemOption`).
- Сервисы: `deals/services/bathrooms.py`,
  `deals/services/additional_options.py`,
  `deals/services/calculation_engine.py`.
- Routes: `core/urls.py` (`deal_bathrooms_page`,
  `deal_bathroom_tab_save`, `deal_additional_options_page`,
  `deal_additional_options_save`, `deal_additional_options_create`).
- Поведенческие тесты: `deals/tests.py` (`BathroomTemplateTests`,
  `BathroomOptionPricingTests`).
