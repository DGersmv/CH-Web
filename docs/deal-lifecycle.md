# Жизненный цикл сделки: лиды, коды проекта, статусы

## Назначение и границы

Операционный runbook по созданию и ведению сделки от «лида без менеджера»
до смены статуса на карточке. Покрывает:

- создание лида с дашборда и формы `/deals/new/`;
- формат и нормализацию `project_code`;
- claim лида («Взять в работу»);
- смену статуса, менеджера, модулей и наценки;
- вкладки «Состояние проекта» на карточке сделки;
- orphan-сделки из ArchiCAD plugin API.

Основные компоненты:

- модели: `deals.models.Deal`, `normalize_project_code`,
  `build_project_code_from_parts`;
- формы: `DashboardLeadForm`, `DealCreateForm`;
- views: `deals/views.py` (`create_dashboard_lead`, `claim_lead`,
  `update_deal_status`, …), `core/views.py` (`home`);
- UI: `templates/home.html`, `templates/deal_detail.html`,
  `templates/includes/deal_*_block.html`,
  `templates/includes/dashboard_leads_block.html`;
- plugin orphan: `deals/api_views.PluginProjectVersionCreateApi`.

Не покрывает конфигуратор/смету, файлы сделки, клиентский портал и
collaboration — для них есть или планируются отдельные guides.

## Маршруты

| Метод и путь | Назначение | Доступ |
|---|---|---|
| `GET /` | Дашборд: новые лиды, мои сделки, «зависшие» | login |
| `POST /dashboard/leads/create/` | Создать лид + клиента (HTMX) | login, не file-only |
| `POST /dashboard/leads/<id>/claim/` | Назначить себя менеджером | login |
| `GET/POST /deals/new/` | Создать сделку формой | login |
| `GET /deals/<id>/` | Карточка сделки | login |
| `POST /deals/<id>/status/` | Сменить `Deal.status` (HTMX) | login, не file-only |
| `POST /deals/<id>/manager/` | Сменить `assigned_manager` | login, не file-only |
| `POST /deals/<id>/module-count/` | Сменить `module_count` | login, не file-only |
| `POST /deals/<id>/margin/` | Сменить `margin_percent` | login, не file-only |
| `POST /api/plugin/project-versions/` | Импорт версии; может создать orphan | token auth |

File-only роли (`designer`, `production` через
`accounts.permissions.is_file_only_role`) получают 403 на create/status/
manager/module/margin. На карточке они видят статус и модули только для
чтения.

## Код проекта (`project_code`)

### Формат

Автосборка: `{module_count}МД-{client}-{site}`.

Пример: `5МД-Иван-Апатиты`.

- `build_project_code_from_parts(module_count, client_part, site_part)`
  склеивает сегменты через дефис и схлопывает пробелы внутри сегментов.
- Ручной ввод на `/deals/new/` допускается; пустой код собирается из
  частей формы.
- Валидация на create-форме: нормализованный код должен содержать
  подстроку `мд`, иначе ошибка («Код должен содержать «МД»…»).

### Нормализация и уникальность

`normalize_project_code`: `strip` → lowercase → схлопнуть повторные
пробелы в один. Результат пишется в `project_code_normalized` при
`Deal.save()` и используется для поиска/уникальности
(в т.ч. plugin lookup).

Коллизия на `/deals/new/` ловится формой. Dashboard-lead create
предварительно не проверяет уникальность: повтор того же
`module_count` + имени + участка даст `IntegrityError` на уровне БД.

### Важные нюансы кода

1. В лиде с дашборда в код попадает **имя** (`first_name`), а не фамилия.
   Фамилия сохраняется только в карточке клиента.
2. `module_count` в модели и UI: `0..15`. Plugin API принимает только
   `1..15`. Лид с `0` модулей валиден для ручного создания.
3. ARCHITECTURE.md исторически описывает формат с пробелами
   (`3МД Иванов Пулково`); текущий код и UI используют дефисы
   (`3МД-Иван-Пулково`). Оба варианта нормализуются по-разному —
   пробелы и дефисы не эквивалентны.

