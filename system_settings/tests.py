from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from deals.models import Deal, ProjectVersion

from .models import IntegrationToken, SystemConfig


class SystemSettingsAccessTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.head = user_model.objects.create_user(
            username='head-settings',
            password='pass1234',
            role='head',
        )
        self.manager = user_model.objects.create_user(
            username='manager-settings',
            password='pass1234',
            role='manager',
        )

    def test_leadership_can_open_system_settings(self):
        self.client.force_login(self.head)
        response = self.client.get(reverse('settings_home'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('settings_employees'))

    def test_manager_cannot_open_system_settings(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('settings_home'))
        self.assertEqual(response.status_code, 403)

    def test_business_settings_persist_values(self):
        self.client.force_login(self.head)
        response = self.client.post(
            reverse('settings_business'),
            {
                'default_margin_percent': '35.5',
                'stale_deal_days': '10',
                'task_reminder_hours': '12',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            SystemConfig.objects.get(
                key=SystemConfig.Key.DEFAULT_MARGIN_PERCENT,
            ).value,
            '35.5',
        )


class IntegrationTokenApiTests(APITestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create_user(
            username='integration-owner',
            password='pass1234',
            role='head',
        )
        self.token = IntegrationToken.create_token(
            name='ArchiCAD',
            owner=self.owner,
            created_by=self.owner,
        )
        self.url = reverse('plugin_project_versions_create')
        self.payload = {
            'project_code': '5МД Тест Интеграция',
            'module_count': 5,
            'source': 'archicad',
            'objects': [
                {
                    'guid': 'GUID-1',
                    'type': 'wall',
                    'params': {'length_mm': 1000},
                },
            ],
        }

    def test_plugin_api_accepts_integration_token(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.key}')
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        deal = Deal.objects.get(project_code_normalized='5мд тест интеграция')
        version = deal.versions.get(version_number=1)
        self.assertEqual(version.source, ProjectVersion.Source.ARCHICAD)

    def test_token_last_used_at_is_updated(self):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {self.token.key}')
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 201)
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)
