# Роли и доступ

Кто что может в CRM. Источник правды — `accounts/permissions.py` и проверки во views. Намерения в `ARCHITECTURE.md` шире, чем то, что код реально закрывает.

Роли проектировщика и производства в коде не различаются: обе попадают в `is_file_only_role`. Ответственный по сделке (`Deal.assigned_manager`) на доступ не влияет.

## Роли

| Код | Кто | Как появляется |
|---|---|---|
| `manager` | Менеджер | Роль по умолчанию у новой учётки |
| `designer` | Проектировщик | Назначает руководство |
| `production` | Производство | Назначает руководство |
| `head` | Руководитель | Назначает руководство |
| `admin` | Админ-сотрудник | Назначает руководство. Это не владелец и не Django `is_staff` |
| `superadmin` | Владелец системы | Только `python manage.py ensure_superadmin`. В списке сотрудников роли нет |

`ensure_superadmin` всегда пишет логин `superadmin`, роль `superadmin`, `is_superuser=True`, `is_staff=True`. Переменная `PLATFORM_OWNER_USERNAME` на эту команду не влияет: её читает процесс умника, если CRM не ответила `whoami`.

Форма сотрудников (`EmployeeCreateForm` / `EmployeeUpdateForm`) принимает только `manager`, `designer`, `production`, `admin`, `head`. Пароль задаётся при создании. `is_staff` форма не ставит, поэтому роль `admin` сама по себе не открывает `/admin/`.

## Предикаты

Все функции в `accounts/permissions.py`.

| Функция | Истина когда |
|---|---|
| `is_leadership` | Роль `head`, `admin` или `superadmin`. Голый Django `is_superuser` без этой роли сюда не входит |
| `is_platform_owner` | Активный пользователь и (`is_superuser` или роль `superadmin`) |
| `is_admin` | `is_superuser` или роль `admin` / `superadmin` |
| `is_file_only_role` | Роль `designer` или `production` |
| `can_edit_deals` | Активный пользователь и не file-only |
| `can_delete_deals` | `is_admin` |
| `can_attach_design_files` | Любой активный аутентифицированный пользователь |
| `can_use_umnik_chat` | Любой активный аутентифицированный пользователь |
| `can_access_file_source` | `designer` — все; `client` и `sales` — только руководство; прочие источники (в том числе `system`) — только руководство |
| `staff_users_qs` | Все пользователи, кроме роли `superadmin` |

`umnik_capabilities(user)` отдаёт умнику словарь: `can_edit` = `can_edit_deals`, `can_delete` = `is_admin`, `can_attach_design_files` / `can_copy_files` = вложения в разделы, `can_edit_code` и `can_restart_crm` = владелец. CRM-эндпоинт `PATCH /api/umnik/deals/<id>/` поле `project_code` по флагу `can_edit_code` не режет: достаточно `can_edit_deals`. Запрет править код держит процесс умника, читая эти флаги.

## Что видно в интерфейсе

Навбар (`templates/base.html`) одинаковый для всех вошедших: Сделки, Задачи, Комнаты, Клиенты, Сервис, Файлы, Архив, поиск, уведомления, чат умника. Пункт **Настройки** только при `is_leadership`.

| Возможность | file-only | manager | head | admin | владелец |
|---|---|---|---|---|---|
| Список и карточка любой сделки | да | да | да | да | да |
| Колонка суммы в списке (`latest_total`) | нет | нет | да | да | да |
| Блок договорной цены, статус, модули, журнал, версии | скрыты | да | да | да | да |
| Файлы источника `designer` | да | да | да | да | да |
| Файлы `client` и `sales` | нет | нет | да | да | да |
| Задачи: создать и открыть форму | да | да | да | да | да |
| Сервис: список и карточка | да | да | да | да | да |
| Сервис: создать, статус, комментарий | редирект на список/карточку | да | да | да | да |
| Главная: лиды, лента, «Новый лид» | заглушка «только файлы» | да | да | да | да |
| `/settings/*` | 403 | 403 | да | да | да |
| Кнопка «Перезапустить CRM» в чате умника | нет | нет | нет | нет | да |
| Удаление сделки из UI | нет кнопки | нет кнопки | нет кнопки | нет кнопки | нет кнопки |

Удаление сделки есть только у умника: `DELETE /api/umnik/deals/<id>/` и `can_delete_deals`. В шаблонах кнопки нет.

Колонка `latest_total` берётся из `frozen_data.calculation` (итог с наценкой плюс доп. опции), не из `Deal.agreed_price`.

## Ответы сервера

File-only на коммерческих POST получает `403` с телом `Not allowed`:

- `POST /deals/<id>/status/`, `/margin/`, `/module-count/`, `/agreed-price/`
- страницы и POST согласований и проектирования, включая открытие файла-основания
- `POST` сообщений клиенту с карточки (`/client-messages/...`)
- `POST /dashboard/leads/create/`

Страницы расчётов (смета, санузлы, доп. опции, электрика, save/recalc конфигуратора) сначала смотрят `CONFIGURATOR_ENABLED`. В `core/settings.py` флага нет, в `deals/views.py` он читается один раз при импорте и по умолчанию `False`. Пока флаг выключен, эти URL делают redirect на карточку (HTMX: `HX-Redirect`) **всем** ролям, и проверка file-only не выполняется.

