# Plugin API Contract (Draft)

Этот документ фиксирует контракт обмена между `CH-Archicad` и `CH-Web`.
Главный принцип: контракт хранится в веб-репозитории и является источником правды.

## Endpoint

- Method: `POST`
- URL: `/api/plugin/project-versions/`
- Auth: DRF token (заголовок `Authorization: Token <token>`)
- Content-Type: `application/json`
- Handler: `deals.api_views.PluginProjectVersionCreateApi`

## Payload (v0 draft)

```json
{
  "project_code": "3МД Иванов Пулково",
  "module_count": 3,
  "source": "archicad",
  "plan_pdf_filename": "plan_ivanov_v3.pdf",
  "objects": [
    {
      "guid": "AC-OBJ-001",
      "type": "wall",
      "params": {
        "length_mm": 4200,
        "height_mm": 2800,
        "thickness_mm": 200
      }
    }
  ]
}
```

## Required fields

- `project_code` (string)
- `module_count` (integer, range 1..15)
- `source` (`archicad`)
- `objects` (array, не пустой)
- `objects[].guid` (string, уникальный внутри payload)
- `objects[].type` (string)
- `objects[].params` (object)

## Rules

- Каждая отправка из плагина создаёт новую `ProjectVersion`.
- Если `project_code` не найден, сервер создаёт `Deal` со статусом `orphan` и без клиента.
- Если `project_code` найден, но `module_count` отличается, сервер обновляет `Deal.module_count`.
- `frozen_data` новой версии содержит `contract_version: "v0-draft"` и копию полей `project_code`, `module_count`, `source`, `objects`.
- Сравнение версий по `guid` — целевое поведение; текущий endpoint сохраняет payload, но не возвращает diff.
- Плагин отправляет конструктивные элементы, влияющие на цену.
- Коммерческие поля (наценка и ручные надбавки) не отправляются плагином.

## PDF plan handling

`plan_pdf_filename` — это только имя файла, не содержимое PDF. Endpoint:

1. очищает путь до basename (`foo/bar/plan.pdf` -> `plan.pdf`);
2. записывает в `ProjectVersion.plan_pdf_path` относительный путь вида:
   `clients/<client>/projects/<deal>/versions/vN/plan/<filename>`;
3. создаёт `ProjectFile` с `source=designer`, `category=pdf`, `size_bytes=0`.

Файл на диск этим запросом не загружается. До появления отдельного upload endpoint у интеграции должен быть согласованный способ положить PDF в `CRM_FILES_ROOT` по указанному пути или использовать ручную загрузку в карточке сделки.

## Success response

HTTP `201 Created`:

```json
{
  "deal_id": 123,
  "project_code": "3МД Иванов Пулково",
  "project_version_id": 456,
  "version_number": 3,
  "created_deal": false
}
```

`created_deal=true` означает, что CRM не нашла сделку по нормализованному `project_code` и создала orphan-сделку.

## Validation errors

HTTP `400 Bad Request`:

```json
{"detail": "module_count is required and must be integer in range 1..15."}
```

Основные ограничения:

- payload должен быть JSON object;
- `project_code` — непустая строка;
- `module_count` — integer `1..15`;
- `source` — строго `archicad`;
- `objects` — непустой массив;
- `objects[].guid` — непустая строка, уникальная внутри payload;
- `objects[].type` — непустая строка;
- `objects[].params` — object;
- `plan_pdf_filename`, если передан, должен быть строкой.

## Versioning

- Contract version: `v0-draft`
- Breaking changes: повышают версию (`v1`, `v2`, ...)
