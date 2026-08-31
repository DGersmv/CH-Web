# CH-Web

Внутренняя CRM для компании модульных домов (Django + Postgres + Docker).

## Запуск проекта

1. Убедись, что Docker Desktop запущен (Engine running).
2. Скопируй `.env.example` в `.env` и при необходимости измени значения.
3. Если в значении есть символ `$` (например, в `DJANGO_SECRET_KEY`), экранируй его как `$$`, иначе Docker Compose воспримет это как подстановку переменной.
4. Запусти сервисы:

```bash
docker compose up -d
```
docker compose exec app python manage.py migrate
docker compose restart app

Compose поднимает три сервиса: `db` (Postgres на `localhost:5433`), `redis` (`localhost:6379`, нужен Channels/WebSocket), `app` (Daphne). Приложение доступно на `http://localhost:8001`.

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

Bootstrap и HTMX отдаются **локально** из `static/vendor/` (не с CDN). Если UI без стилей:

```bash
curl -I http://localhost:8001/static/vendor/bootstrap/bootstrap.min.css
curl -I http://localhost:8001/static/vendor/htmx/htmx.min.js
curl -I http://localhost:8001/static/img/logo.jpg
```

Если страница открывается, а колокольчик уведомлений молчит — проверь, что контейнер `redis` healthy и `REDIS_URL=redis://redis:6379/0`.

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

- По умолчанию проект хранит файлы сделки в `crm_files` внутри корня репозитория.
- Переопределить корень можно через переменную окружения `CRM_FILES_ROOT`.
- Файлы раскладываются по структуре клиент/проект/источник (заказчик или проектировщик), пути в БД сохраняются относительными.
- Вложения задач копируются в `media/task_attachments/` (`MEDIA_ROOT`), это отдельное дерево от `CRM_FILES_ROOT`.

## Документация подсистем

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — целевая архитектура и расхождения с кодом.
- [`docs/excel-formula-spec.md`](docs/excel-formula-spec.md) — формулы сметы Excel 1:1.
- [`docs/configurator-draft-workflow.md`](docs/configurator-draft-workflow.md) — draft конфигуратора, save vs recalc, смета.
- [`docs/tasks-workflow.md`](docs/tasks-workflow.md) — задачи на сделке и `/tasks/`.
- [`docs/plugin-api-contract.md`](docs/plugin-api-contract.md) — контракт ArchiCAD plugin.
- [`docs/ch-crm-platform-blueprint.md`](docs/ch-crm-platform-blueprint.md) — platform settings, jobs, events.

## Состояние проекта

Планируемая структура вкладок по этапам:

1. `Переговоры и КП` — объединяет лид / квалификацию и переговоры с коммерческим предложением
2. `Согласования`
3. `Проектирование`
4. `Договор и оплата`
5. `Производство`
6. `Монтаж / Установка`
7. `Сдача клиенту`
