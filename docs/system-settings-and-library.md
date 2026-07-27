# Системные настройки, библиотека файлов и platform jobs

## Назначение и границы

Раздел `/settings/` — административная поверхность платформы для ролей
`head` и `admin`. Здесь управляют сотрудниками, корпоративной библиотекой
файлов, каталогом расчёта, бизнес-параметрами и integration tokens для
плагина ArchiCAD.

Основные компоненты:

- маршруты UI: `system_settings/urls.py`, `system_settings/views.py`;
- модели: `SystemConfig`, `IntegrationToken`, `PlatformJob`;
- библиотека: `deals.models.LibraryAsset`, загрузка/скачивание в `core/views.py`;
- пути на диске: `deals/services/storage_paths.py` (`ensure_library_dirs`);
- события: `system_settings/events.py` → `accounts.events.log_audit_event`;
- jobs: `system_settings/job_handlers.py`,
  `manage.py run_platform_jobs`.

`docs/ch-crm-platform-blueprint.md` описывает границы domain/platform.
Этот документ — операционный runbook: кто куда ходит, что реально
работает, и какие ограничения сейчас есть в коде.

## Доступ

Все view раздела `/settings/` требуют `@login_required` и
`@leadership_required` (`accounts.permissions.is_leadership` → роль
`head` или `admin`). Остальные роли получают HTTP 403.

Навигация «Настройки» в шапке показывается только leadership. Пункт
«Файлы» виден всем авторизованным пользователям, но `GET /files/`
делает redirect на `/settings/library/`, поэтому менеджер или
проектировщик после клика получают 403. Это текущее поведение, а не
отдельная публичная библиотека.

Загрузка и скачивание библиотечных файлов живут вне `/settings/`:

| Метод и путь | Доступ |
|---|---|
| `POST /files/upload/` | любой залогиненный пользователь |
| `GET /files/assets/<id>/download/` | любой залогиненный пользователь |

UI библиотеки доступен только leadership; прямой POST на upload при этом
не проверяет роль.

## Разделы `/settings/`

| Путь | Назначение |
|---|---|
| `/settings/` | Redirect на сотрудников |
| `/settings/employees/` | Создание и правка пользователей/ролей |
| `/settings/library/` | Просмотр и загрузка `LibraryAsset` |
| `/settings/catalog/` | Список `CostItem` с фильтром и поиском |
| `/settings/catalog/items/new/` | Создание позиции каталога |
| `/settings/catalog/items/<id>/` | Карточка позиции и опций |
| `/settings/catalog/options/<id>/update/` | POST-обновление опции |
| `/settings/business/` | `SystemConfig` |
| `/settings/integrations/` | Tokens, endpoint плагина, последние jobs |
| `/settings/integrations/tokens/<id>/delete/` | Удаление token |

### Сотрудники

- Создание: username, ФИО, email, роль, пароль, `is_active`.
- Правка: только `role` и `is_active`.
- Нельзя снять у себя leadership-доступ (`head`/`admin` + active).
- Нельзя деактивировать или понизить последнего активного
  leadership-пользователя.

Роли модели `accounts.User`: `manager`, `designer`, `production`,
`admin`, `head`.

### Каталог

Leadership-редактор справочника `CostItem` / `CostItemOption` с поиском
по коду и названию, фильтром по секции и категории. Пустая единица
измерения у опции подставляется из родительской позиции.

Параллельно остаются deal-flow маршруты
`/catalog/cost-items/.../options/create/` и
`/catalog/options/<id>/update/` — это известный coupling из blueprint,
а не дублирующий settings-only API.

## Бизнес-параметры (`SystemConfig`)

Ключи и дефолты (`system_settings.services.DEFAULT_SYSTEM_CONFIG`):

| Ключ | Дефолт | Фактическое использование |
|---|---|---|
| `default_margin_percent` | `30` | Да: `get_default_margin_percent()` при создании сделки и лида |
| `stale_deal_days` | `7` | Только сохранение в UI; обработчиков нет |
| `task_reminder_hours` | `24` | Только сохранение в UI; обработчиков нет |

Значения читаются через `get_system_config_value` / typed helpers. Пустая
строка в БД трактуется как «использовать дефолт». Невалидный decimal/int
при чтении тоже откатывается к дефолту.

Нельзя считать, что смена `stale_deal_days` или `task_reminder_hours`
уже меняет поведение CRM: jobs и reminders для этих ключей ещё не
подключены.

## Библиотека файлов (`LibraryAsset`)

Корпоративная медиатека (не файлы сделки). Метаданные в
`LibraryAsset`, бинарники под `CRM_FILES_ROOT/library/...`.

### Секции и вкладки

| `section` | Вкладки | Каталог на диске |
|---|---|---|
| `layout` | module groups `m1`…`m6plus` | `library/layouts/<group>/` |
| `photo` | module groups | `library/photos/<group>/` |
| `video` | module groups | `library/videos/<group>/` |
| `contract_template` | без вкладок (`module_group` = `m1`) | `library/contracts/` |
| `supplier_file` | supplier categories | `library/suppliers/<category>/` |

Категории поставщиков: `finishing`, `plumbing`, `electrical`,
`floor_heating`, `stoves_fireplaces`, `windows`, `furniture`.

### Загрузка

