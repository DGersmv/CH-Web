# Project Files Runbook

Файловое хранилище сделки хранит документы, планы и фотографии рядом с CRM, а в БД сохраняет только относительные пути.

Источник поведения:
- `deals/models.py` (`ProjectFile`)
- `deals/views.py` (`upload_project_file`, `open_project_file`, `archive_project_file`, `bulk_project_file_action`)
- `deals/services/storage_paths.py`
- `accounts/permissions.py`

## Storage root

Корень задаётся переменной `CRM_FILES_ROOT`.

Если переменная не задана, используется:

```text
<repo>/crm_files
```

`ProjectFile.relative_path` всегда хранится относительно этого корня. Абсолютный путь вычисляется как:

```python
get_files_root() / project_file.relative_path
```

## Directory layout

Для сделки создаются каталоги:

```text
clients/<client-id-and-name>/projects/<deal-id-and-code>/
  incoming/
    client/
      photos/
      docs/
    designer/
      plans_pdf/
      dwg/
      reference/
    sales/
      photos/
      docs/
  outgoing/
    client/
  system/
  archive/
  versions/
    v<N>/
      plan/
      quote/
```

Если сделка не привязана к клиенту, используется сегмент `clients/client-unknown`.

## File sources and categories

`ProjectFile.source`:

- `client`
- `designer`
- `sales`
- `system`

`ProjectFile.category` определяется по расширению при ручной загрузке:

- images (`.jpg`, `.jpeg`, `.png`, `.webp`, `.gif`) -> `photo`
- `.pdf` -> `pdf`
- `.dwg`, `.dxf` -> `dwg`
- всё остальное -> `other`

Имя файла нормализуется удалением `/` и `\`, затем сохраняется с префиксом:

```text
YYYYMMDD_HHMMSS_<source>_<category>_<original_name>
```

## Access rules

Текущие правила из `accounts/permissions.py`:

- `head` и `admin` видят источники `client`, `sales`, `designer`, `system`;
- `manager` видит `designer`;
- `designer` и `production` считаются file-only ролями и видят `designer`;
- источники `client` и `sales` доступны только руководящим ролям (`head`, `admin`).

Эти правила применяются при загрузке, открытии, архивировании и bulk-действиях.

## User workflows

### Upload

Endpoint UI:

```text
POST /deals/<deal_id>/files/upload/
```

Форма передаёт `source` и `upload`. Сервер:

1. проверяет права на выбранный source;
2. создаёт каталоги сделки;
3. определяет category по расширению;
4. пишет файл на диск;
5. создаёт `ProjectFile`;
6. пишет `ChangeLog` с `field_path="files.event"` и action `upload`.

### Open / preview

```text
GET /deals/files/<file_id>/open/
```

Файл отдаётся inline через `FileResponse`. По умолчанию открытие логируется как action `download`. Чтобы не писать лог (например, для внутреннего preview), можно передать:

```text
?log=0
```

### Archive

```text
POST /deals/files/<file_id>/archive/
```

Если файл существует на диске, он переносится в каталог `archive/` текущей сделки. Запись `ProjectFile` остаётся в БД, но получает:

- `is_archived=True`
- `archived_at`
- `archived_by`

### Bulk actions

```text
POST /deals/<deal_id>/files/<source>/bulk/
```

Поддерживаются actions:

- `archive` — архивирует выбранные файлы;
- `preview` — открывает первый выбранный файл;
- `download` — отдаёт zip `deal-<id>-<source>-files.zip`.

## Plugin caveat

`POST /api/plugin/project-versions/` не загружает PDF. Если передан `plan_pdf_filename`, endpoint только создаёт относительный путь версии `versions/v<N>/plan/<filename>` и `ProjectFile` с `size_bytes=0`.

До появления отдельного upload endpoint интеграция ArchiCAD должна отдельно положить файл в ожидаемый путь под `CRM_FILES_ROOT` или оператор должен загрузить файл вручную в карточке сделки.

## Operational checks

```bash
docker compose exec app python manage.py shell -c "from django.conf import settings; print(settings.CRM_FILES_ROOT)"
docker compose exec app python manage.py shell -c "from deals.models import ProjectFile; print(ProjectFile.objects.filter(is_archived=False).count())"
docker compose exec app python manage.py shell -c "from deals.models import ProjectFile; print([f.id for f in ProjectFile.objects.filter(size_bytes=0)[:20]])"
```

Common pitfalls:

- `CRM_FILES_ROOT` должен быть доступен на запись пользователю контейнера `app`.
- При переносе CRM на другой сервер нужно переносить и Postgres, и каталог `CRM_FILES_ROOT`; одной базы недостаточно.
- Относительные пути в БД нельзя менять вручную без синхронного перемещения файлов на диске.
