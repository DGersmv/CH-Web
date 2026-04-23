from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from catalog.models import CostItem
from clients.models import Client
from deals.models import Deal, normalize_project_code
from tasks.models import Task


class Command(BaseCommand):
    help = 'Seed idempotent demo data for dashboard development.'

    def handle(self, *args, **options):
        users = self._seed_users()
        clients = self._seed_clients(users['manager_1'])
        deals = self._seed_deals(users, clients)
        self._seed_versions(deals, users['manager_1'])
        self._seed_tasks(users, deals)
        self._seed_cost_items()
        self.stdout.write(self.style.SUCCESS('Demo data seeding completed.'))

    def _seed_users(self):
        User = get_user_model()
        specs = [
            ('ivanov', 'manager', 'ivanov@example.com'),
            ('petrov', 'manager', 'petrov@example.com'),
            ('sidorov', 'designer', 'sidorov@example.com'),
            ('boss', 'head', 'boss@example.com'),
        ]
        result = {}
        for username, role, email in specs:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={'email': email, 'role': role},
            )
            if not created:
                updates = []
                if user.role != role:
                    user.role = role
                    updates.append('role')
                if user.email != email:
                    user.email = email
                    updates.append('email')
                if updates:
                    user.save(update_fields=updates)
            user.is_staff = True
            user.save(update_fields=['is_staff'])
            if not user.has_usable_password():
                user.set_password('demo12345')
                user.save(update_fields=['password'])
            key = f'manager_{1 if username == "ivanov" else 2}' if role == 'manager' else role
            result[key] = user
        return result

    def _seed_clients(self, created_by):
        specs = [
            ('Иванов Иван Иванович', '+7 900 111-22-33', 'ivanov.client@example.com', 'Пулково'),
            ('Петров Пётр Петрович', '+7 911 222-33-44', 'petrov.client@example.com', 'Токсово'),
            ('Сидоров Сидор Сидорович', '+7 921 333-44-55', 'sidorov.client@example.com', 'Петергоф'),
            ('ООО "Рога и копыта"', '+7 812 444-55-66', 'office@roga.example.com', 'Всеволожск'),
            ('Козлов Константин', '+7 931 555-66-77', '', 'Кудрово'),
        ]
        clients = {}
        for full_name, phone, email, location in specs:
            client, _ = Client.objects.get_or_create(
                full_name=full_name,
                defaults={
                    'phone': phone,
                    'email': email,
                    'location': location,
                    'created_by': created_by,
                },
            )
            clients[full_name] = client
        return clients

    def _seed_deals(self, users, clients):
        specs = [
            ('3МД Иванов Пулково', 3, Deal.Status.ORPHAN, None, None),
            ('5МД Петров Токсово', 5, Deal.Status.NEW, None, clients['Петров Пётр Петрович']),
            ('3МД Сидоров Петергоф', 3, Deal.Status.QUALIFIED, users['manager_1'], clients['Сидоров Сидор Сидорович']),
            ('5МД Иванов 2', 5, Deal.Status.QUALIFIED, users['manager_2'], clients['Иванов Иван Иванович']),
            ('7МД Рога Всеволожск', 7, Deal.Status.SENT_QUOTE, users['manager_1'], clients['ООО "Рога и копыта"']),
            ('11МД Козлов Кудрово', 11, Deal.Status.SENT_QUOTE, users['manager_2'], clients['Козлов Константин']),
            ('5МД Контракт Пушкин', 5, Deal.Status.CONTRACT, users['manager_1'], clients['Иванов Иван Иванович']),
            ('3МД Производство Колпино', 3, Deal.Status.PRODUCTION, users['manager_2'], clients['Петров Пётр Петрович']),
            ('5МД Сдано Парголово', 5, Deal.Status.DELIVERED, users['manager_1'], clients['Сидоров Сидор Сидорович']),
            ('7МД Потеря Гатчина', 7, Deal.Status.LOST, users['manager_2'], clients['Козлов Константин']),
        ]
        deals = {}
        for project_code, module_count, status, manager, client in specs:
            normalized = normalize_project_code(project_code)
            deal = Deal.objects.filter(project_code_normalized=normalized).first()
            if deal is None:
                deal = Deal.objects.create(
                    project_code=project_code,
                    module_count=module_count,
                    status=status,
                    assigned_manager=manager,
                    client=client,
                    margin_percent=30,
                )
            updates = []
            if deal.project_code != project_code:
                deal.project_code = project_code
                updates.append('project_code')
            if deal.status != status:
                deal.status = status
                updates.append('status')
            if deal.module_count != module_count:
                deal.module_count = module_count
                updates.append('module_count')
            if deal.assigned_manager_id != (manager.id if manager else None):
                deal.assigned_manager = manager
                updates.append('assigned_manager')
            if deal.client_id != (client.id if client else None):
                deal.client = client
                updates.append('client')
            if updates:
                deal.save(update_fields=updates)
            deals[project_code] = deal

        stale_codes = [
            '5МД Петров Токсово',
            '7МД Рога Всеволожск',
            '3МД Производство Колпино',
        ]
        for code in stale_codes:
            Deal.objects.filter(pk=deals[code].pk).update(updated_at=timezone.now() - timedelta(days=14))
        return deals

    def _seed_versions(self, deals, created_by):
        version_plan = {
            '3МД Сидоров Петергоф': [('manual', 'draft'), ('archicad', 'draft')],
            '7МД Рога Всеволожск': [('archicad', 'draft'), ('manual', 'sent_to_client')],
            '11МД Козлов Кудрово': [('manual', 'draft'), ('manual', 'draft'), ('archicad', 'draft')],
            '5МД Контракт Пушкин': [('manual', 'draft'), ('manual', 'sent_to_client')],
        }
        for code, versions in version_plan.items():
            deal = deals[code]
            for idx, (source, status) in enumerate(versions, start=1):
                pv, _ = deal.versions.get_or_create(
                    version_number=idx,
                    defaults={'source': source, 'status': status, 'created_by': created_by},
                )
                updates = []
                if pv.source != source:
                    pv.source = source
                    updates.append('source')
                if pv.status != status:
                    pv.status = status
                    updates.append('status')
                if pv.created_by_id != created_by.id:
                    pv.created_by = created_by
                    updates.append('created_by')
                if updates:
                    pv.save(update_fields=updates)

    def _seed_tasks(self, users, deals):
        today = timezone.localdate()
        manager_1 = users['manager_1']
        manager_2 = users['manager_2']
        specs = [
            ('Сегодня: перезвонить Иванову', manager_1, deals['3МД Сидоров Петергоф'], today, False),
            ('Сегодня: сверить смету Петров', manager_2, deals['5МД Петров Токсово'], today, False),
            ('Сегодня: согласовать план 7МД', manager_1, deals['7МД Рога Всеволожск'], today, False),
            ('Сегодня: уточнить сроки производства', manager_2, deals['3МД Производство Колпино'], today, False),
            ('Сегодня: отправить документы по контракту', manager_1, deals['5МД Контракт Пушкин'], today, False),
            ('Просрочено: запросить аванс', manager_2, deals['11МД Козлов Кудрово'], today - timedelta(days=2), False),
            ('Просрочено: обновить статус лида', manager_1, None, today - timedelta(days=1), False),
            ('Просрочено: подготовить коммерческое предложение', manager_2, deals['7МД Потеря Гатчина'], today - timedelta(days=3), False),
            ('Будущее: выезд на участок', manager_1, deals['5МД Контракт Пушкин'], today + timedelta(days=5), False),
            ('Будущее: согласовать изменения планировки', manager_2, deals['7МД Рога Всеволожск'], today + timedelta(days=6), False),
            ('Будущее: подтвердить поставку материалов', manager_1, None, today + timedelta(days=7), False),
            ('Выполнено: вводный звонок', manager_2, deals['5МД Петров Токсово'], today - timedelta(days=4), True),
            ('Выполнено: проверка проекта', manager_1, deals['3МД Сидоров Петергоф'], today - timedelta(days=2), True),
            ('Выполнено: отправка КП', manager_2, deals['11МД Козлов Кудрово'], today - timedelta(days=5), True),
            ('Выполнено: финальное согласование', manager_1, None, today - timedelta(days=6), True),
        ]
        for title, assignee, deal, due_date, done in specs:
            task, _ = Task.objects.get_or_create(
                title=title,
                assignee=assignee,
                defaults={'deal': deal, 'due_date': due_date},
            )
            updates = []
            if task.deal_id != (deal.id if deal else None):
                task.deal = deal
                updates.append('deal')
            if task.due_date != due_date:
                task.due_date = due_date
                updates.append('due_date')
            if updates:
                task.save(update_fields=updates)
            if done and not task.is_done:
                task.mark_done()
            if not done and task.is_done:
                task.is_done = False
                task.completed_at = None
                task.save(update_fields=['is_done', 'completed_at'])

    def _seed_cost_items(self):
        specs = [
            ('floor_insulation_150', 'Пол утепление 150мм', 'sqm', 'floors', '1200.00', '700.00'),
            ('floor_insulation_200', 'Пол утепление 200мм', 'sqm', 'floors', '1400.00', '800.00'),
            ('floor_laminate', 'Ламинат', 'sqm', 'floors', '900.00', '500.00'),
            ('wall_frame', 'Каркас стены', 'sqm', 'walls', '2200.00', '1300.00'),
            ('wall_insulation', 'Утепление стен', 'sqm', 'walls', '1100.00', '650.00'),
            ('wall_finish', 'Отделка стен', 'sqm', 'walls', '1500.00', '900.00'),
            ('window_double_glazed', 'Окно двухкамерное', 'pcs', 'openings', '18000.00', '3500.00'),
            ('door_entrance', 'Входная дверь', 'pcs', 'openings', '22000.00', '4500.00'),
            ('roof_metal', 'Кровля металл', 'sqm', 'roof', '1900.00', '1000.00'),
            ('roof_insulation', 'Утепление кровли', 'sqm', 'roof', '1600.00', '900.00'),
            ('plumbing_base', 'Сантехника базовая', 'complex', 'bathroom', '45000.00', '15000.00'),
            ('electrical_wiring', 'Электрика разводка', 'complex', 'engineering', '30000.00', '12000.00'),
        ]
        for code, name_ru, unit, category, price_material, price_work in specs:
            item, _ = CostItem.objects.get_or_create(
                code=code,
                defaults={
                    'name_ru': name_ru,
                    'unit': unit,
                    'category': category,
                    'price_material': price_material,
                    'price_work': price_work,
                },
            )
            updates = []
            if item.name_ru != name_ru:
                item.name_ru = name_ru
                updates.append('name_ru')
            if item.unit != unit:
                item.unit = unit
                updates.append('unit')
            if item.category != category:
                item.category = category
                updates.append('category')
            if str(item.price_material) != price_material:
                item.price_material = price_material
                updates.append('price_material')
            if str(item.price_work) != price_work:
                item.price_work = price_work
                updates.append('price_work')
            if not item.is_active:
                item.is_active = True
                updates.append('is_active')
            if updates:
                item.save(update_fields=updates)
