from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from rooms.models import Room
from rooms.services import get_or_create_room, has_umnik, post_message


@override_settings(
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
)
class RoomsMessengerTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.manager = user_model.objects.create_user(username='rm_mgr', password='pass1234', role='manager')
        self.designer = user_model.objects.create_user(
            username='rm_des', password='pass1234', role='designer', first_name='Ира'
        )

    def test_iphone_login_opens_rooms(self):
        ua = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15'
        self.client.get(reverse('login'), HTTP_USER_AGENT=ua)
        response = self.client.post(
            reverse('login'),
            {'username': 'rm_mgr', 'password': 'pass1234'},
            HTTP_USER_AGENT=ua,
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, '/app/')

    def test_login_required_for_rooms_and_app(self):
        rooms = self.client.get(reverse('rooms:list'))
        self.assertEqual(rooms.status_code, 302)
        self.assertIn('/accounts/login/', rooms.url)
        app = self.client.get(reverse('app:list'))
        self.assertEqual(app.status_code, 302)
        self.assertIn('/accounts/login/', app.url)
        self.assertIn('next=', app.url)
        self.assertIn('/app/', app.url)

    def test_create_chat_with_colleague(self):
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('rooms:new'),
            {'user_ids': [str(self.designer.id)]},
        )
        self.assertEqual(response.status_code, 302)
        room_id = int(response.url.rstrip('/').split('/')[-1])
        detail = self.client.get(reverse('rooms:detail', args=[room_id]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Ира')

    def test_same_people_reopen_same_room(self):
        room1 = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=False)
        room2 = get_or_create_room(creator=self.designer, user_ids=[self.manager.id], with_umnik=False)
        self.assertEqual(room1.id, room2.id)

    @patch('rooms.services.ask_umnik_chat', return_value={'ok': True, 'answer': 'Принял файл.', 'attachments': []})
    def test_umnik_only_chat_and_direct_reply(self, _mocked):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('rooms:new'), {'with_umnik': 'on'})
        self.assertEqual(response.status_code, 302)
        room_id = int(response.url.rstrip('/').split('/')[-1])
        send = self.client.post(reverse('rooms:send', args=[room_id]), {'body': 'Найди планировку 6МД'})
        self.assertEqual(send.status_code, 200)
        payload = send.json()
        self.assertTrue(payload['asked_umnik'])
        self.assertEqual(payload['message']['body'], 'Найди планировку 6МД')
        self.assertIsNone(payload['umnik_message'])
        self.assertTrue(has_umnik(Room.objects.get(pk=room_id)))

    def test_group_does_not_call_umnik_until_addressed(self):
        room = get_or_create_room(
            creator=self.manager,
            user_ids=[self.designer.id],
            with_umnik=True,
        )
        with patch('rooms.services.ask_umnik_chat') as mocked:
            result = post_message(room=room, author=self.manager, body='Согласуем фасады завтра', uploads=[], wait_umnik=True)
            mocked.assert_not_called()
            self.assertFalse(result['asked_umnik'])
            mocked.return_value = {'ok': True, 'answer': 'Записал.', 'attachments': []}
            addressed = post_message(
                room=room,
                author=self.manager,
                body='умник, поставь задачу на фасады',
                uploads=[],
                wait_umnik=True,
            )
            mocked.assert_called_once()
            self.assertTrue(addressed['asked_umnik'])

    def test_file_attachment_without_umnik(self):
        import tempfile
        from pathlib import Path

        room = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=False)
        upload = SimpleUploadedFile('plan.pdf', b'%PDF-1.4 demo', content_type='application/pdf')
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(CRM_FILES_ROOT=Path(tmp)):
                result = post_message(room=room, author=self.manager, body='', uploads=[upload])
        self.assertEqual(result['message']['attachments'][0]['name'], 'plan.pdf')
        self.assertIsNone(result['umnik_message'])

    def test_app_shell_has_no_crm_nav(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse('app:list'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Чаты')
        self.assertContains(response, 'Контакты')
        self.assertContains(response, 'Звонки')
        self.assertContains(response, 'Настройки')
        self.assertContains(response, 'Все')
        self.assertContains(response, 'Новые')
        self.assertContains(response, 'Рабочая')
        self.assertContains(response, 'Клиенты')
        self.assertNotContains(response, 'href="/deals/"')

    def test_contacts_open_chat_with_colleague(self):
        self.client.force_login(self.manager)
        page = self.client.get(reverse('app:contacts'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Ира')
        response = self.client.get(reverse('app:with_user', args=[self.designer.id]))
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(response.url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'Ира')

    def test_new_folder_hides_read_chats(self):
        room = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=False)
        self.client.force_login(self.manager)
        self.client.get(reverse('app:detail', args=[room.id]))
        filtered = self.client.get(reverse('app:list'), {'folder': 'new'})
        self.assertEqual(filtered.status_code, 200)
        self.assertContains(filtered, 'Пока нет чатов в этой папке')

    def test_app_chat_shows_composer_and_mic(self):
        self.client.force_login(self.manager)
        response = self.client.post(reverse('app:new'), {'with_umnik': 'on'})
        self.assertEqual(response.status_code, 302)
        detail = self.client.get(response.url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, 'id="room-send-form"')
        self.assertContains(detail, 'id="tg-mic"')
        self.assertContains(detail, 'name="files"')
        self.assertContains(detail, 'class="tg-composer"')

    def test_voice_upload_is_voice_note(self):
        import tempfile
        from pathlib import Path

        room = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=False)
        upload = SimpleUploadedFile('voice_message.webm', b'OggS\x00voice', content_type='audio/webm')
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(CRM_FILES_ROOT=Path(tmp)):
                result = post_message(room=room, author=self.manager, body='', uploads=[upload])
        self.assertEqual(result['message']['kind'], 'voice_note')
        self.assertTrue(result['message']['attachments'][0]['is_audio'])

    @patch('rooms.services.transcribe_room_voice', return_value='Найди планировку 6МД Ирина')
    @patch('rooms.services.ask_umnik_chat', return_value={'ok': True, 'answer': 'Нашёл планировку.', 'attachments': []})
    def test_umnik_hears_voice_in_chat_and_group(self, mocked_ask, _stt):
        import tempfile
        from pathlib import Path

        room = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=True)
        upload = SimpleUploadedFile('voice_message.webm', b'OggS\x00voice', content_type='audio/webm')
        with tempfile.TemporaryDirectory() as tmp:
            with override_settings(CRM_FILES_ROOT=Path(tmp)):
                result = post_message(
                    room=room,
                    author=self.manager,
                    body='',
                    uploads=[upload],
                    wait_umnik=True,
                )
        self.assertTrue(result['asked_umnik'])
        mocked_ask.assert_called_once()
        self.assertIn('Найди планировку 6МД Ирина', mocked_ask.call_args.kwargs['message'])

    def test_stranger_cannot_open_room(self):
        room = get_or_create_room(creator=self.manager, user_ids=[self.designer.id], with_umnik=False)
        other = get_user_model().objects.create_user(username='rm_other', password='pass1234', role='manager')
        self.client.force_login(other)
        response = self.client.get(reverse('rooms:detail', args=[room.id]))
        self.assertEqual(response.status_code, 404)
