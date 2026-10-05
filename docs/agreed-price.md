# Договорная цена

С сентября 2026 цена, которую видит менеджер на карточке сделки, — ручное поле **«Договорная цена»**. Автосмета, санузлы, доп. опции и страница электрики в интерфейсе закрыты. Код расчёта в репозитории остаётся: его можно вернуть флагом, описанным ниже.

Спека формул Excel (`docs/excel-formula-spec.md`) описывает `calculate_config`, а не то, что сейчас сохраняется как цена сделки.

## Где смотреть в интерфейсе

Карточка `/deals/<id>/`, вкладка **«Переговоры и КП»**, блок справа «Договорная цена» (`templates/includes/deal_price_block.html`).

- Пустое поле показывает «Цена не указана».
- Сумма, комментарий и время последнего сохранения видны сразу.
- Форма уходит HTMX-запросом и подменяет только этот блок.

Роли `designer` и `production` (`is_file_only_role`) блок не видят. Остальные вошедшие сотрудники (менеджер, админ, руководитель, superadmin) могут править цену любой сделки: проверки «только своя сделка» нет.

Вкладки **«Договор и оплата»**, **«Производство»**, **«Монтаж / Установка»**, **«Сдача клиенту»** и **«Сервис / Рекламации»** на карточке — заглушки с текстом «Раздел в разработке». Оплата туда не пишется. Заявки сервиса живут отдельно на `/service/`.

Шаблоны `templates/includes/deal_cost_panel.html` и `templates/includes/deal_margin_block.html` ни одна текущая страница не подключает. Наценка на карточке не редактируется.

## Сохранение

| | |
|---|---|
| Метод | `POST` |
| URL | `/deals/<id>/agreed-price/` (`deal_agreed_price_update`) |
| Вход | `login_required` |
| Кто может | все, кроме `designer` и `production` (им `403 Not allowed`) |
| Ответ | фрагмент `includes/deal_price_block.html`, не редирект |

Пример тела (обычные пробелы и запятая как десятичный разделитель):

```
agreed_price=4 850 000,5
agreed_price_note=каркас и монтаж, участок отдельно
```

Разбор в `update_deal_agreed_price`:

1. Пробелы ` ` выкидываются, запятая меняется на точку: `4850000.5`.
2. `Decimal` округляется до копеек, `ROUND_HALF_UP`.
3. Комментарий обрезается до 300 символов.
4. Пустая сумма записывает `NULL` (цена снимается). Ноль допустим. Отрицательное и нечисловое значение — `400 Invalid price`.
5. Запись идёт только если изменилась сумма или комментарий.

Поля на `Deal` (миграция `deals/0032_deal_agreed_price`):

| Поле | Ограничение |
|---|---|
| `agreed_price` | `Decimal(max_digits=12, decimal_places=2)`, null. Потолок колонки — `9999999999.99`. Более длинное число представление не проверяет и упадёт на `save()`. |
| `agreed_price_note` | до 300 символов, по умолчанию пустая строка |
| `agreed_price_updated_at` | ставится при любом реальном изменении |

Журнал: `ChangeLog.field_path = agreed_price` на **последней** `ProjectVersion` сделки. Если версий нет, создаётся новая manual-версия. `old_value` — только прошлая сумма. `new_value` — новая сумма и комментарий; старый комментарий в журнал не кладётся.

Событие в `AuditEvent` и ленту Главной это сохранение не пишет.

## Что цена не обновляет

Договорная цена не связана с черновиком сметы.

- Колонка **«Сумма последней версии»** в списке `/deals/` видна только руководству (`is_leadership`: `head`, `admin`, `superadmin`). `DealListView._extract_total` читает `frozen_data.calculation`: `totals.with_margin` плюс `additional_options.subtotal`. Поле `Deal.agreed_price` туда не входит. Нет сохранённого расчёта — в колонке «—».
- `serialize_deal` для умного отдаёт `totals` из того же `frozen_data`, без `agreed_price`. `update_deal` это поле не принимает.
- `update_cost` / `POST /api/umnik/deals/<id>/cost/` по-прежнему пишет материалы и работу в `frozen_data['calculation']` и журнал `cost_summary_manual_edit`. Флаг интерфейса этот API не закрывает.
- Кабинет заказчика цену не показывает.
- Справочник `catalog.CostItem` этой формой не читается. Базовые строки `calculate_config` держат цены прямо в коде; `CostItem` нужен шаблонам санузлов и доп. опций, а их страницы сейчас закрыты.

