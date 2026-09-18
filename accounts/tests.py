from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from deals.models import Deal, ProjectFile


class RoleAndAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(username='head1', password='pass1234', role='head')
        self.designer = user_model.objects.create_user(username='designer1', password='pass1234', role='designer')
        self.production = user_model.objects.create_user(username='prod1', password='pass1234', role='production')
        self.manager = user_model.objects.create_user(username='manager1', password='pass1234', role='manager')
        self.deal = Deal.objects.create(
            project_code='3МД-Иванов-Пулково',
            module_count=3,
            code_client_name='Иванов',
            code_site_name='Пулково',
            status=Deal.Status.NEW,
        )

    def test_production_role_exists(self):
        roles = {value for value, _ in get_user_model().Role.choices}
        self.assertIn('production', roles)
        self.assertIn('superadmin', roles)

    def test_cannot_assign_superadmin_from_dashboard(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse('dashboard_employee_create'),
            {
                'username': 'hidden_owner',
                'first_name': 'Dmitry',
                'last_name': 'Gerasimov',
                'email': 'owner@example.com',
                'role': 'superadmin',
                'is_active': 'on',
                'password': 'pass1234',
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(get_user_model().objects.filter(username='hidden_owner').exists())

    def test_superadmin_is_hidden_from_dashboard_employee_list(self):
        owner = get_user_model().objects.create_user(
            username='superadmin',
            password='pass1234',
            role='superadmin',
            first_name='Дмитрий',
            last_name='Герасимов',
        )
        self.client.force_login(self.head)
        response = self.client.post(
            reverse('dashboard_employee_create'),
            {
                'username': 'visible_emp',
                'first_name': 'Visible',
                'last_name': 'Employee',
                'email': 'visible@example.com',
                'role': 'manager',
                'is_active': 'on',
                'password': 'pass1234',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, owner.username)
        self.assertNotContains(response, 'superadmin')
        self.assertContains(response, 'visible_emp')
        update = self.client.post(
            reverse('dashboard_employee_update', kwargs={'user_id': owner.id}),
            {'role': 'manager', 'is_active': 'on'},
        )
        self.assertEqual(update.status_code, 404)
        owner.refresh_from_db()
        self.assertEqual(owner.role, 'superadmin')

    def test_head_can_create_employee_from_dashboard(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse('dashboard_employee_create'),
            {
                'username': 'new_emp',
                'first_name': 'New',
                'last_name': 'Employee',
                'email': 'new@example.com',
                'role': 'manager',
                'is_active': 'on',
                'password': 'pass1234',
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(get_user_model().objects.filter(username='new_emp').exists())

    def test_manager_cannot_create_employee_from_dashboard(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('dashboard_employee_create'),
            {
                'username': 'x',
                'first_name': 'x',
                'last_name': 'x',
                'email': 'x@example.com',
                'role': 'manager',
                'password': 'pass1234',
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_designer_is_forbidden_on_cost_summary_page(self):
        self.client.force_login(self.designer)
        response = self.client.get(reverse('deal_cost_summary_page', kwargs={'deal_id': self.deal.id}))
        self.assertEqual(response.status_code, 403)

    def test_production_is_forbidden_on_task_create(self):
        self.client.force_login(self.production)
        response = self.client.get(reverse('deal_task_create', kwargs={'deal_id': self.deal.id}))
        self.assertEqual(response.status_code, 403)

    def test_manager_cannot_open_client_source_file(self):
        project_file = ProjectFile.objects.create(
            deal=self.deal,
            source=ProjectFile.Source.CLIENT,
            category=ProjectFile.Category.PDF,
            relative_path='clients/x/projects/y/incoming/client/docs/test.pdf',
            original_name='test.pdf',
            size_bytes=0,
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse('deal_file_open', kwargs={'file_id': project_file.id}))
        self.assertEqual(response.status_code, 403)


class UmnikCapabilityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(username='cap_admin', password='pass1234', role='admin')
        self.manager = user_model.objects.create_user(username='cap_mgr', password='pass1234', role='manager')
        self.designer = user_model.objects.create_user(username='cap_des', password='pass1234', role='designer')

    def test_admin_can_delete_manager_cannot(self):
        from accounts.permissions import can_delete_deals, can_edit_deals, umnik_capabilities

        self.assertTrue(can_delete_deals(self.admin))
        self.assertTrue(can_edit_deals(self.admin))
        self.assertFalse(can_delete_deals(self.manager))
        self.assertTrue(can_edit_deals(self.manager))
        self.assertFalse(can_edit_deals(self.designer))
        self.assertTrue(umnik_capabilities(self.designer)['can_copy_files'])
        self.assertTrue(umnik_capabilities(self.designer)['can_attach_design_files'])
        self.assertFalse(umnik_capabilities(self.designer)['can_edit'])
        self.assertTrue(umnik_capabilities(self.admin)['can_delete'])
        self.assertFalse(umnik_capabilities(self.manager)['can_delete'])
        self.assertFalse(umnik_capabilities(self.admin)['can_edit_code'])
        self.assertFalse(umnik_capabilities(self.admin)['can_restart_crm'])
        self.assertFalse(umnik_capabilities(self.admin)['is_platform_owner'])

    def test_username_admin_is_not_platform_owner(self):
        from accounts.permissions import is_platform_owner, umnik_capabilities

        named_admin = get_user_model().objects.create_user(
            username='admin', password='pass1234', role='manager',
        )
        superuser = get_user_model().objects.create_user(
            username='rootish', password='pass1234', role='manager',
        )
        superuser.is_superuser = True
        superuser.save(update_fields=['is_superuser'])
        owner = get_user_model().objects.create_user(
            username='superadmin', password='pass1234', role='superadmin',
        )
        self.assertFalse(is_platform_owner(named_admin))
        self.assertFalse(is_platform_owner(self.admin))
        self.assertTrue(is_platform_owner(superuser))
        self.assertTrue(is_platform_owner(owner))
        caps = umnik_capabilities(owner)
        self.assertTrue(caps['can_edit_code'])
        self.assertTrue(caps['can_restart_crm'])
        self.assertTrue(caps['is_platform_owner'])
        self.assertFalse(umnik_capabilities(named_admin)['is_platform_owner'])


class EnsureSuperadminCommandTests(TestCase):
    def test_creates_owner_and_does_not_reset_password_on_second_run(self):
        from django.core.management import call_command

        from accounts.management.commands.ensure_superadmin import (
            SUPERADMIN_EMAIL,
            SUPERADMIN_FIRST_NAME,
            SUPERADMIN_LAST_NAME,
            SUPERADMIN_PASSWORD,
            SUPERADMIN_USERNAME,
        )

        call_command('ensure_superadmin')
        user = get_user_model().objects.get(username=SUPERADMIN_USERNAME)
        self.assertEqual(user.role, 'superadmin')
        self.assertEqual(user.email, SUPERADMIN_EMAIL)
        self.assertEqual(user.first_name, SUPERADMIN_FIRST_NAME)
        self.assertEqual(user.last_name, SUPERADMIN_LAST_NAME)
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.is_staff)
        self.assertTrue(user.check_password(SUPERADMIN_PASSWORD))

        user.set_password('changed-pass')
        user.save(update_fields=['password'])
        call_command('ensure_superadmin')
        user.refresh_from_db()
        self.assertTrue(user.check_password('changed-pass'))
        self.assertEqual(user.role, 'superadmin')

        call_command('ensure_superadmin', reset_password=True)
        user.refresh_from_db()
        self.assertTrue(user.check_password(SUPERADMIN_PASSWORD))


class LoginHeaderTests(TestCase):
    def test_http_login_page_does_not_send_coop_header(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get('Cross-Origin-Opener-Policy'))