## Создание лида с дашборда

Кнопка «Новый лид» на `/` → HTMX POST на
`/dashboard/leads/create/`.

### Что создаётся

1. `Client` с ФИО, телефоном, email, notes (комментарий + собранный
   адрес), `created_by=request.user`.
2. Пароль клиентского портала через `client.set_portal_password(...)`
   (обязательное поле, минимум 6 символов).
3. `Deal` со статусом `new`, без `assigned_manager`,
   `margin_percent=get_default_margin_percent()`,
   `code_client_name=first_name`, `code_site_name=location`,
   плюс `mortgage_required` и `target_deal_date`.
4. Каталоги файлов сделки: `ensure_deal_dirs(deal)`.
5. Domain event `deal.created` (через `record_domain_event` → audit).
   Событие **не** входит в `TOP_DOMAIN_EVENTS` blueprint, но пишется в
   audit log.

При успехе ответ с заголовком `HX-Redirect` на карточку сделки.
Ошибки формы возвращают modal body со статусом 400.

### Ограничения формы

| Поле | Правило |
|---|---|
| `email` | обязателен (для входа клиента) |
| `portal_password` | обязателен, ≥ 6 символов |
| `phone` | пустой → `+7`; иначе должен начинаться с `+7` |
| `location` | обязателен (участок → сегмент кода) |
| адрес (region/street/house) | опционален; пишется в `Client.notes` |
| `module_count` | `0..15`, default `0` |

## Альтернатива: `/deals/new/`

`DealCreateView` + `DealCreateForm`:

- требует `module_count`, `code_client_name`, `code_site_name`;
- клиент опционален; можно быстро создать через `new_client_name`;
- менеджер опционален (список только `role='manager'`);
- наценка из `get_default_margin_percent()`;
- статус по умолчанию модели — `new`;
- **не** выставляет portal password и **не** эмитит `deal.created`.

## Новые лиды и claim

На дашборде блок «Новые лиды без ответственного» показывает сделки с
`assigned_manager IS NULL` и статусом `orphan` или `new`.

`POST /dashboard/leads/<id>/claim/`:

- ставит `assigned_manager=request.user`;
- перерисовывает блок лидов (HTMX);
- **не** меняет статус;
- **не** пишет ChangeLog и domain event;
- **не** проверяет `is_file_only_role` — любой залогиненный пользователь,
  прошедший фильтр queryset, может взять лид.

После claim сделка исчезает из блока лидов и при статусе из
«активных» попадает в «Мои активные сделки» текущего пользователя.

## Статусы сделки

Значения `Deal.Status`:

| Значение | Label в UI |
|---|---|
| `orphan` | Orphan |
| `new` | New |
| `qualified` | Qualified |
| `sent_quote` | Sent quote |
| `contract` | Contract |
| `prepayment` | Prepayment |
| `production` | Production |
| `installation` | Installation |
| `delivered` | Delivered |
| `lost` | Lost |

### Смена статуса

HTMX select на карточке → `POST /deals/<id>/status/`.

При реальной смене:

1. сохраняет `status` + `updated_at`;
2. пишет `ChangeLog` на последнюю (или только что созданную) версию с
   `field_path='status'`;
3. эмитит `deal.status_changed` с payload
   `{old_status, new_status}`.

Ограничений на переходы нет: можно прыгнуть из `new` в `delivered` или
обратно в `orphan`. Невалидное значение → HTTP 400.

### Как статусы используются на дашборде

| Блок | Фильтр |
|---|---|
| Мои активные сделки | `assigned_manager=me` и status ∈ new…installation (без orphan/delivered/lost) |
| Новые лиды | `assigned_manager IS NULL` и status ∈ {orphan, new} |
| Зависшие сделки | не delivered/lost и `updated_at` старше **7 дней** (hardcoded) |
| Pipeline total (leadership) | всё кроме delivered/lost |

