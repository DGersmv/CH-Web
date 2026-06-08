# CH-Web

Внутренняя CRM для компании модульных домов (Django + Postgres + Redis + Docker).

## Документация

- `docs/developer-guide.md` — ежедневный workflow разработки, runtime stack, тесты, troubleshooting.
- `ARCHITECTURE.md` — доменная модель, роли и бизнес-правила.
- `docs/excel-formula-spec.md` — расчет стоимости и связанные UI-потоки.
- `docs/plugin-api-contract.md` — REST API для ArchiCAD-плагина.

## Запуск проекта

1. Убедись, что Docker Desktop запущен (Engine running).
2. Скопируй `.env.example` в `.env` и при необходимости измени значения.
3. Если в значении есть символ `$` (например, в `DJANGO_SECRET_KEY`), экранируй его как `$$`, иначе Docker Compose воспримет это как подстановку переменной.
4. Запусти сервисы:

```bash
docker compose up -d
docker compose logs app --tail=120
```

Приложение доступно на `http://localhost:8001`, Postgres проброшен на `localhost:5433`, Redis — на `localhost:6379`.

Контейнер `app` запускает Django через Daphne/ASGI и перед стартом выполняет:

- `python manage.py migrate --noinput`
- `python manage.py collectstatic --noinput`
- `python manage.py seed_demo_data`, если `DJANGO_SEED_DEMO_DATA=1`, `true` или `True`

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

По умолчанию сиды не запускаются автоматически. Для разовой инициализации демо-данных:

```bash
docker compose exec app python manage.py seed_demo_data
```

Сид идемпотентный: создает демо-пользователей `ivanov`, `petrov`, `sidorov`, `boss` (пароль `demo12345` только если у пользователя еще нет usable password), клиентов, сделки по статусам, версии, задачи и базовые позиции каталога.

## Тесты

```bash
docker compose exec app python manage.py test
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

Если UI отображается без стилей, проверь, что локальная статика собрана и отдается:

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

- По умолчанию проект хранит файлы в `crm_files` внутри корня репозитория.
- Переопределить корень можно через переменную окружения `CRM_FILES_ROOT`.
- Файлы раскладываются по структуре `clients/{client}/projects/{deal}/...`, пути в БД сохраняются относительными (`ProjectFile.relative_path`).
- Для сделки создаются каталоги:
  - `incoming/client/photos|docs`
  - `incoming/designer/plans_pdf|dwg|reference`
  - `incoming/sales/photos|docs`
  - `outgoing/client`
  - `system`
  - `archive`
- Источники файлов: `client`, `designer`, `sales`, `system`. Роли `head`/`admin` видят клиентские и sales-файлы; `designer` видит файлы проектировщика; `production` — file-only роль и не меняет сделку/стоимость.
- Удаление в UI — это архивирование: файл переносится в `archive`, запись помечается `is_archived=True`, событие пишется в `ChangeLog`.

## Состояние проекта

На странице сделки уже есть оболочка вкладок `templates/deal_detail.html`. Контент вкладок пока placeholder; рабочие блоки сделки (стоимость, файлы, задачи, история изменений) расположены рядом с ними.

Структура вкладок по этапам:

1. `Переговоры и КП` — объединяет лид / квалификацию и переговоры с коммерческим предложением
2. `Согласования`
3. `Проектирование`
4. `Договор и оплата`
5. `Производство`
6. `Монтаж / Установка`
7. `Сдача клиенту`

Статусы `Deal.Status` (`new`, `qualified`, `sent_quote`, `contract`, `prepayment`, `production`, `installation`, `delivered`, `lost`) пока не переключают вкладку автоматически. Если добавляете поведение этапов, синхронизируйте его с `deals/views.py`, `core/views.py::DealDetailView` и этой секцией.
