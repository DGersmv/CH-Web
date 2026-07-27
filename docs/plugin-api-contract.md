# Plugin API Contract (Draft)

Этот документ фиксирует контракт обмена между `CH-Archicad` и `CH-Web`.
Главный принцип: контракт хранится в веб-репозитории и является источником правды.

## Endpoint

- Method: `POST`
- URL: `/api/plugin/project-versions/`
- Auth (любой из вариантов):
  - Integration token из `/settings/integrations/`: `Authorization: Bearer <key>` или `Authorization: Token <key>`
  - DRF auth token: `Authorization: Token <drf_token>`
- Content-Type: `application/json`

Токен интеграции привязан к `owner`; при успешной аутентификации обновляется `last_used_at`, а `created_by` плагин-запроса становится этим пользователем. Управление токенами и jobs: [system-settings-and-library.md](system-settings-and-library.md).

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
- Сравнение версий выполняется по `guid`.
- Плагин отправляет конструктивные элементы, влияющие на цену.
- Коммерческие поля (наценка и ручные надбавки) не отправляются плагином.

## Versioning

- Contract version: `v0-draft`
- Breaking changes: повышают версию (`v1`, `v2`, ...)
