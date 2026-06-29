# ARCHITECTURE.md

Этот документ — контекст для AI-ассистентов (Cursor, Claude Code) и для разработчика. Кладётся в корень репозитория. В начале каждой сессии с AI добавляй этот файл в контекст.

Важно: ниже описано текущее состояние кода и отдельно отмечены запланированные, но ещё не реализованные возможности. Не переносите пункты из "планируется" в код или документацию как факт без проверки source.

---

## 1. Что это за система

Внутренняя CRM для компании, занимающейся строительством модульных домов. Команда до 10 человек. Каждый проект — индивидуальный (типовых готовых моделей нет, только шаблоны-заготовки по количеству модулей).

Главная задача системы — автоматизация полного цикла от лида до сдачи дома, с особым акцентом на **переговорный процесс с клиентом**: менеджер в разговоре должен видеть, как меняется цена при каждой правке, и объяснять клиенту "что почём".

Хоститься будет локально (внутренний сервер компании).

## 2. Роли пользователей

- **Менеджер** — продаёт, общается с клиентом, ведёт сделку от лида до договора. Работает в CRM большую часть дня.
- **Проектировщик** — рисует проекты в ArchiCAD, отправляет расчёты и PDF-планы в CRM через плагин. В текущем интерфейсе это file-only роль без коммерческих блоков карточки сделки.
- **Админ** — редактирует справочники (позиции, цены, пользователи) через Django admin.
- **Руководитель** — видит всю воронку, аналитику, может править любые сделки.

## 3. Ключевые концепции

### Проект, сделка, версия
- **Deal (Сделка)** — основная сущность. Один клиент — одна сделка. Имеет `project_code` вида "3МД-Иванов-Пулково" (уникальный бизнес-ключ).
- **ProjectVersion (Версия проекта)** — итерация расчёта. Каждая сделка имеет много версий; текущий код хранит ArchiCAD payload или черновик расчёта в `frozen_data`.
- **Client (Клиент)** — физлицо или компания, заказчик.

### Количество модулей
Метка "3МД", "5МД", "7МД" и т.д. означает количество модулей в доме (от 1 до ~15, рекорд 11). Хранится как простое число `module_count` на Deal. Это **не** ссылка на каталог моделей — каталога нет, каждый дом индивидуальный. Используется только для фильтрации и аналитики.

### Интеграция с ArchiCAD
Текущий API описан в `docs/plugin-api-contract.md` и реализован в `deals/api_views.py`.

- Endpoint: `POST /api/plugin/project-versions/`.
- Auth: DRF Token (`Authorization: Token <token>`).
- Payload: JSON с `project_code`, `module_count`, `source="archicad"`, непустым `objects[]` и опциональным `plan_pdf_filename`.
- Каждая успешная отправка создаёт новую `ProjectVersion` с `source=archicad`.
- Если сделки с таким нормализованным кодом нет, создаётся orphan-сделка (`Deal.status="orphan"`).
- Если передан `plan_pdf_filename`, сервер создаёт запись `ProjectFile`-указатель и путь в `ProjectVersion.plan_pdf_path`, но сам PDF-файл этим endpoint'ом не загружается.

Плагин должен отправлять детальные объекты с `guid`, чтобы в будущем можно было строить diff. Сам diff по `guid` сейчас не реализован.

### Версионирование и diff
Реализовано:

- `Deal.create_new_version()` создаёт следующую версию с номером `last_version + 1`.
- Входящий plugin payload сохраняется в `ProjectVersion.frozen_data`.
- Конфигуратор сохраняет расчётный черновик в последнюю draft-версию.

Планируется, но не реализовано:

- сравнение версий по `guid`;
- автоматическая классификация "изменён / добавлен / удалён";
- автоматический перевод diff в стоимостную разницу.

### Источник данных в полях
Планируемая модель источников данных:
- `archicad` — прилетело из плагина, не трогалось
- `manual` — ввёл менеджер (цены от поставщиков, сауна)
- `override` — прилетело из ArchiCAD, но менеджер переписал

Иконки источника рядом с полями пока не реализованы. Текущая форма конфигуратора — ручные поля из `DealConfiguratorForm`.

### Отправка КП клиенту
Целевой сценарий:
1. Текущая draft-версия фиксируется со статусом `sent_to_client`
2. Генерируется итоговый PDF: титулка + план из ArchiCAD + таблица расчёта
3. Автоматически создаётся новая draft-версия (копия отправленной) для дальнейшей работы
4. Отправленная версия больше не редактируется (хранится в истории)

В текущем коде это не завершено: генерация PDF КП и строгая иммутабельность non-draft версий находятся в TODO.

### Наценка
Хранится как параметр (% на Deal), применяется при расчёте итога. Не зашита в формулы.

### Файловое рабочее пространство
Файлы проекта описаны моделью `ProjectFile` и хранятся под `CRM_FILES_ROOT` (по умолчанию `crm_files` в корне репозитория).

- Источники: `client`, `designer`, `sales`, `system`.
- Категории: `photo`, `pdf`, `dwg`, `other`.
- Директории создаются в `deals/services/storage_paths.py`: `incoming/client`, `incoming/designer`, `incoming/sales`, `outgoing/client`, `versions/vN/{plan,quote}`, `system`, `archive`.
- Загрузка, просмотр, архивирование и bulk ZIP записывают события в `ChangeLog` с `field_path="files.event"`.
- Права доступа реализованы в `accounts/permissions.py`: `head` и `admin` видят клиентские/sales/system-файлы; designer-файлы доступны всем; роли `designer` и `production` считаются file-only и не видят коммерческие блоки.

### Конфигуратор и смета
Текущий расчёт реализован в `deals/services/calculation_engine.py`; подробности в `docs/excel-formula-spec.md`.

