# Задачи менеджера

Операционный гид по созданию, списку и закрытию задач. Модель — `tasks.Task`; UI живёт на карточке сделки и на `/tasks/`.

## Назначение

Задача привязана к сделке (FK, nullable в модели, но UI создания всегда ставит `deal`). Исполнитель, срок, опциональный файл. Список `/tasks/` показывает **только задачи текущего пользователя как assignee**.

Напоминания по `SystemConfig.task_reminder_hours` **не реализованы**: ключ есть в настройках (`/settings/business/`), handler в `run_platform_jobs` нет.

## Маршруты

| Method | Path | View | Кто видит |
| --- | --- | --- | --- |
| GET | `/tasks/` | `tasks.views.TaskListView` | Свои open / done |
| GET/POST | `/deals/<id>/tasks/new/` | `create_task_for_deal` | Любой залогиненный |
| POST | `/tasks/<id>/toggle/` | `toggle_task` | Любой залогиненный (по id) |
| GET | `/tasks/<id>/file/open/` | `open_task_file` | Любой залогиненный (по id) |

Отдельного `is_file_only_role` guard нет: дизайнер может создать задачу со страницы сделки (блок задач на карточке не прячется).

## Модель

`tasks.models.Task`:

| Поле | Смысл |
| --- | --- |
| `deal` | Сделка; в UI создания всегда заполняется |
| `assignee` | Исполнитель; если в форме пусто — ставится `request.user` |
| `title`, `description` | Текст |
| `due_date` | Срок (в шаблоне подписан «Дата выполнения») |
| `attachment` | Файл в `MEDIA_ROOT/task_attachments/` |
| `project_file` | Ссылка на неархивный `ProjectFile` сделки |
| `is_done`, `completed_at` | Закрытие через `mark_done()` |
| `created_at` | Дата постановки |

## Создание

Карточка сделки → «+ Задача» → HTMX `GET /deals/<id>/tasks/new/` в модалку.

POST (`DealTaskCreateForm`):

1. `task.deal = deal`.
2. Пустой assignee → текущий пользователь.
3. Save, затем `_copy_project_file_to_task_attachment`: если выбран `project_file` и нет своего `attachment`, файл копируется в `media/task_attachments/task-<id>-<stem>-<8hex><ext>`.
4. Если есть assignee — `Notification` типа `task_assigned` + WebSocket `notification.created`.
5. `record_domain_event(event_type='task.created')` — тип входит в `TOP_DOMAIN_EVENTS`.
6. Ответ: `includes/deal_tasks_block.html`, заголовок `HX-Trigger: taskCreated`.
7. Невалидная форма → тот же partial формы, HTTP 400.

Queryset исполнителей: все `is_active=True` пользователи. Queryset файлов: `ProjectFile` сделки с `is_archived=False`.

## Список и закрытие

`/tasks/`: `assignee=request.user`, открытые по `due_date`, выполненные по `-completed_at`.

Чекбокс в `task_row.html` шлёт POST на `toggle_task`. `mark_done()` срабатывает **только если задача ещё открыта**. Обратного открытия нет: у выполненной задачи чекбокс `checked disabled`.

`toggle_task` не проверяет, что текущий пользователь — исполнитель. Зная id, любой залогиненный может закрыть чужую задачу. Событие `task.completed` пишется в аудит, но **не** входит в `TOP_DOMAIN_EVENTS`.

## Файлы

`GET /tasks/<id>/file/open/` отдаёт `FileResponse` (`as_attachment=False`). Если `attachment` пуст, но есть `project_file`, перед отдачей снова копирует файл в media. 404, если файла нет на диске.

Путь на диске: `Path(settings.MEDIA_ROOT) / task.attachment.name`. Это **не** `CRM_FILES_ROOT` / `crm_files`.

## Примеры

Создать задачу менеджеру по сделке:

```bash
curl -X POST "http://localhost:8001/deals/1/tasks/new/" \
  -H "Cookie: sessionid=..." \
  -F "csrfmiddlewaretoken=..." \
  -F "title=Согласовать планировку" \
  -F "due_date=2026-09-05" \
  -F "assignee=2"
```

Ожидание: строка в блоке задач сделки, уведомление assignee, `AuditEvent` с `event_type=task.created`.

Закрыть:

```bash
curl -X POST "http://localhost:8001/tasks/12/toggle/" \
  -H "Cookie: sessionid=..." \
  --data "csrfmiddlewaretoken=..."
```

Повторный POST не сбрасывает `is_done`.

## Troubleshooting

| Симптом | Почему | Что проверить |
| --- | --- | --- |
| На `/tasks/` пусто, хотя задачи на сделке есть | Список фильтрует по `assignee=user`, не по роли/сделке | Исполнитель в форме; чужие задачи видны только на карточке сделки |
| Чекбокс не снимается | Toggle только в одну сторону | Переоткрытия в коде нет |
| «Файл задачи» 404 | Копия в media не создалась или файл с диска удалили | `project_file.absolute_path` существует; `MEDIA_ROOT/task_attachments/` |
| Нет напоминаний о сроке | `task_reminder_hours` только хранится в `SystemConfig` | `system_settings/job_handlers.py` — handler нет |
| Нет realtime-колокольчика | Уведомление идёт через Redis Channels | Сервис `redis` в compose, `REDIS_URL` |
| Дизайнер создаёт коммерческие задачи | Нет `is_file_only_role` на task views | Ожидаемое текущее поведение, не баг документации |

## Код

- `tasks/models.py`, `tasks/forms.py`, `tasks/views.py`
- `core/urls.py` — маршруты выше
- `templates/task_list.html`, `templates/includes/deal_tasks_block.html`, `templates/includes/task_row.html`, `templates/includes/task_create_form.html`
- `accounts.events.create_notification`, `system_settings.events.record_domain_event`
