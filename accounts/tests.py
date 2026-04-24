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