1. Форма из `/settings/library/` шлёт `POST /files/upload/` с
   `section`, опционально `module_group` / `supplier_category`,
   файлом `upload` и `redirect_to`.
2. Имя очищается от `/` и `\`; расширение проверяется whitelist по
   секции.
3. Файл сохраняется как
   `{YYYYMMDD_HHMMSS}_{module_group}_{original_name}`.
4. Создаётся `LibraryAsset` и audit/domain event
   `project_file.uploaded` с `entity_model='LibraryAsset'`.

Допустимые расширения (по коду `_is_allowed_library_upload`):

- layout: `.pdf`, `.jpg`, `.jpeg`, `.png`, `.webp`
- contract_template: office/PDF/текст (`.pdf`, `.doc(x)`, `.xls(x)`,
  `.ppt(x)`, OpenDocument, `.rtf`, `.txt`)
- photo: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`
- video: `.mp4`, `.webm`, `.mov`, `.avi`, `.mkv`
- supplier_file: объединение photo/video/document списков выше

Ошибки «файл не выбран» и «недопустимый формат» возвращаются query
`error=` на redirect. Размер файла отдельным лимитом библиотеки не
ограничен — действуют общие лимиты Django/прокси.

`ensure_library_dirs()` создаёт каркас каталогов при загрузке. Шаблон
`templates/files_page.html` сейчас не используется: `files_page`
только редиректит в settings.

## Integration tokens и Plugin API

`IntegrationToken` — именованный hex-ключ (`secrets.token_hex(24)`),
привязанный к активному `owner`. Создание в
`/settings/integrations/`; полный ключ показывается **один раз** в
`created_token`, дальше в UI только `masked_key`.

Аутентификация плагина
(`deals.api_views.PluginProjectVersionCreateApi`):

```http
Authorization: Bearer <integration_token>
Authorization: Token <drf_token>
```

`IntegrationTokenAuthentication` принимает keyword `token` или
`bearer` (без учёта регистра), требует `is_active=True` у токена и
владельца, обновляет `last_used_at`. UI умеет только удалять токен
(hard delete), отдельной кнопки deactivate нет — поле `is_active`
меняется через Django Admin / код.

Контракт payload: `docs/plugin-api-contract.md`.

## Domain events и platform jobs

`record_domain_event()` всегда пишет audit через
`log_audit_event`. Опция `enqueue_follow_up=True` ставит job
`domain_event_follow_up`, но **ни один текущий вызов не передаёт
`True`**, и handler для этого типа в `JOB_HANDLERS` отсутствует —
такая job сразу уйдёт в `failed`.

События, которые код реально публикует:

| `event_type` | Где |
|---|---|
| `deal.status_changed` | смена статуса сделки |
| `deal.created` | создание лида с дашборда |
| `project_version.imported` | plugin API |
| `project_file.uploaded` | upload `LibraryAsset` (имя события историческое) |
| `task.created` / `task.completed` | задачи |
| `client_message.sent` | сообщения сотрудника клиенту |

Список `TOP_DOMAIN_EVENTS` на странице интеграций — ориентир roadmap,
а не полный перечень эмиттеров.

### Jobs

Единственный зарегистрированный handler:

- `cleanup_expired_portal_access` — удаляет просроченные
  `DealClientPortalOtp` и `DealClientPortalSession`.

Запуск:

```bash
docker compose exec app python manage.py run_platform_jobs
```

Команда берёт до 100 `pending` jobs с `run_after <= now`, ставит
`running`, вызывает handler, пишет `succeeded`/`failed` и кладёт
`result` в `payload`. Автоповтора failed jobs нет. Cron/отдельный
worker в compose не настроены — постановка и запуск ручные или
внешним планировщиком.

Пример постановки cleanup:

```bash
docker compose exec app python manage.py shell -c \
  "from system_settings.services import enqueue_platform_job; enqueue_platform_job(job_type='cleanup_expired_portal_access')"
docker compose exec app python manage.py run_platform_jobs
```

Последние 20 jobs видны на `/settings/integrations/`.

## Эксплуатация и типовые сбои

1. **403 на «Файлы» или «Настройки»** — роль не `head`/`admin`.
2. **Новые сделки с маржой 30% после смены параметра** — проверьте
   запись `SystemConfig` с ключом `default_margin_percent` и что
   значение не пустая строка.
3. **Плагин 401** — неверный/неактивный token, неактивный owner, или
   заголовок не вида `Bearer …` / `Token …`.
4. **Файл в UI есть, скачивание 404** — битый `relative_path` или файл
   отсутствует под `CRM_FILES_ROOT`.
5. **Job `failed` с «No handler…»** — тип не из `JOB_HANDLERS`
   (в том числе `domain_event_follow_up`).
6. **Просроченные portal sessions копятся** — никто не ставит и не
   гоняет `cleanup_expired_portal_access`.

## Текущие ограничения

- Нет RBAC внутри settings: все leadership-пользователи видят весь
  раздел одинаково.
- `stale_deal_days` и `task_reminder_hours` пока только хранятся.
- Нет soft-revoke integration token в UI, нет журнала вызовов API.
- Upload библиотеки не требует leadership, хотя browse UI — да.
- Event `project_file.uploaded` используется и для `LibraryAsset`.
- Нет фонового worker/cron для platform jobs в `docker-compose.yml`.
- `templates/files_page.html` — мёртвый шаблон после redirect.
