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

Приложение доступно на `http://localhost:8001`, Postgres проброшен на `localhost:5433`.
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

Если UI отображается без стилей, проверь доступ сервера к CDN:

```bash
curl -I https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css
curl -I https://unpkg.com/htmx.org@1.9.12
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
