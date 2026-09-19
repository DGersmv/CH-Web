# Файловый workspace проекта

Этот документ описывает текущий workflow файлов сделки: где лежат файлы, кто
может их видеть, и какие действия пишутся в историю изменений.

## Назначение

Файлы сделки — не обычные Django media uploads. Это артефакты проекта, связанные
с `Deal` и опционально с `ProjectVersion`. Файлы разделены по источникам, чтобы
коммерческие материалы и документы заказчика можно было скрывать от ролей,
которым нужен только файловый доступ.

Основные точки реализации:

- `deals.models.ProjectFile` — метаданные файла в БД.
- `deals.services.storage_paths` — детерминированная структура папок.
- `deals.views` — загрузка, открытие, архивирование и bulk-действия.
- `accounts.permissions` — правила доступа по роли и источнику.
- `tasks.views` — копирование файлов сделки во вложения задач.

## Корень хранилища и структура папок

`settings.CRM_FILES_ROOT` задаёт корень файлового дерева. По умолчанию это
`<repo>/crm_files`; на сервере корень можно вынести из репозитория через
переменную окружения `CRM_FILES_ROOT`.

Для сделки `ensure_deal_dirs(deal)` создаёт:

```text
clients/<client-id>-<client-slug>/projects/<deal-id>-<project-code-slug>/
  incoming/
    client/photos/
    client/docs/
    designer/plans_pdf/
    designer/dwg/
    designer/reference/
    sales/photos/
    sales/docs/
  outgoing/client/
  system/
  archive/
```

Для версии проекта `ensure_version_dirs(project_version)` создаёт:

```text
versions/v<version_number>/
  plan/
  quote/
```

`ProjectFile.relative_path` всегда хранится относительно `CRM_FILES_ROOT`, а
`ProjectFile.absolute_path` собирает абсолютный путь при чтении.

## Источники, категории и маршрутизация

В UI (`templates/includes/deal_files_block.html`) есть три секции загрузки:

| Source | Название в UI | Куда попадает загрузка |
| --- | --- | --- |
| `client` | "Файлы от заказчика" | фото -> `incoming/client/photos`, остальное -> `incoming/client/docs` |
| `designer` | "Файлы от проектировщика" | PDF -> `incoming/designer/plans_pdf`, DWG/DXF -> `incoming/designer/dwg`, остальное -> `incoming/designer/reference` |
| `sales` | "Файлы от отдела продаж" | фото -> `incoming/sales/photos`, остальное -> `incoming/sales/docs` |

Категория определяется в `_detect_category()` по расширению:

- изображения: `.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`
- PDF: `.pdf`
- CAD: `.dwg`, `.dxf`
- все остальные расширения: `other`