`SystemConfig.stale_deal_days` сейчас **не** читается дашбордом: порог
«зависших» зашит как `timedelta(days=7)` в `core.views.home`.

## Вкладки «Состояние проекта»

Блок на `deal_detail` с семью Bootstrap-вкладками:

1. Переговоры и КП  
2. Согласования  
3. Проектирование  
4. Договор и оплата  
5. Производство  
6. Монтаж / Установка  
7. Сдача клиенту  

Это **только UI-каркас** в `templates/deal_detail.html`. Вкладки не
связаны с `Deal.status`, не сохраняют состояние и не меняют queryset.
Каждая pane показывает текст «Раздел в разработке…».

Список тех же этапов в README — целевая структура продукта, а не
описание уже работающей логики. Операционный статус сделки — это
select `Deal.status`, не эти вкладки.

## Orphan из плагина

Если `POST /api/plugin/project-versions/` приходит с неизвестным
`project_code`, создаётся сделка:

- `status=orphan`;
- без клиента и менеджера;
- `module_count` из payload (`1..15`);
- каталоги через `ensure_deal_dirs`.

Такая сделка появляется в блоке новых лидов и может быть взята в работу
через claim. Подробности контракта плагина —
`docs/plugin-api-contract.md`.

## Сопутствующие правки на карточке

| Действие | Side effects |
|---|---|
| Менеджер | Только пользователи с `role='manager'`; пустое значение снимает назначение; ChangeLog `assigned_manager` |
| Модули | `0..15`; при смене может пересобрать `project_code` из частей, если нет конфликта нормализованного кода |
| Наценка | float из POST; ChangeLog `margin_percent`; не пересчитывает смету сама по себе |

## Примеры

### Создать лид с дашборда (smoke)

1. Войти как менеджер/head/admin.
2. `/` → «Новый лид».
3. Заполнить: модули `3`, фамилия `Иванов`, имя `Иван`, email,
   пароль портала, участок `Пулково`.
4. Ожидание: редирект на сделку с кодом `3МД-Иван-Пулково`, статус
   `New`, менеджер пустой.
5. С другого менеджера: «Взять в работу» → лид исчезает из списка,
   появляется в «Мои активные».

### Сменить статус

На карточке выбрать `Qualified` в select статуса. Ожидание: badge
обновляется без перезагрузки; в admin/`ChangeLog` появляется запись
`field_path=status`; в audit — `deal.status_changed`.

## Troubleshooting

| Симптом | Что проверить |
|---|---|
| 403 при создании лида | Роль `designer`/`production` — file-only |
| 500 при создании лида | Вероятна коллизия `project_code_normalized`; сменить имя/участок/модули |
| Код «странного» вида | В код идёт `first_name`, не фамилия |
| Лид не в блоке «Новые» | Уже есть `assigned_manager` или статус не `orphan`/`new` |
| Claim не срабатывает | Сделка уже назначена или статус вне {orphan, new} |
| Смена статуса «не пишется» | Тот же статус повторно — no-op без ChangeLog/event |
| Вкладки этапов пустые | Ожидаемо: UI shell, логика не подключена |
| «Зависшие» игнорируют settings | `stale_deal_days` в `/settings/business/` пока не влияет на дашборд |
| Plugin создал сделку без клиента | Норма для orphan; назначить менеджера и привязать клиента вручную |

## Текущие ограничения (зафиксировано по коду)

- Нет валидации переходов статусов.
- Вкладки «Состояние проекта» не связаны со статусом и не персистятся.
- Dashboard lead не защищён от дубликата кода на уровне формы.
- `claim_lead` не запрещён для file-only ролей.
- Labels статусов в UI — английские (`New`, `Qualified`, …).
- `deal.created` пишется в audit, но не входит в `TOP_DOMAIN_EVENTS`.
- Дашборд «зависших» использует hardcoded 7 дней, не `stale_deal_days`.
