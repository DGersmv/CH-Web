# PHASE_1_CHECKLIST.md

План проверок и ревизии после завершения Фазы 1 (модели данных и админка).
Делается **до** перехода к Фазе 2 (dashboard).

**Как пользоваться:**
- Идти сверху вниз, отмечать `- [x]` сделанное
- Если проверка падает — фиксить сразу или заносить в `TODO.md`
- Не переходить к Фазе 2, пока уровень A полностью зелёный

**Оценка времени:** 2-4 часа внимательной работы.

---

## УРОВЕНЬ A — Базовое здоровье (критично)

Без этого ничего дальше делать нельзя. Если что-то здесь не работает — значит фундамент сломан.

### A.1 — Контейнеры стабильно запускаются

- [ ] `docker compose down` отработало без ошибок
- [ ] `docker compose up -d` стартует оба контейнера
- [ ] `docker compose ps` показывает `db` и `app` в статусе `Up` (или `running`)
- [ ] Ни один контейнер не падает и не перезапускается циклически (проверь через Docker Desktop или `docker compose logs --tail=50`)

**Что делать если упало:** смотри `docker compose logs db` и `docker compose logs app`, ищи строку с ошибкой.

---

### A.2 — Django запускается и открывается

- [ ] Открывается `http://localhost:8001/admin/` (или твой порт)
- [ ] Логин в админку работает, суперюзер заходит
- [ ] Никаких ошибок в консоли контейнера (`docker compose logs app --tail=50`)

---

### A.3 — Все миграции применены

В терминале:
```
docker compose exec app python manage.py showmigrations
```

- [ ] В столбце `[X]` отмечены ВСЕ миграции (включая django.contrib.auth, accounts, clients, deals)
- [ ] Нет строк `[ ]` — неприменённых миграций
- [ ] Нет warning'ов о несогласованных миграциях

**Что делать если есть [ ]:** `docker compose exec app python manage.py migrate`.

---

### A.4 — Проверка БД изнутри

Подключись к Postgres напрямую и посмотри глазами:
```
docker compose exec db psql -U chcrm_user -d chcrm
```

В psql:
```sql
\dt          -- список таблиц
\d deals_deal     -- структура таблицы Deal
\d deals_projectversion
\d deals_task
\d clients_client
\d deals_costitem  -- или где он лежит
\q
```

- [ ] Все ожидаемые таблицы на месте (`deals_deal`, `deals_projectversion`, `deals_task`, `clients_client`, `deals_costitem`, `deals_changelog`, `accounts_user`)
- [ ] В таблицах видны все поля из плана
- [ ] Есть индексы на ключевых полях (`project_code_normalized`, FK, unique constraints)

---

## УРОВЕНЬ B — Структурная проверка (важно)

Архитектурные решения, которые дорого менять потом, когда в БД реальные данные.

### B.1 — Проверка `on_delete` на внешних ключах

Открой `models.py` каждого app'а, найди все `ForeignKey` и проверь что у каждого явно задан `on_delete`.

**Правильные дефолты:**

| Модель | Поле | on_delete | Почему |
|---|---|---|---|
| Deal | client | SET_NULL | удалили клиента — сделка остаётся |
| Deal | assigned_manager | SET_NULL | уволили менеджера — сделка остаётся |
| Deal | created_by | SET_NULL | тот же принцип |
| ProjectVersion | deal | CASCADE | удалили сделку — все её версии тоже (это ок) |
| ProjectVersion | created_by | SET_NULL | |
| Task | deal | CASCADE | удалили сделку — её задачи тоже |
| Task | assignee | SET_NULL | уволили — задача остаётся |
| ChangeLog | project_version | CASCADE | |
| ChangeLog | changed_by | SET_NULL | |

Проверки:
- [ ] Все FK имеют явный `on_delete`
- [ ] Нет ни одного `CASCADE` на User (иначе удаление юзера снесёт пол-базы)
- [ ] Для nullable FK стоит `null=True, blank=True` — иначе админка не даст выбрать "пусто"

---

### B.2 — UniqueConstraints на месте

- [ ] `Deal.project_code_normalized` — unique (дубли не допустимы)
- [ ] `ProjectVersion (deal, version_number)` — unique_together (две v3 у одной сделки = катастрофа)
- [ ] `CostItem.code` — unique
- [ ] `User.username` — unique (по умолчанию Django это делает)

Проверка через psql:
```sql
\d deals_deal
-- ищи строки с "Unique" и "Indexes"
```

---

### B.3 — Нормализация `project_code`

В админке создай сделку с `project_code = "3МД   Иванов  Пулково"` (лишние пробелы).

- [ ] После сохранения в `project_code_normalized` попало без лишних пробелов и в lowercase
- [ ] Попытка создать вторую сделку с `"3мд иванов пулково"` падает с ошибкой уникальности

