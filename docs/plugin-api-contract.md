# Plugin API Contract (Draft)

Этот документ фиксирует контракт обмена между `CH-Archicad` и `CH-Web`.
Главный принцип: контракт хранится в веб-репозитории и является источником правды.

## Endpoint

- Method: `POST`
- URL: `/api/plugin/project-versions/`
- Auth: DRF token (заголовок `Authorization: Token <token>`)
- Content-Type: `application/json`

## Payload (v0 draft)

```json
{
  "project_code": "3МД-Иван-Пулково",
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

- Каждая успешная отправка из плагина создаёт новую `ProjectVersion` с `source = archicad`.
- Если `project_code` не найден, CRM создаёт orphan-сделку (`Deal.status = orphan`) без клиента.
- Если сделка найдена, но `module_count` отличается, CRM обновляет `Deal.module_count`.
- `objects[].guid` должен быть уникален внутри одного payload.
- Коммерческие поля (наценка, ручной конфигуратор, санузлы, дополнительные опции) не отправляются плагином.
- Плагин отправляет конструктивные элементы, но текущий серверный endpoint только сохраняет JSON payload; автоматического расчёта цены по `objects[]` пока нет.

## Saved data

`ProjectVersion.frozen_data` для plugin payload сохраняется в отдельном от ручного конфигуратора формате:

```json
{
  "contract_version": "v0-draft",
  "project_code": "3МД-Иван-Пулково",
  "module_count": 3,
  "source": "archicad",
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

Этот JSON не содержит `calc_schema_version`, `config_inputs` или `calculation`; эти поля относятся к ручному Excel-конфигуратору.

## Plan PDF filename

`plan_pdf_filename` сейчас является только именем файла:

- API нормализует имя и записывает путь в `ProjectVersion.plan_pdf_path`;
- создаётся `ProjectFile` с `source = designer`, `category = pdf`, `size_bytes = 0`;
- бинарная загрузка PDF в этом endpoint пока не реализована.

## Response

Успешный ответ (`201 Created`):

```json
{
  "deal_id": 12,
  "project_code": "3МД-Иван-Пулково",
  "project_version_id": 34,
  "version_number": 2,
  "created_deal": false
}
```

`created_deal = true` означает, что CRM создала новую orphan-сделку по входящему `project_code`.

Ошибки валидации возвращают `400 Bad Request`:

```json
{
  "detail": "objects[].guid must be unique inside payload."
}
```

## Not implemented in v0 draft

- Сравнение версий по GUID-ам.
- Превращение diff-а в денежную разницу.
- Маппинг `objects[]` в `DealConfiguratorForm.config_inputs`.
- Multipart или binary upload PDF через этот endpoint.

## Versioning

- Contract version: `v0-draft`
- Breaking changes: повышают версию (`v1`, `v2`, ...)