- Версия схемы: `excel-v1`.
- Draft хранит `config_inputs`, `calculation` и `saved_at` в `ProjectVersion.frozen_data`.
- HTMX endpoints: `/deals/<id>/config/recalc/` и `/deals/<id>/config/save/`.
- Санузлы создаются из каталожного шаблона `bathroom_template_v1` по полю D37, максимум 20 вкладок.
- Дополнительные опции создаются из `additional_options_template_v1`, выключены по умолчанию и считаются отдельно от `with_margin`.

### Состояние проекта
В карточке сделки есть семь вкладок этапов:
`Переговоры и КП`, `Согласования`, `Проектирование`, `Договор и оплата`, `Производство`, `Монтаж / Установка`, `Сдача клиенту`.

Сейчас это навигационная UI-заготовка. Она не управляет `Deal.status` и не хранит отдельные данные этапов. Фактический статус сделки меняется отдельным контролом в шапке карточки.

## 4. Модель данных (общий обзор)

```
Client
  - company_name или last_name/first_name/middle_name
  - phone, email, notes
  - full_name вычисляется из компании или ФИО

Deal
  - project_code (unique)        "3МД-Иванов-Пулково"
  - project_code_normalized      для поиска, lowercase+trim
  - code_client_name/code_site_name
  - module_count                  0..15 в UI/модели, 1..15 в plugin API
  - client                       FK → Client (nullable для orphan)
  - status                       'orphan'|'new'|'qualified'|'sent_quote'|...
  - assigned_manager             FK → User
  - margin_percent               наценка, по умолчанию 30
  - mortgage_required, target_deal_date
  - created_at, updated_at

ProjectVersion
  - deal                         FK → Deal
  - version_number               1, 2, 3...
  - source                       'archicad'|'manual'|'client_revision'
  - status                       'draft'|'sent_to_client'|'accepted'|'superseded'
  - frozen_data                  JSONB — plugin payload или сохранённый draft расчёта
  - plan_pdf_path                путь к PDF от проектировщика
  - plan_preview_png_path        миниатюра первой страницы
  - plan_uploaded_at
  - quote_pdf_path               путь к итоговому КП клиенту (при sent_to_client)
  - quote_sent_at
  - created_by                   FK → User
  - created_at

ProjectFile
  - deal, project_version
  - source                       'client'|'designer'|'sales'|'system'
  - category                     'photo'|'pdf'|'dwg'|'other'
  - relative_path, original_name, size_bytes, mime_type, ext
  - is_archived, archived_at, archived_by

ChangeLog
  - project_version              FK → ProjectVersion
  - changed_by                   FK → User
  - changed_at
  - field_path                   "items.window_W02.width"
  - old_value                    JSON
  - new_value                    JSON

CostItem (справочник позиций, редактируется в админке)
  - code (unique)                "floor_insulation_200"
  - name_ru
  - unit                         'sqm'|'lm'|'pcs'|'complex'|'rubles'
  - category                     'floors'|'walls'|'openings'|...
  - price_material
  - price_work
  - formula_multiplier           опциональная формула, например "ceiling_height + 0.95"
  - is_active

Task (задачи менеджера)
  - deal                         FK → Deal
  - assignee                     FK → User
  - title
  - description
  - attachment                   файл задачи в MEDIA_ROOT/task_attachments
  - project_file                 опциональная ссылка на ProjectFile; при открытии/создании копируется в attachment
  - due_date
  - is_done
  - completed_at
  - created_at

User (расширение стандартного Django User)
  - role                         'manager'|'designer'|'production'|'admin'|'head'
```

## 5. Стек

- **Backend:** Django 5 + Django REST Framework (для API плагина)
- **DB:** PostgreSQL 16
- **Realtime:** Django Channels + Redis, запуск через Daphne.
- **Frontend:** Django templates + HTMX + Bootstrap; Bootstrap и HTMX лежат локально в `static/vendor`.
- **Файловое хранилище:** локальная папка `CRM_FILES_ROOT`.
- **Аутентификация:** Django стандартная для людей, DRF token для плагина.
- **Деплой:** Docker Compose (`app`, `db`, `redis`); `app` запускает migrate, collectstatic и Daphne.

## 6. Ключевые бизнес-правила (что легко забыть)

1. `project_code` — уникальный, регистронезависимый для поиска. UI-генератор использует формат "{модули}МД-{клиент}-{участок}".
2. `module_count` — целое число 0..15 в UI/модели и 1..15 во входящем plugin API. Не ссылка на каталог.
3. Каждая успешная отправка из ArchiCAD API = новая ProjectVersion.
4. После отправки КП клиенту текущая draft должна замораживаться и создавать новую draft — это целевой сценарий, не полностью реализованный код.
5. Замороженные версии (status != draft) должны быть иммутабельны; enforcement пока в TODO.
6. Плагин не шлёт мебель — только конструктив, который влияет на цену.
7. Сохранённый расчёт конфигуратора лежит в `ProjectVersion.frozen_data`; строки санузлов и дополнительных опций хранят snapshots в отдельных таблицах.
8. Наценка — параметр на Deal, не в формуле.
9. File-only роли (`designer`, `production`) не видят коммерческие блоки карточки сделки; полноценная RBAC-матрица по всем полям пока не реализована.

## 7. Что делать, если AI предлагает противоречащее этому документу

Отказываться. Этот документ — источник правды. Если появляется новое требование, сначала обновляется этот документ, потом код.

## 8. Версия документа

v1.1 — обновлено по текущей реализации Django-приложения: plugin API, файловое рабочее пространство, конфигуратор, санузлы, дополнительные опции, project-state tabs и известные gaps.