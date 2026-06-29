# Plugin API Contract (Draft)

Этот документ фиксирует контракт обмена между `CH-Archicad` и `CH-Web`.
Главный принцип: контракт хранится в веб-репозитории и является источником правды.

## Endpoint

- Method: `POST`
- URL: `/api/plugin/project-versions/`
- Auth: DRF token (заголовок `Authorization: Token <token>`)
- Content-Type: `application/json`
- Django view: `deals.api_views.PluginProjectVersionCreateApi`

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

## Success response

Status: `201 Created`

```json
{
  "deal_id": 42,
  "project_code": "3МД Иванов Пулково",
  "project_version_id": 101,
  "version_number": 3,
  "created_deal": false
}
```

## Validation errors

Status: `400 Bad Request`

```json
{
  "detail": "module_count is required and must be integer in range 1..15."
}
```

Текущие проверки:

- payload должен быть JSON-объектом;
- `project_code` — непустая строка;
- `module_count` — integer в диапазоне 1..15;
- `source` — строго `archicad`;
- `objects` — непустой массив;
- каждый объект должен иметь непустые `guid`, `type` и объект `params`;
- `guid` должен быть уникален внутри одного payload;
- `plan_pdf_filename`, если передан, должен быть строкой.

## Rules

- Каждая отправка из плагина создаёт новую `ProjectVersion`.
- Плагин отправляет конструктивные элементы, влияющие на цену.
- Коммерческие поля (наценка и ручные надбавки) не отправляются плагином.
- Сделка ищется по `project_code_normalized` (lowercase + сжатие пробелов). Если сделки нет, API создаёт orphan-сделку со статусом `orphan` и `module_count` из payload.
- Если сделка найдена, но `module_count` отличается от payload, API обновляет `Deal.module_count`.
- Новая версия создаётся через `Deal.create_new_version(source='archicad')`; номер версии увеличивается на 1 относительно последней версии сделки.
- `frozen_data` версии получает `contract_version`, `project_code`, `module_count`, `source` и исходный массив `objects`.
- `plan_pdf_filename` сейчас не загружает файл. API только нормализует имя файла, записывает ожидаемый относительный путь в `ProjectVersion.plan_pdf_path` и создаёт `ProjectFile` c `size_bytes=0`, `source=designer`, `category=pdf`.
- Подробный diff версий по `guid` и расчёт стоимостной разницы пока не реализованы в этом endpoint'е.

## File side effect for `plan_pdf_filename`

Если передано:

```json
{
  "plan_pdf_filename": "plans/ivanov-v3.pdf"
}
```

сервер отбросит путь и сохранит только имя `ivanov-v3.pdf`. Ожидаемый файл будет привязан к версии по относительному пути:

```text
clients/<client-or-unknown>/projects/<deal>/versions/v<version_number>/plan/ivanov-v3.pdf
```

Это запись-указатель для рабочего пространства файлов. Сам PDF должен быть передан отдельным механизмом; текущий JSON endpoint не принимает multipart/body файла.

## Versioning

- Contract version: `v0-draft`
- Breaking changes: повышают версию (`v1`, `v2`, ...)