Руководство на `/settings/` получает `403 Not allowed`, если роли нет в `is_leadership`. Снять с себя `head`/`admin` или выключить последнего активного `head`/`admin` нельзя: `/settings/employees/` отвечает `400`, старый `POST /dashboard/employees/<id>/update/` — `403`. Роль `superadmin` в этот подсчёт не входит и в списке сотрудников не редактируется.

`POST /settings/restart-crm/` без владельца отвечает JSON `403` `forbidden`. Кнопка есть только в `templates/includes/umnik_chat.html` при `can_restart_crm`.

Кабинет заказчика (`/deals/<id>/client-portal/`) — отдельная cookie-сессия клиента, не роль сотрудника. `@login_required` там нет.

## Файлы

На карточке три колонки режет `can_access_file_source` (`deals/views.py`, `_files_context`):

- загрузка, открытие, архив и массовые действия по `client` / `sales` — только руководство;
- источник `designer` доступен и менеджеру, и file-only;
- пункт навбара **Файлы** (`/files/`) редиректит на `/settings/library/`, то есть для менеджера и file-only это `403`.

Сами URL библиотеки проверку руководства не делают: `POST /files/upload/` и `GET /files/assets/<id>/download/` достаточно быть залогиненным.

Вложения согласований и разделов проекта пишутся как `ProjectFile.source=system`. Страницы разделов для file-only закрыты `403`. Умник кладёт PDF в раздел через `can_attach_design_files`, поэтому проектировщик может приложить файл из чата умника и не может сделать то же самое кнопкой на странице проектирования.

## Где ответственный не проверяется

- Список `/deals/`, шапка `GET /search/global/` и карточка `/deals/<id>/` отдают все сделки любому вошедшему.
- Открытие карточки без draft-версии создаёт новую `ProjectVersion` от имени того, кто открыл страницу, включая file-only.
- `POST /deals/<id>/tasks/new/` доступен file-only. Исполнитель — любой активный пользователь, список не прогоняется через `staff_users_qs`.
- `POST /tasks/<id>/toggle/` и `GET /tasks/<id>/file/open/` не проверяют, что задача назначена текущему пользователю. Список `/tasks/` показывает только свои.
- Клиентов создавать и править может любой вошедший (`/clients/new/`, `/clients/<id>/edit/`).
- Сервисный список не фильтруется по роли: file-only читает обращения, писать не может.

## Четыре входа, не одна сессия

| Поверхность | Чем доказывают личность |
|---|---|
| Страницы CRM, `/ws/events/` | Сессия Django. Логин: `/accounts/login/`. С телефона (`iPhone`, `iPad`, `Android`, `Mobile` в User-Agent) редирект в `/app/`, иначе на `/` |
| `POST /api/plugin/project-versions/` | `IntegrationToken` (`Authorization: Token` или `Bearer`) или DRF Token. Роль владельца токена не проверяется: создаётся версия и при необходимости сделка `orphan`. `module_count` здесь `1..15` |
| `GET/POST /api/messages/`, `/api/notifications/` | Только DRF `TokenAuthentication`. Сессия и `IntegrationToken` эти view не принимают |
| `/api/umnik/*` | `Authorization: Bearer <UMNIK_TOKEN>` и заголовок `X-Umnik-Actor: <username>` активного пользователя. Скачивание вложения чата (`/api/umnik/chat-attachments/<id>/`) актёра не требует, только токен. CSRF на этих view выключен |

Комнаты (`/rooms/` и `/app/`, одни и те же view): чужая комната — `404`, не `403`. Контакты и состав новой комнаты берутся из `staff_users_qs`, поэтому владелец в списке контактов не появляется.

## Ловушки

1. Менеджер не входит в руководство. Он меняет сделки, но не видит файлы заказчика и продаж и не открывает настройки. Колонку суммы в списке тоже не видит.
2. Спрятанный блок цены на карточке — это шаблон. View карточки всё равно считает `calculate_config` в памяти для любого зрителя.
3. Форма «написать клиенту» на карточке рисуется и file-only, а POST отвечает `403`.
4. `can_edit_code` не охраняет `update_deal` в CRM. Охрана стоит в умнике (`umnik/crm_api.py`, `umnik/ops.py`).
5. `PLATFORM_OWNER_USERNAME` и логин, который создаёт `ensure_superadmin`, могут разъехаться. Пока CRM отвечает на `whoami`, умник верит флагам. Если `whoami` недоступен, запасной путь сравнивает имя актёра с переменной окружения.
6. Учётка с ролью `admin`, созданная в «Сотрудниках», в Django admin не входит, пока отдельно не выставлен `is_staff`.
7. Голый `is_superuser` с ролью `manager` считается владельцем для перезапуска и не считается руководством для `/settings/`. Команда `ensure_superadmin` ставит оба признака сразу.

## Куда смотреть

| Тема | Путь |
|---|---|
| Предикаты | `accounts/permissions.py` |
| Тесты флагов умника | `accounts/tests.py` |
| Создание владельца | `accounts/management/commands/ensure_superadmin.py` |
| Навбар и редирект логина | `templates/base.html`, `core/views.py` `StaffLoginView` |
| Настройки | `system_settings/decorators.py`, `system_settings/views.py` |
| Действия умника по сделке | `deals/services/umnik_actions.py`, `deals/umnik_api.py` |
| Плагин | `deals/api_views.py` |
| Сообщения и уведомления API | `core/api_views.py` |
