# CH-Web

Внутренняя CRM для компании модульных домов (Django + Postgres + Redis + Daphne + Docker).

## Запуск проекта

1. Убедись, что Docker Desktop запущен (Engine running).
2. Скопируй `.env.example` в `.env` и при необходимости измени значения.
3. Если в значении есть символ `$` (например, в `DJANGO_SECRET_KEY`), экранируй его как `$$`, иначе Docker Compose воспримет это как подстановку переменной.
4. Запусти сервисы:

```bash
docker compose up -d
docker compose exec app python manage.py migrate
docker compose restart app
```

Приложение доступно на `http://localhost:8001`, Postgres проброшен на `localhost:5433`.

Если меняли Python-код или `urls.py`, а интерфейс как будто старый, перезапустите приложение (Daphne сам код не подхватывает):

```bash
docker compose restart app
```

После правок шаблонов обычно достаточно обновить страницу в браузере (при необходимости с принудительным сбросом кэша: Ctrl+F5).

### Команды `manage.py` с Windows вне Docker

Тогда `python manage.py migrate` ругается на отсутствие Django: либо активируйте venv с зависимостями (`python -m venv .venv`, затем `.\.venv\Scripts\pip install -r requirements.txt`), либо **выполняйте команды внутри контейнера** (так надёжнее, БД доступна по имени `db`):

```bash
docker compose exec app python manage.py migrate
```
При старте контейнера `app` автоматически выполняются:
- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`

По умолчанию сиды не запускаются автоматически. Для разовой инициализации демо-данных:

```bash
docker compose exec app python manage.py seed_demo_data
```

## Типовая проверка после деплоя на сервер

```bash
docker compose config
docker compose ps
docker compose logs app --tail=120
docker compose exec app python manage.py showmigrations
docker compose exec db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select count(*) from catalog_costitem;"
curl -I http://localhost:8001/static/img/logo.jpg
```

Если UI отображается без стилей или HTMX не реагирует на действия, проверь сборку и наличие локальных vendor-ассетов:

```bash
docker compose exec app python manage.py collectstatic --noinput
curl -I http://localhost:8001/static/vendor/bootstrap/bootstrap.min.css
curl -I http://localhost:8001/static/vendor/htmx/htmx.min.js
```

## Миграции

Накатить миграции:

```bash
docker compose exec app python manage.py migrate
```

Создать миграции после изменений моделей:

```bash
docker compose exec app python manage.py makemigrations
```

## Суперпользователь

Создать суперпользователя:

```bash
docker compose exec app python manage.py createsuperuser
```

Админка: `http://localhost:8001/admin/`

## Файловое хранилище

- По умолчанию проект хранит файлы в `crm_files` внутри корня репозитория (`CRM_FILES_ROOT`).
- Переопределить корень можно через переменную окружения `CRM_FILES_ROOT`.
- Файлы раскладываются по структуре клиент/проект/источник; пути в БД сохраняются относительными.
- Основные папки создаёт `ensure_deal_dirs(...)`: `incoming/client`, `incoming/designer`, `incoming/sales`, `outgoing/client`, `system`, `archive`.
- Источники файлов в интерфейсе: `client`, `designer`, `sales`, `system`; категории определяются по расширению как `photo`, `pdf`, `dwg` или `other`.
- Права доступа сейчас ограничены по источнику: роли `head` и `admin` видят клиентские и sales-файлы, все роли видят designer-файлы, роли `designer` и `production` работают в файловом режиме без коммерческих блоков.
- Загрузка, просмотр, архивирование и ZIP-скачивание записываются в `ChangeLog` как `field_path="files.event"`.

## Расчёт стоимости и конфигуратор

- Основной расчёт находится в `deals/services/calculation_engine.py`, версия схемы: `excel-v1`.
- Черновик расчёта хранится в последней `ProjectVersion` со статусом `draft` в `frozen_data`: `calc_schema_version`, `config_inputs`, `calculation`, `saved_at`.
- HTMX endpoint'ы:
  - `POST /deals/<id>/config/recalc/` — пересчитать форму без фиксации пользовательского черновика.
  - `POST /deals/<id>/config/save/` — сохранить входы, пересчитать смету и записать изменения в `ChangeLog`.
- Санузлы зависят от поля `D37 Количество санузлов`: для каждого санузла создаётся вкладка из шаблона каталога `bathroom_template_v1`, максимум 20 вкладок.
- Дополнительные опции берутся из шаблона `additional_options_template_v1`; строки по умолчанию выключены, пользователь может включить шаблонные позиции или создать ручную строку.
- Итог для клиента в карточке сделки считается как `calculation.totals.with_margin + calculation.additional_options.subtotal`.

## Состояние проекта

В карточке сделки есть навигационные вкладки по этапам. Сейчас это UI-заготовки: они не меняют `Deal.status`, не запускают автоматические переходы и не хранят собственные данные этапа.

1. `Переговоры и КП` — объединяет лид / квалификацию и переговоры с коммерческим предложением
2. `Согласования`
3. `Проектирование`
4. `Договор и оплата`
5. `Производство`
6. `Монтаж / Установка`
7. `Сдача клиенту`

Фактический статус сделки редактируется отдельным контролом `Deal.status` в шапке карточки.

## Дополнительные технические документы

- `ARCHITECTURE.md` — текущая карта сущностей, ролей, интерфейсов и известных разрывов между планом и реализацией.
- `docs/excel-formula-spec.md` — правила расчёта и связь с Excel-строками.
- `docs/plugin-api-contract.md` — контракт входящего API для ArchiCAD-плагина.
