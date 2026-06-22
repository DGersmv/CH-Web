# ARCHITECTURE.md

Этот документ — контекст для AI-ассистентов (Cursor, Claude Code) и для разработчика. В начале каждой сессии с AI добавляй этот файл в контекст.

---

## 1. Что это за система

Внутренняя CRM для компании, занимающейся строительством модульных домов. Команда до 10 человек. Каждый проект индивидуальный: типовых готовых моделей нет, есть справочники и шаблоны-заготовки для расчёта.

Главная задача системы — автоматизация полного цикла от лида до сдачи дома, с особым акцентом на **переговорный процесс с клиентом**: менеджер в разговоре должен видеть, как меняется цена при каждой правке, и объяснять клиенту "что почём".

Хостинг предполагается локальный (внутренний сервер компании).

## 2. Роли пользователей

- **Менеджер** — продаёт, общается с клиентом, ведёт сделку от лида до договора. Видит коммерческие данные по сделкам.
- **Проектировщик** — готовит материалы в ArchiCAD и работает с проектными файлами. В коде относится к file-only ролям и не видит коммерческий конфигуратор.
- **Производство** — file-only роль для производственных файлов и проектных материалов без коммерческих блоков.
- **Админ** — редактирует справочники, цены, пользователей и настройки через Django admin.
- **Руководитель** — видит всю воронку, аналитику и коммерческие данные.

Практические проверки доступа лежат в `accounts/permissions.py`: `designer` и `production` считаются file-only, а `head` и `admin` — leadership.

## 3. Ключевые концепции

### Проект, сделка, версия

- **Client (Клиент)** — физлицо или компания, заказчик.
- **Deal (Сделка)** — основная сущность. Имеет уникальный `project_code` и нормализованное поле `project_code_normalized` для поиска/уникальности.
- **ProjectVersion (Версия проекта)** — итерация проекта или расчёта. Каждая сделка имеет много версий; draft-версия используется для текущего конфигуратора.

`project_code` сейчас строится как `{module_count}МД-{code_client_name}-{code_site_name}`, например `3МД-Иван-Пулково` (`build_project_code_from_parts`). `module_count` хранится простым числом и допускает диапазон `0..15`; это не ссылка на каталог моделей.

### Интеграция с ArchiCAD

Плагин ArchiCAD подключается к CRM по REST API:

- `POST /api/plugin/project-versions/`
- DRF Token Auth: `Authorization: Token <token>`
- JSON payload с `project_code`, `module_count`, `source=archicad`, `objects[]` и опциональным `plan_pdf_filename`

Каждый успешный запрос создаёт новую `ProjectVersion` с `source=archicad`. Если сделка по `project_code` не найдена, API создаёт orphan-сделку (`status=orphan`) без клиента. `plan_pdf_filename` пока создаёт запись `ProjectFile` и путь в версии, но не передаёт байты PDF.

Детальный diff по GUID-ам объектов и перевод изменений в денежную разницу — запланированная возможность, но в текущем коде не реализована.

### Конфигуратор и расчёт

Текущий коммерческий расчёт живёт в ручном конфигураторе:

- форма входов: `DealConfiguratorForm` (`deals/forms.py`);
- расчёт Excel-parity: `calculate_config(...)` (`deals/services/calculation_engine.py`);
- страницы и HTMX endpoints: `deals/views.py`, `core/urls.py`.

Основной поток:

1. Менеджер редактирует входы конфигуратора на `/deals/<id>/cost-summary/`.
2. `recalc_configurator` пересчитывает смету без сохранения.
3. `save_configurator_draft` сохраняет `config_inputs`, создаёт/синхронизирует вкладки санузлов и пишет `calculation` в `ProjectVersion.frozen_data`.
4. Страница сделки показывает `cost_summary`: материалы, работы, итог с наценкой, дополнительные опции и итог для клиента.

`frozen_data` имеет два актуальных формата:

- **ручной конфигуратор**: `calc_schema_version`, `config_inputs`, `calculation`, `saved_at`;
- **плагин ArchiCAD**: `contract_version`, `project_code`, `module_count`, `source`, `objects`.

Эти форматы пока не объединены: ArchiCAD payload не маппится автоматически в `config_inputs`.

### Санузлы и дополнительные опции

Смета расширена двумя модулями поверх базовой Excel-таблицы:

- **Санузлы** (`DealBathroom`, `DealBathroomLine`) — количество вкладок берётся из `bathrooms_count` (D37). Новые вкладки копируют строки из секции каталога `bathroom_template_v1`. Для материалных строк можно выбрать `CostItemOption`, который подставляет цену модели.
- **Дополнительные опции** (`DealAdditionalOptionLine`) — строки берутся из секции `additional_options_template_v1` или создаются вручную на странице сделки.

При наличии вкладок санузлов `calculate_config` берёт суммы из `DealBathroomLine` и распределяет их по строкам Excel C33/C34. Дополнительные опции возвращаются в отдельном блоке `calculation.additional_options` и прибавляются к `with_margin` как отдельная сумма, не проходящая через основную наценку.

### Отправка КП клиенту

Модели уже содержат статусы `sent_to_client` и поля `quote_pdf_path` / `quote_sent_at`, но workflow "зафиксировать и отправить КП" с генерацией PDF и автоматическим созданием новой draft-версии пока не реализован в UI.

### Наценка

`margin_percent` хранится на `Deal` и применяется в `calculate_config` к базовой смете. Дополнительные опции добавляются сверху к итоговой сумме для клиента.

## 4. Модель данных (общий обзор)

