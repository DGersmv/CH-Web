# CH-Web

Внутренняя CRM для компании модульных домов (Django + Postgres + Docker).

## Запуск проекта

Двойной клик по `start.bat` в корне репозитория: Docker + CRM на `http://localhost:8001` и умник на `:7861`.

Поиск планировок — пункт меню **Архив** (`/archive/`) и чат умника. Отдельный сайт Scan_Pdf на `:7860` больше не нужен.

Либо вручную:
2. Скопируй `.env.example` в `.env` и при необходимости измени значения.
3. Если в значении есть символ `$` (например, в `DJANGO_SECRET_KEY`), экранируй его как `$$`, иначе Docker Compose воспримет это как подстановку переменной.
4. Запусти сервисы:

```bash
docker compose up -d
```
docker compose exec app python manage.py migrate
docker compose restart app

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

Если UI отображается без стилей, CSS/JS отдаются с диска (`static/vendor/`), не с CDN:

```bash
curl -I http://localhost:8001/static/vendor/bootstrap/bootstrap.min.css
curl -I http://localhost:8001/static/vendor/htmx/htmx.min.js
docker compose exec app python manage.py collectstatic --noinput
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
- Файлы раскладываются по структуре клиент/проект/источник (заказчик или проектировщик), пути в БД сохраняются относительными.

## Документация

- [ARCHITECTURE.md](ARCHITECTURE.md) — контекст для разработки (роли, модели, умник).
- [docs/service-requests.md](docs/service-requests.md) — сервис / рекламации (`/service/`).
- [docs/umnik-crm-api.md](docs/umnik-crm-api.md) — входящий API умника и чат в CRM.
- [docs/umnik-chat-attachments.md](docs/umnik-chat-attachments.md) — как умник получает файлы чата.
- [docs/telegram-bot.md](docs/telegram-bot.md) — бот диспетчерской.
- [docs/plugin-api-contract.md](docs/plugin-api-contract.md) — контракт ArchiCAD-плагина.
- [docs/excel-formula-spec.md](docs/excel-formula-spec.md) — формулы сметы.
- [docs/ch-crm-platform-blueprint.md](docs/ch-crm-platform-blueprint.md) — модули платформы.

## Состояние проекта

Планируемая структура вкладок по этапам:

1. `Переговоры и КП` — объединяет лид / квалификацию и переговоры с коммерческим предложением
2. `Согласования`
3. `Проектирование`
4. `Договор и оплата`
5. `Производство`
6. `Монтаж / Установка`
7. `Сдача клиенту`

Отдельно от вкладок сделки: меню **Сервис** (`/service/`) — обращения после сдачи
(гарантия, доработка, вопрос). Вкладка «Сервис / Рекламации» на карточке объекта
пока заглушка. Подробности: [docs/service-requests.md](docs/service-requests.md).