Имя загруженного файла нормализуется удалением `/` и `\`, затем сохраняется в
формате:

```text
<YYYYMMDD_HHMMSS>_<source>_<category>_<original-name>
```

Оригинальное имя остаётся в `ProjectFile.original_name` и используется при
открытии файла, скачивании и формировании ZIP.

## Правила доступа

Доступ зависит от источника файла. Проверка выполняется до рендера файлового
блока и до отдачи байтов файла:

| Роль | `client` | `designer` | `sales` |
| --- | --- | --- | --- |
| `head`, `admin` | да | да | да |
| `manager` | нет | да | нет |
| `designer`, `production` | нет | да | нет |

То же правило из `can_access_file_source(user, source)` используется для:

- загрузки (`POST /deals/<deal_id>/files/upload/`);
- открытия (`GET /deals/files/<file_id>/open/`);
- архивирования (`POST /deals/files/<file_id>/archive/`);
- bulk-действий (`POST /deals/<deal_id>/files/<source>/bulk/`).

`designer` и `production` дополнительно считаются file-only ролями через
`is_file_only_role()`: они могут смотреть карточку сделки и файлы проектировщика,
но не могут менять статус, менеджера, количество модулей, наценку, конфигуратор
и лиды на dashboard.

## Действия пользователя и побочные эффекты

### Загрузка

`upload_project_file()` валидирует `DealFileUploadForm`, проверяет доступ к
источнику, создаёт папки сделки, пишет файл чанками, создаёт `ProjectFile` и
добавляет запись `ChangeLog`:

```json
{
  "action": "upload",
  "file_id": 123,
  "file_name": "plan.pdf",
  "source": "designer",
  "category": "pdf",
  "size_bytes": 456789
}
```

### Открытие / preview

`open_project_file()` отдаёт файл через `FileResponse(as_attachment=False)`.
По умолчанию пишется `action=download`; если в query string есть `?log=0`, запись
не создаётся. Миниатюры изображений и PDF iframe используют `log=0`, чтобы не
засорять историю изменений.

### Архивирование

Архивирование — это soft delete. `_archive_file()` переносит физический файл в
папку `archive/` внутри сделки, если файл существует, затем выставляет:

- `is_archived=True`
- `archived_at=<now>`;
- `archived_by=<current user>`;
- `relative_path=<archive-relative-path>`, если перенос был выполнен.

Архивные файлы скрыты из обычных списков, потому что выборки используют
`is_archived=False`.

### Bulk-действия

Bulk-действия ограничены одним источником и применяются только к выбранным
неархивным файлам той же сделки:

- `archive` — архивирует каждый выбранный файл и пишет по одному `files.event`
  на файл.
- `download` — возвращает ZIP в памяти с именем
  `deal-<deal_id>-<source>-files.zip` и пишет `download_zip` со списком file ID.
- `preview` есть в backend и открывает первый выбранный файл, но текущий шаблон
  не выводит bulk-кнопку preview.

## Вложения задач

При создании задачи по сделке `DealTaskCreateForm` может ссылаться на
существующий `ProjectFile`. `tasks.views._copy_project_file_to_task_attachment()`
копирует этот файл в `MEDIA_ROOT/task_attachments/` и сохраняет путь в
`Task.attachment`.

Важные ограничения:

- У задачи хранится отдельная копия, а не live-ссылка на путь `ProjectFile`.
- Если исходного файла нет на диске, копия вложения не создаётся.
- Открытие вложения задачи отдаёт файл из `MEDIA_ROOT`, а не из
  `CRM_FILES_ROOT`.

## PDF-записи, созданные плагином

`POST /api/plugin/project-versions/` принимает `plan_pdf_filename`. Текущая
реализация очищает имя файла, сохраняет ожидаемый путь версии в
`ProjectVersion.plan_pdf_path` и создаёт `ProjectFile` с полями:

- `source=designer`
- `category=pdf`
- `project_version=<created version>`
- `size_bytes=0`

Endpoint пока не принимает и не записывает байты PDF. Пока плагин ArchiCAD или
другой backend-шаг не положит файл в `versions/v<version_number>/plan/`,
открытие такого `ProjectFile` может вернуть 404.

## Troubleshooting

### Загруженный файл возвращает 404

1. Проверь `ProjectFile.relative_path` в Django admin.
2. Убедись, что `CRM_FILES_ROOT / relative_path` существует на сервере.
3. Проверь, что файл не архивирован: архивные записи не проходят фильтр
   `open_project_file()`.

### Пользователь получает 403 на файловое действие

Проверь `source` файла и `role` пользователя. Только `head` и `admin` имеют
доступ к источникам `client` и `sales`; все аутентифицированные роли имеют
доступ к `designer`.

### В карточке сделки нет секций client или sales

Для не-руководящих ролей это ожидаемо. `_files_context()` убирает недоступные
источники до рендера файлового блока.

### У задачи нет вложения

Если задача создавалась из `ProjectFile`, проверь, что исходный файл существовал
на диске в момент создания задачи. Копирование в `MEDIA_ROOT/task_attachments/`
выполняется best-effort и пропускается, если исходного пути нет.

### Перенос `CRM_FILES_ROOT`

Так как пути в БД относительные, перенос `CRM_FILES_ROOT` безопасен только при
копировании того же относительного дерева в новое место.