```
Client
  - ФИО / компания, телефон, email, адресные и договорные поля

Deal
  - project_code (unique)        "3МД-Иван-Пулково"
  - project_code_normalized      lowercase+trim для поиска и уникальности
  - code_client_name             часть кода проекта
  - code_site_name               часть кода проекта
  - module_count                 0..15
  - client                       FK -> Client (nullable для orphan)
  - status                       orphan|new|qualified|sent_quote|contract|...
  - assigned_manager             FK -> User
  - margin_percent               наценка, по умолчанию 30
  - mortgage_required, target_deal_date
  - created_at, updated_at

ProjectVersion
  - deal                         FK -> Deal
  - version_number               1, 2, 3...
  - source                       archicad|manual|client_revision
  - status                       draft|sent_to_client|accepted|superseded
  - frozen_data                  JSON: конфигуратор или payload плагина
  - plan_pdf_path                путь к PDF-плану
  - quote_pdf_path               путь к итоговому КП (зарезервировано)
  - created_by, created_at

Catalog Section
  - code                         bathroom_template_v1, additional_options_template_v1
  - kind, name_ru, sort_order

CostItem
  - code, name_ru, unit, category
  - price_material, price_work
  - kind                         material|work|mixed
  - default_included, section, sort_order
  - is_active

CostItemOption
  - cost_item                    FK -> CostItem
  - code, name_ru, manufacturer, article, country
  - unit, price, description
  - is_default, is_active, sort_order

DealBathroom
  - deal, project_version
  - index, label

DealBathroomLine
  - bathroom                     FK -> DealBathroom
  - cost_item                    FK -> CostItem
  - selected_option              FK -> CostItemOption
  - name_snapshot, kind, is_included
  - quantity, unit_price, sort_order

DealAdditionalOptionLine
  - project_version              FK -> ProjectVersion
  - cost_item                    FK -> CostItem (nullable для ручных строк)
  - name_snapshot, kind, is_included
  - quantity, unit_price, unit_snapshot, sort_order

ProjectFile
  - deal, project_version
  - source                       client|designer|sales|system
  - category                     photo|pdf|dwg|other
  - relative_path, original_name, size_bytes, mime_type, ext
  - uploaded_by, is_archived, archived_at, archived_by

ChangeLog
  - project_version, changed_by, changed_at
  - field_path, old_value, new_value

Task
  - deal, assignee, title, description, due_date, file, is_done

User
  - role                         manager|designer|production|admin|head

DirectMessage / Notification / AuditEvent
  - dashboard messaging, unread notifications, audit trail
```

## 5. Стек

- **Backend:** Django + Django REST Framework.
- **Realtime:** Django Channels + Redis channel layer; `ws/events/` отдаёт пользовательские события.
- **DB:** PostgreSQL 16.
- **Frontend:** Django templates + HTMX + Alpine.js.
- **Файловое хранилище:** локальная папка `CRM_FILES_ROOT` (по умолчанию `crm_files/` в корне проекта). Пути в БД относительные.
- **Аутентификация:** стандартная Django auth для людей, DRF token для плагина.
- **Деплой:** Docker Compose (`app` под Daphne, `db`, `redis`).

## 6. Ключевые URL и codepaths

- `/deals/` — список сделок (`core.views.DealListView`).
- `/deals/<id>/` — карточка сделки, конфигуратор и файлы (`core.views.DealDetailView`).
- `/deals/<id>/cost-summary/` — ручной конфигуратор и итоговая смета.
- `/deals/<id>/config/recalc/` — HTMX пересчёт без сохранения.
- `/deals/<id>/config/save/` — HTMX сохранение draft-конфигуратора.
- `/deals/<id>/bathrooms/` — вкладки санузлов.
- `/deals/<id>/additional-options/` — дополнительные опции.
- `/api/plugin/project-versions/` — ingest из ArchiCAD.
- `/api/messages/`, `/api/notifications/`, `/ws/events/` — сообщения и realtime-уведомления.

## 7. Ключевые бизнес-правила (что легко забыть)

1. `project_code` уникален и нормализуется для поиска. Текущий формат автогенерации: `{модули}МД-{клиент}-{участок}`.
2. `module_count` — целое число `0..15`. Это не ссылка на каталог.
3. Каждая отправка из ArchiCAD создаёт новую `ProjectVersion`.
4. Ручной конфигуратор работает с draft-версией сделки. Если draft нет, она создаётся автоматически.
5. `frozen_data` ручного конфигуратора и `frozen_data` плагина — разные JSON-контракты.
6. Санузлы сохраняются отдельными строками версии и при расчёте заменяют legacy-суммы Excel по строкам C33/C34.
7. Дополнительные опции не входят в `with_margin`; итог для клиента = `with_margin + additional_options.subtotal`.
8. Изменение `CostItem` не должно менять старые строки сделки: строки санузлов и дополнительных опций хранят snapshot названия и цены.
9. File-only роли (`designer`, `production`) не имеют доступа к коммерческим страницам; видимость файлов по источникам ограничена в `can_access_file_source`.
10. Workflow diff по GUID-ам, field-source icons и генерация/отправка КП пока не реализованы, хотя модели частично подготовлены.

## 8. Что делать, если AI предлагает противоречащее этому документу

Проверять по исходному коду. Если требование изменилось, сначала обновляется этот документ и профильные спецификации в `docs/`, затем код.

## 9. Версия документа

v1.1 — синхронизация с текущим Django-кодом: конфигуратор, санузлы, дополнительные опции, ProjectFile, realtime и актуальные ограничения.