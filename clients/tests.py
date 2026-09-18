from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from clients.models import PORTAL_LOGIN_ID_BASE, Client
from deals.models import Deal


class PortalLoginIdTests(TestCase):
    def test_auto_assigns_base_plus_pk(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Тест')
        customer.refresh_from_db()
        self.assertEqual(customer.portal_login_id, str(PORTAL_LOGIN_ID_BASE + customer.pk))

    def test_keeps_custom_login_id(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Тест', portal_login_id='200001')
        customer.refresh_from_db()
        self.assertEqual(customer.portal_login_id, '200001')

    def test_skips_taken_auto_id(self):
        first = Client.objects.create(last_name='Первый', first_name='Клиент')
        next_auto = str(PORTAL_LOGIN_ID_BASE + first.pk + 1)
        first.portal_login_id = next_auto
        first.save(update_fields=['portal_login_id'])
        second = Client.objects.create(last_name='Второй', first_name='Клиент')
        second.refresh_from_db()
        self.assertNotEqual(second.portal_login_id, next_auto)
        self.assertTrue(second.portal_login_id.isdigit())
        self.assertGreaterEqual(len(second.portal_login_id), 4)


class ClientCardPortalTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.user = user_model.objects.create_user(username='mgr_clients', password='pass1234', role='manager')
        self.client.force_login(self.user)

    def _form(self, customer, **overrides):
        data = {
            'company_name': '',
            'last_name': customer.last_name,
            'first_name': customer.first_name,
            'middle_name': '',
            'phone': '',
            'email': '',
            'notes': '',
            'portal_login_id': customer.portal_login_id,
            'portal_password': '',
            'portal_password_confirm': '',
        }
        data.update(overrides)
        return data

    def test_edit_page_shows_portal_block(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Тест')
        response = self.client.get(reverse('client_edit', kwargs={'pk': customer.pk}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Вход в кабинет')
        self.assertContains(response, customer.portal_login_id)
        self.assertContains(response, 'Пароль не задан')
        self.assertContains(response, 'Внутренний № карточки')

    def test_edit_sets_login_id_and_password(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Тест')
        response = self.client.post(
            reverse('client_edit', kwargs={'pk': customer.pk}),
            self._form(
                customer,
                portal_login_id='555001',
                portal_password='secret99',
                portal_password_confirm='secret99',
            ),
        )
        self.assertEqual(response.status_code, 302)
        customer.refresh_from_db()
        self.assertEqual(customer.portal_login_id, '555001')
        self.assertTrue(customer.check_portal_password('secret99'))

    def test_empty_password_does_not_clear_existing(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Тест')
        customer.set_portal_password('keep-me1')
        customer.save(update_fields=['portal_password_hash'])
        response = self.client.post(
            reverse('client_edit', kwargs={'pk': customer.pk}),
            self._form(customer),
        )
        self.assertEqual(response.status_code, 302)
        customer.refresh_from_db()
        self.assertTrue(customer.check_portal_password('keep-me1'))

    def test_login_id_must_be_unique(self):
        Client.objects.create(last_name='Первый', first_name='Клиент', portal_login_id='111111')
        other = Client.objects.create(last_name='Второй', first_name='Клиент')
        response = self.client.post(
            reverse('client_edit', kwargs={'pk': other.pk}),
            self._form(other, portal_login_id='111111'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'уже занят')
        other.refresh_from_db()
        self.assertNotEqual(other.portal_login_id, '111111')

    def test_create_assigns_login_id(self):
        response = self.client.post(
            reverse('client_create'),
            {
                'company_name': '',
                'last_name': 'Новый',
                'first_name': 'Клиент',
                'middle_name': '',
                'phone': '',
                'email': '',
                'notes': '',
                'portal_login_id': '',
                'portal_password': 'abcdef',
                'portal_password_confirm': 'abcdef',
            },
        )
        self.assertEqual(response.status_code, 302)
        customer = Client.objects.get(last_name='Новый', first_name='Клиент')
        self.assertEqual(customer.portal_login_id, str(PORTAL_LOGIN_ID_BASE + customer.pk))
        self.assertTrue(customer.check_portal_password('abcdef'))

    def test_list_shows_portal_login_id(self):
        customer = Client.objects.create(last_name='Ирина', first_name='Список')
        response = self.client.get(reverse('clients'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ID входа')
        self.assertContains(response, customer.portal_login_id)


class ClientPortalLoginTests(TestCase):
    def setUp(self):
        self.customer = Client.objects.create(last_name='Ирина', first_name='Портал')
        self.customer.set_portal_password('client123')
        self.customer.save(update_fields=['portal_password_hash'])
        self.deal = Deal.objects.create(
            project_code='6МД-Тест-Портал',
            module_count=6,
            client=self.customer,
            status=Deal.Status.NEW,
        )

    def test_login_with_portal_id(self):
        response = self.client.post(
            reverse('client_portal_login', kwargs={'deal_id': self.deal.id}),
            {'login_id': self.customer.portal_login_id, 'password': 'client123'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('client_portal_chat', kwargs={'deal_id': self.deal.id}))
        self.assertIn('client_portal_token', response.cookies)

    def test_pk_is_not_accepted_as_login(self):
        response = self.client.post(
            reverse('client_portal_login', kwargs={'deal_id': self.deal.id}),
            {'login_id': str(self.customer.pk), 'password': 'client123'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Неверный ID или пароль', status_code=400)

    def test_otp_code_is_ignored(self):
        response = self.client.post(
            reverse('client_portal_login', kwargs={'deal_id': self.deal.id}),
            {'login_id': self.customer.portal_login_id, 'password': '123456', 'code': '123456'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'Неверный ID или пароль', status_code=400)

    def test_legacy_send_otp_url_still_logs_in(self):
        response = self.client.post(
            reverse('client_portal_send_otp', kwargs={'deal_id': self.deal.id}),
            {'login_id': self.customer.portal_login_id, 'password': 'client123'},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn('client_portal_token', response.cookies)

    def test_entry_has_no_otp_copy(self):
        response = self.client.get(reverse('client_portal_entry', kwargs={'deal_id': self.deal.id}))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ID для входа')
        self.assertNotContains(response, 'код из письма')
        self.assertNotContains(response, 'Подтверждение входа')
