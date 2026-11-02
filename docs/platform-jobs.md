# Очередь platform jobs

Короткая очередь на таблице `system_settings.PlatformJob`. Отдельного воркера,
cron и сервиса в `docker-compose.yml` нет: строки копятся, пока кто-то вручную
не запустит `run_platform_jobs`.

Код: `system_settings/models.py` (`PlatformJob`), `system_settings/services.py`
(`enqueue_platform_job`), `system_settings/management/commands/run_platform_jobs.py`,
`system_settings/job_handlers.py`, `system_settings/events.py`.

## Как поставить и выполнить

Постановка — только через `enqueue_platform_job`. Статус новой строки всегда
`pending`, `attempts = 0`. `run_after` по умолчанию — `timezone.now()` (`TIME_ZONE`
в настройках — `UTC`).

```python
from system_settings.services import enqueue_platform_job

enqueue_platform_job(job_type='cleanup_expired_portal_access')
```

Запуск (внутри контейнера, чтобы была БД):

```bash
docker compose exec app python manage.py run_platform_jobs
```

Команда без аргументов. Пустая очередь печатает `No pending platform jobs.`
Успех: `SUCCEEDED <job_type>`. Нет обработчика: `No handler: <job_type>`.
Исключение в обработчике: `FAILED <job_type>: <текст ошибки>`.

За один запуск берутся не больше **100** строк: `status=pending` и
`run_after <= now`, порядок `run_after`, затем `created_at`. Остальные ждут
следующего запуска. Строки с `run_after` в будущем не берутся.

`entrypoint.sh` эту команду не вызывает. В compose нет сервиса-воркера.

## Статусы

| Статус | Когда |
|---|---|
| `pending` | Создана, ещё не взята в работу |
| `running` | Обработчик найден, `attempts` уже увеличен, работа ещё идёт или процесс умер |
| `succeeded` | Обработчик вернул управление без исключения |
| `failed` | Нет обработчика или обработчик бросил исключение |

`failed` и `succeeded` команда больше не берёт. Повтора нет: чтобы прогнать
снова, статус нужно вернуть в `pending` (admin или shell). Сама команда этого
не делает.

`attempts` растёт только если обработчик есть, и растёт **до** его вызова,
включая падение с исключением. Если обработчика нет, `attempts` остаётся 0,
`last_error` = `No handler for job type <job_type>`.

Успешный результат дописывается в тот же JSON: `payload["result"]`.
Исключение кладётся в `last_error` как `str(error)`, без traceback.

Статус `running` коммитится отдельной транзакцией до вызова обработчика.
Если процесс убьют после этого, строка останется `running` навсегда, а уже
выполненные записи обработчика не откатятся. Два одновременных запуска не
блокируют строки (`select_for_update` / `skip_locked` нет) и могут взять одни
и те же `pending`.

## Единственный обработчик

`JOB_HANDLERS` содержит один ключ: `cleanup_expired_portal_access`.

Он не читает `job.payload`. Удаляет строки с `expires_at < now`:

- `DealClientPortalOtp`
- `DealClientPortalSession`

`last_seen_at` не смотрит и живые сессии не трогает. В `payload.result`:

```json
{"deleted_otps": 0, "deleted_sessions": 3}
```

Числа — первый элемент ответа `QuerySet.delete()` (сколько объектов удалено).

Кабинет заказчика (`deals/client_portal.py`) по-прежнему создаёт сессию на
**7 суток** (`SESSION_TTL`) и **не** создаёт OTP. `touch_session` обновляет
только `last_seen_at`, срок `expires_at` не продлевает. Вход и так отвергает
сессию с `expires_at <= now`, поэтому очистка — уборка старых строк, а не
контроль доступа. Новые OTP сами не появляются: почту и коды заказчикам не
шлём, таблица осталась от старой схемы.

Ни view, ни сигнал, ни старт контейнера такую задачу не ставят. Обработчик
сработает только если строку создали вручную (shell, Django admin) и затем
запустили команду.

## Follow-up, которого нет

`record_domain_event(..., enqueue_follow_up=True)` после записи `AuditEvent`
ставит job `domain_event_follow_up` с payload:

```json
{
  "event_type": "...",
  "entity_model": "...",
  "entity_id": 1,
  "payload": {}
}
```

Флаг по умолчанию `False`. В коде нет вызова с `enqueue_follow_up=True`,
поэтому такие строки сейчас не создаются. Обработчика на этот `job_type` нет:
если флаг включить, команда пометит задачу `failed` с текстом
`No handler for job type domain_event_follow_up`. Запись аудита при этом уже
сохранена — очередь её не заменяет.

Список из пяти имён на `/settings/integrations/` (`TOP_DOMAIN_EVENTS`) — подпись
на странице, не фильтр постановки в очередь. `record_domain_event` принимает
любую строку `event_type`.

## Где смотреть

| Куда | Что видно | Кто |
|---|---|---|
| `/settings/integrations/`, блок «Последние platform jobs» | 20 последних строк: тип, статус, `run_after`, попытки. `last_error` нет | роли `head`, `admin`, `superadmin` (`leadership_required`). Чужому — HTTP 403 `Not allowed` |
| `/admin/system_settings/platformjob/` | статус, payload, `last_error`, время старта и финиша | Django `is_staff` |

Подписи статусов в таблице настроек — английские verbose names модели
(`Pending`, `Running`, `Succeeded`, `Failed`).

Разобрать завалы:

```python
from system_settings.models import PlatformJob

for job in PlatformJob.objects.filter(status='failed').order_by('-created_at')[:20]:
    print(job.id, job.job_type, job.attempts, job.last_error)
```

Зависший `running` этой выборкой не виден — фильтруйте `status='running'`.

## Настройки, которые очередь не читает

Форма «Бизнес» (`/settings/business/`, тот же доступ руководства) пишет три
ключа `SystemConfig`:

| Ключ | Поле формы | Если строки нет |
|---|---|---|
| `default_margin_percent` | число ≥ 0, до 2 знаков | `'30'` |
| `stale_deal_days` | целое ≥ 1 | `'7'` |
| `task_reminder_hours` | целое ≥ 1 | `'24'` |

`get_default_margin_percent()` читает только маржу и подставляет её **новым**
сделкам в момент создания. Уже созданные сделки эта форма не переписывает.

`stale_deal_days` и `task_reminder_hours` форма сохраняет и показывает снова.
`get_int_system_config` в проекте никем не вызывается: ни напоминаний по
задачам, ни поиска «зависших» сделок нет. Смена этих двух чисел на поведение
CRM не влияет.
