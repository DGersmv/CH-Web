"""Long-polling цикл телеграм-бота диспетчерской.

Запуск: python manage.py run_telegram_bot
В docker-compose поднят отдельным сервисом telegram_bot на том же образе, что app.
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from deals.models import TelegramBotState
from deals.services import telegram_api
from deals.services.telegram_bot import flush_stale_albums, handle_update

log = logging.getLogger('deals.telegram')


class Command(BaseCommand):
    help = 'Слушает Telegram (getUpdates) и отвечает через умника в группе диспетчерской.'

    def handle(self, *args, **options):
        token = (getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
        chat_id = int(getattr(settings, 'TELEGRAM_DISPATCH_CHAT_ID', 0) or 0)
        if not token:
            self.stderr.write('TELEGRAM_BOT_TOKEN не задан — бот не запускается.')
            return
        if not chat_id:
            self.stderr.write('TELEGRAM_DISPATCH_CHAT_ID не задан — бот не запускается.')
            return

        poll_timeout = int(getattr(settings, 'TELEGRAM_POLL_TIMEOUT', 50) or 50)
        state = TelegramBotState.load()
        self.stdout.write(self.style.SUCCESS(
            f'Telegram bot запущен, offset={state.update_offset}, группа={chat_id}'
        ))
        try:
            chat = telegram_api._call('getChat', {'chat_id': chat_id}, timeout=30)
            title = chat.get('title') or ''
            ctype = chat.get('type') or ''
            self.stdout.write(f'Группа на связи: {title!r} ({ctype})')
        except telegram_api.TelegramError as exc:
            text = str(exc)
            self.stderr.write(f'Не могу открыть группу {chat_id}: {text}')
            if 'upgraded to a supergroup' in text:
                self.stderr.write(
                    'Группу повысили до супергруппы — в .env нужен новый TELEGRAM_DISPATCH_CHAT_ID '
                    '(обычно из ошибки migrate_to_chat_id).'
                )
            return

        while True:
            try:
                updates = telegram_api.get_updates(state.update_offset, poll_timeout)
            except telegram_api.TelegramError as exc:
                log.warning('getUpdates: %s', exc)
                time.sleep(3)
                continue
            except Exception:  # noqa: BLE001 - сеть/JSON; переживаем и повторяем
                log.exception('getUpdates crash')
                time.sleep(5)
                continue

            for update in updates or []:
                try:
                    handle_update(update)
                except Exception:  # noqa: BLE001 - один битый апдейт не роняет цикл
                    log.exception('handle_update failed: %s', update.get('update_id'))
                state.update_offset = update['update_id'] + 1
                state.save(update_fields=['update_offset', 'updated_at'])

            try:
                flush_stale_albums()
            except Exception:  # noqa: BLE001
                log.exception('flush_stale_albums failed')

            if not updates:
                # getUpdates уже держал соединение poll_timeout секунд — паузу не нужно
                continue