## Открытие карточки всё ещё создаёт черновик

`DealDetailView` при GET, если у сделки нет версии со статусом `draft`, вызывает `create_new_version`. Затем в памяти считает `calculate_config` и кладёт итог в контекст `cost_summary`. Шаблон `deal_detail.html` этот контекст не рисует, и расчёт в `frozen_data` сам по себе не сохраняется.

Итог: заход на карточку может добавить пустую draft-версию, но не заполняет договорную цену и не наполняет колонку «Сумма последней версии».

## Выключенные страницы расчёта

Флаг задаётся один раз при импорте `deals/views.py`:

```python
CONFIGURATOR_ENABLED = getattr(settings, 'CONFIGURATOR_ENABLED', False)
```

В `core/settings.py` атрибута нет, переменная окружения не читается. Пока его не задать, значение `False`.

Закрытые view отвечают через `_configurator_disabled_response`: сообщение «Модуль автоматических расчётов отключён…» и переход на карточку сделки. Обычный запрос — `302`. HTMX — пустое тело и заголовок `HX-Redirect`. Проверка роли `is_file_only_role` стоит **после** флага, поэтому при выключенном модуле проектировщик тоже получает редирект, а не `403`.

| URL | Имя |
|---|---|
| `/deals/<id>/cost-summary/` | `deal_cost_summary_page` |
| `/deals/<id>/cost-summary/update/` | `deal_cost_summary_update` |
| `/deals/<id>/config/recalc/` | `config_recalc` |
| `/deals/<id>/config/save/` | `config_save` |
| `/deals/<id>/bathrooms/` и `.../save/` | `deal_bathrooms_page`, `deal_bathroom_tab_save` |
| `/deals/<id>/additional-options/` и save/create | `deal_additional_options_*` |
| `/deals/<id>/electrical/` и `.../save/` | `deal_electrical_page`, `deal_electrical_save` |

На странице пункта согласования (`deal_approval_detail.html`) блок «Связанные разделы проекта» всё ещё ведёт на эти URL. Карта ссылок — `_APPROVAL_RELATED_PAGES` и `_DESIGN_RELATED_PAGES` в `deals/views.py` (смета, санузлы, доп. опции, электрика). Сейчас клик возвращает на карточку с тем же сообщением.

## Как снова включить смету

1. В `core/settings.py` добавить `CONFIGURATOR_ENABLED = True`. Флаг читается при импорте модуля, не на каждый запрос.
2. Перезапустить процесс приложения. Daphne сам код не подхватывает: `docker compose restart app`.
3. После включения роли `designer` и `production` на этих URL получают `403`, остальные — прежние формы сметы.

Пока флаг выключен, тесты, которые ждут запись в `frozen_data` или `400`/`403` от этих view, с кодом расходятся. Примеры: `deals.tests` `test_updates_cost_summary_totals` (редирект `302` есть, суммы в версии не меняются), `test_rejects_negative_totals` (ждёт `400`), `accounts.tests` `test_designer_is_forbidden_on_cost_summary_page` (ждёт `403`).

## Файлы

| Файл | Роль |
|---|---|
| `deals/views.py` | `CONFIGURATOR_ENABLED`, `update_deal_agreed_price`, закрытые страницы сметы |
| `deals/models.py` | поля `agreed_price*` |
| `templates/includes/deal_price_block.html` | форма на карточке |
| `templates/deal_detail.html` | блок цены и заглушки этапов |
| `core/views.py` | `DealListView._extract_total`, контекст `cost_summary` на карточке |
| `deals/services/calculation_engine.py` | формулы, которые UI сейчас не сохраняет |
| `deals/services/umnik_actions.py` | `update_cost` / `serialize_deal` без договорной цены |