**Если не работает:** проверь, что в `save()` модели Deal вызывается нормализация.

---

### B.4 — Защита валидации `module_count`

В админке попробуй создать сделку с `module_count = 0`, потом `module_count = 50`.

- [ ] Обе попытки падают с validation error
- [ ] `module_count = 3` сохраняется

**Что проверить в коде:** должен быть `validators=[MinValueValidator(1), MaxValueValidator(15)]` или подобное.

---

### B.5 — `created_at` и `updated_at` работают автоматически

Создай любую сделку, запиши дату. Измени любое поле, сохрани.

- [ ] `created_at` не изменилась
- [ ] `updated_at` изменилась на текущее время
- [ ] Обе видны в админке

**Что проверить в коде:** `created_at = DateTimeField(auto_now_add=True)`, `updated_at = DateTimeField(auto_now=True)`.

---

### B.6 — Метод `Deal.create_new_version()` работает

В shell:
```
docker compose exec app python manage.py shell
```

```python
from deals.models import Deal
d = Deal.objects.first()
v1 = d.create_new_version(source='manual')
v2 = d.create_new_version(source='manual')
v3 = d.create_new_version(source='manual')
print([v.version_number for v in d.projectversion_set.all().order_by('version_number')])
```

- [ ] Печатает `[1, 2, 3]` (или с учётом ранее созданных версий — последовательные числа)
- [ ] Версии появились в админке внутри inline этой сделки

---

### B.7 — Метод `Task.mark_done()` работает

В shell:
```python
from deals.models import Task
from django.utils import timezone

t = Task.objects.create(title="Тест", due_date=timezone.now().date(), assignee_id=1)
t.mark_done()
t.refresh_from_db()
print(t.is_done, t.completed_at)
```

- [ ] Печатает `True 2026-04-23 ...` (сегодняшняя дата со временем)
- [ ] `completed_at` не None

---

### B.8 — Админка удобна для работы

Открой админку, пройдись по каждой модели:

**DealAdmin:**
- [ ] `list_display` показывает: project_code, client, module_count, status, assigned_manager, updated_at
- [ ] `list_filter` есть: status, module_count, assigned_manager
- [ ] `search_fields` включает: project_code, client__full_name
- [ ] Inline ProjectVersion виден внутри сделки

**ClientAdmin:**
- [ ] Поиск по ФИО, телефону, email

**TaskAdmin:**
- [ ] Фильтры: is_done, assignee, due_date
- [ ] Просроченные задачи как-то подсвечены (хорошо бы, но не обязательно)

**CostItemAdmin:**
- [ ] Фильтр по category
- [ ] Поиск по name_ru

**ChangeLogAdmin:**
- [ ] Доступен только для просмотра (не должно быть возможности создавать/менять через админку — это системная таблица). Проверь: `has_add_permission = False`, `has_change_permission = False`.

---

## УРОВЕНЬ C — Данные для dashboard (подготовка)

Фаза 2 (dashboard) без данных не разработается. Набей тестовую базу.

### C.1 — Пользователи

Создай через админку:
- [ ] 1 суперюзер (уже есть)
- [ ] 2 менеджера (role=manager): например `ivanov`, `petrov`
- [ ] 1 проектировщик (role=designer): `sidorov`
- [ ] 1 руководитель (role=head): `boss`

---

### C.2 — Клиенты

- [ ] Минимум 5 клиентов с разными ФИО, телефонами, локациями

Пример:
```
1. Иванов Иван Иванович, +7 900 111-22-33, участок в Пулково
2. Петров Пётр Петрович, +7 911 222-33-44, участок в Токсово
3. Сидоров Сидор Сидорович, +7 921 333-44-55, Петергоф
4. ООО "Рога и копыта" (юрлицо)
5. Козлов, без email
```

---

### C.3 — Сделки на разных стадиях

Минимум **8-10 сделок**, покрывающие:
- [ ] Orphan (1 шт) — без менеджера и без клиента
- [ ] New (1 шт) — свежий лид, менеджера нет
- [ ] Qualified (2 шт) — в работе, менеджер назначен
- [ ] Sent_quote (2 шт) — КП отправлено
- [ ] Contract (1 шт) — договор подписан
- [ ] Production (1 шт) — в производстве
- [ ] Delivered (1 шт) — сдан
- [ ] Lost (1 шт) — проиграна

По module_count:
- [ ] Минимум 2 сделки с module_count=3
- [ ] Минимум 2 с module_count=5
- [ ] 1 с module_count=7
- [ ] 1 с module_count=11 (рекорд)

**Хитрый момент для теста dashboard:** у 2-3 сделок **вручную поменяй `updated_at` на дату 10+ дней назад** (через админку или shell), чтобы потом проверить блок "сделки без движения > 7 дней".

