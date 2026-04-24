# CH-Web

Внутренняя CRM для компании модульных домов (Django + Postgres + Docker).

## Запуск проекта

1. Убедись, что Docker Desktop запущен (Engine running).
2. Скопируй `.env.example` в `.env` и при необходимости измени значения.
3. Запусти сервисы:

```bash
docker compose up -d
```

Приложение доступно на `http://localhost:8001`, Postgres проброшен на `localhost:5433`.

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