Через shell:
```python
from deals.models import Deal
from datetime import timedelta
from django.utils import timezone

d = Deal.objects.get(project_code__contains="Петров")
Deal.objects.filter(pk=d.pk).update(updated_at=timezone.now() - timedelta(days=14))
```

(Используется `.update()`, а не `.save()`, чтобы `auto_now` не перезаписал дату обратно.)

---

### C.4 — Версии проектов

- [ ] У 3-4 сделок создано по 2-3 ProjectVersion разных статусов
- [ ] Минимум 2 версии с `source='archicad'` (для блока "свежие обновления из ArchiCAD")
- [ ] Одна версия со статусом `sent_to_client` (имитация отправленного КП)
- [ ] Остальные в `draft`

---

### C.5 — Задачи

Минимум 15 задач:
- [ ] 5 задач на сегодня (`due_date = today`)
- [ ] 3 задачи просроченные (`due_date` вчера или раньше, `is_done=False`)
- [ ] 3 задачи на будущее (следующая неделя)
- [ ] 4 задачи выполненные (`is_done=True`)

Раскидать по двум менеджерам, часть привязать к сделкам, часть без deal.

---

### C.6 — Позиции каталога

- [ ] Первые 10-15 позиций из Excel вбиты в CostItem
- [ ] Разные категории представлены (floors, walls, openings, roof)
- [ ] Цены ненулевые

Это ещё не весь каталог — полный импорт сделаем отдельным скриптом в Фазе 5.

---

## УРОВЕНЬ D — Чистота и документация

### D.1 — Git в порядке

- [ ] Все изменения закоммичены
- [ ] `.env` **не** закоммичен (проверь `git log --all --full-history -- .env` — должно быть пусто)
- [ ] `.gitignore` исключает: `.env`, `__pycache__/`, `*.pyc`, `db.sqlite3`, `.venv/`, `/media/`, IDE-файлы (`.idea/`, `.vscode/`)
- [ ] Коммиты осмысленные (не все "wip" или "fix")

---

### D.2 — `TODO.md` актуален

- [ ] Создан файл `TODO.md` в корне
- [ ] Занесены пункты про ProjectVersion:
  - иммутабельность версий sent_to_client / accepted / superseded
  - валидация переходов статусов
  - транзакция в create_new_version
- [ ] Занесены мелочи, которые откладывали "разберёмся потом"

---

### D.3 — Документация проекта

- [ ] `README.md` обновлён: как запустить (`docker compose up -d`), как создать суперюзера, как накатить миграции
- [ ] `ARCHITECTURE.md` актуален, синхронен с реальным кодом
- [ ] Если были архитектурные изменения — обновлены в `ARCHITECTURE.md`

---

## УРОВЕНЬ E — Бэкап перед переходом к Фазе 2

Перед тем, как начнёшь крутить dashboard — сделай контрольную точку.

### E.1 — Резервная копия БД

```bash
docker compose exec db pg_dump -U chcrm_user chcrm > backup_phase1.sql
```

- [ ] Файл `backup_phase1.sql` создан, размер разумный (несколько KB)
- [ ] Файл положен куда-то кроме папки проекта (Google Drive, отдельная папка бэкапов)

**Зачем:** если в Фазе 2 что-то сломаешь необратимо, можно откатиться к этой точке.

---

### E.2 — Git tag

```bash
git tag -a v0.1-phase1 -m "End of Phase 1: models and admin"
git push origin v0.1-phase1  # если используешь удалённый репозиторий
```

- [ ] Tag создан

**Зачем:** удобный ориентир в истории. `git checkout v0.1-phase1` — и ты в точности в этом состоянии.

---

## Финальная проверка — можно переходить к Фазе 2?

Перед переходом задай себе вопросы:

- [ ] Все галочки уровня A проставлены?
- [ ] Критичные пункты уровня B проверены или занесены в TODO?
- [ ] Данных в БД достаточно, чтобы dashboard было что показывать?
- [ ] Бэкап сделан, tag поставлен?

Если на всё "да" — открывай `IMPLEMENTATION_PLAN.md`, Фаза 2, Задача 2.1. Вперёд.

Если где-то "нет" — сначала добей этот пункт.

---

## Отдельная памятка: как эффективно проверять с Cursor

Для Cursor удобнее давать такие запросы:

> Покажи текущий код модели ProjectVersion. Нужно проверить: какой on_delete на FK, есть ли unique_together, автоматически ли заполняется created_at.

> Запусти в shell: `Deal.objects.filter(project_code_normalized='3мд иванов пулково').count()`. Должно вернуть 1 или больше.

Не проси Cursor "проверить всё" — будет размазанный ответ. Проси проверить конкретный пункт этого чеклиста.
