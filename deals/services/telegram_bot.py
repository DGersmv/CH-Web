"""Обработка апдейтов телеграм-бота диспетчерской.

Модель простая: группа ``TELEGRAM_DISPATCH_CHAT_ID`` целиком — это один чат с умником.
Кто угодно из привязанных к CRM боссов пишет в группу, бот отвечает reply. Автор
конкретного сообщения = actor (его роль и права идут умнику). История общая на группу.

Личка с ботом используется только для привязки: ``/start <код>`` (код берётся в профиле CRM).
"""
from __future__ import annotations

import logging
import time

from django.conf import settings
from django.utils import timezone

from accounts.permissions import umnik_capabilities
from deals.models import (
    TelegramGroupThread,
    TelegramProfile,
    UmnikChatAttachment,
    UmnikChatThread,
)
from deals.services import telegram_api
from deals.services import umnik_chat as chat_store
from deals.services.umnik import ask_umnik_chat

log = logging.getLogger('deals.telegram')

ALBUM_FLUSH_SECONDS = 2.0
_albums: dict[str, dict] = {}

# кэши в пределах одного процесса, чтобы не тянуть повторно из БД / телеграма
_group_title_cache: dict[int, str] = {}
_name_cache: dict[tuple[int, int], str] = {}

NOT_LINKED_TEXT = (
    'Вы не привязаны к CRM. Напишите мне в личные сообщения команду\n'
    '/start КОД\n'
    'Код одноразовый, его выдаёт ваш профиль в CRM.'
)


# --------------------------------------------------------------------------- helpers

def _resolve_user(tg_user_id: int):
    profile = (
        TelegramProfile.objects.filter(telegram_user_id=tg_user_id)
        .select_related('user')
        .first()
    )
    if profile and profile.user and profile.user.is_active:
        return profile.user
    return None


def _display_name(tg_from: dict) -> str:
    parts = [tg_from.get('first_name') or '', tg_from.get('last_name') or '']
    name = ' '.join(p for p in parts if p).strip()
    return name or (tg_from.get('username') or f'id{tg_from.get("id")}')


def _group_thread(chat_id: int, owner, group_title: str) -> UmnikChatThread:
    link, _ = TelegramGroupThread.objects.get_or_create(chat_id=chat_id)
    if group_title and link.title != group_title:
        link.title = group_title[:200]
        link.save(update_fields=['title', 'updated_at'])
    if link.thread_id:
        return link.thread
    thread = UmnikChatThread.objects.create(
        user=owner,
        kind=UmnikChatThread.Kind.GENERAL,
        deal=None,
        title=(f'Телеграм: {group_title}'.strip()[:120]) or 'Телеграм-диспетчерская',
    )
    link.thread = thread
    link.save(update_fields=['thread', 'updated_at'])
    return thread


def _pick_media(message: dict) -> tuple[str, str, str] | None:
    """(file_id, имя_файла, mime) для скачивания, либо None если медиа нет."""
    if message.get('photo'):
        biggest = max(message['photo'], key=lambda p: p.get('file_size') or p.get('width') or 0)
        return biggest['file_id'], f'photo_{biggest["file_id"][:10]}.jpg', 'image/jpeg'
    doc = message.get('document')
    if doc:
        return doc['file_id'], doc.get('file_name') or f'file_{doc["file_id"][:10]}', doc.get('mime_type') or ''
    video = message.get('video')
    if video:
        return video['file_id'], video.get('file_name') or f'video_{video["file_id"][:10]}.mp4', video.get('mime_type') or 'video/mp4'
    voice = message.get('voice')
    if voice:
        return voice['file_id'], f'voice_{voice["file_id"][:10]}.ogg', voice.get('mime_type') or 'audio/ogg'
    audio = message.get('audio')
    if audio:
        return audio['file_id'], audio.get('file_name') or f'audio_{audio["file_id"][:10]}.mp3', audio.get('mime_type') or 'audio/mpeg'
    return None


def _save_media(thread: UmnikChatThread, spec: tuple[str, str, str], user):
    file_id, name, mime = spec
    max_bytes = int(getattr(settings, 'TELEGRAM_MAX_FILE_MB', 45)) * 1024 * 1024
    try:
        path = telegram_api.get_file_path(file_id)
        data = telegram_api.download_file(path, max_bytes=max_bytes)
    except telegram_api.TelegramError as exc:
        log.warning('telegram media skip: %s', exc)
        return None
    return chat_store.save_bytes(
        thread, name, data, mime=mime, origin=UmnikChatAttachment.Origin.UPLOAD, user=user,
    )


def _ask_and_reply(*, chat_id: int, reply_to: int, user, text: str, media_specs: list):
    thread = _group_thread(chat_id, user, _group_title_cache.get(chat_id, ''))
    attachments = []
    for spec in media_specs:
        att = _save_media(thread, spec, user)
        if att is not None:
            attachments.append(att)

    body = (text or '').strip()
    if not body and not attachments:
        return
    if not body:
        body = '(файл без комментария)'

    history = chat_store.thread_history(thread)
    stored = f'[{_name_cache.get((chat_id, reply_to), "")}] {body}'.strip()
    user_msg = chat_store.append_message(thread, 'user', stored, has_attachments=bool(attachments))
    chat_store.link_attachments(user_msg, attachments)

    telegram_api.send_chat_action(chat_id)
    result = ask_umnik_chat(
        message=body,
        history=history,
        actor=user.username,
        capabilities=umnik_capabilities(user),
        attachments=chat_store.model_attachments(attachments),
    )
    answer = (result.get('answer') or '').strip() or 'Пустой ответ.'
    outgoing = []
    for item in result.get('attachments') or []:
        raw = item.get('path') or item.get('server_path') if isinstance(item, dict) else str(item)
        src = chat_store.resolve_server_path(raw or '')
        if src is None:
            log.warning('umnik attachment unmapped: %s', raw)
            continue
        outgoing.append(src)
    if result.get('ok'):
        saved = chat_store.append_message(thread, 'assistant', answer, has_attachments=bool(outgoing))
        added = []
        for src in outgoing:
            att = chat_store.save_server_file(thread, src, str(src), None)
            att.origin = UmnikChatAttachment.Origin.UMNIK
            att.save(update_fields=['origin'])
            added.append(att)
        chat_store.link_attachments(saved, added)
    try:
        telegram_api.send_message(chat_id, answer, reply_to=reply_to)
    except telegram_api.TelegramError as exc:
        log.error('telegram sendMessage failed: %s', exc)
    for src in outgoing:
        try:
            telegram_api.send_chat_action(chat_id, 'upload_document')
            telegram_api.send_document(chat_id, src, filename=src.name, reply_to=reply_to)
        except telegram_api.TelegramError as exc:
            log.error('telegram sendDocument failed: %s', exc)
            try:
                telegram_api.send_message(
                    chat_id,
                    f'Не смог отправить файл «{src.name}»: {exc}',
                    reply_to=reply_to,
                )
            except telegram_api.TelegramError:
                pass


# --------------------------------------------------------------------------- private chat

def _handle_private(message: dict):
    chat_id = message['chat']['id']
    tg_from = message.get('from') or {}
    text = (message.get('text') or '').strip()
    if not text.startswith('/start'):
        telegram_api.send_message(
            chat_id,
            'Это бот диспетчерской. Чтобы привязать аккаунт, отправьте: /start КОД (код в вашем профиле CRM).',
        )
        return
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else ''
    if not code:
        telegram_api.send_message(chat_id, 'Укажите код: /start КОД')
        return
    profile = TelegramProfile.objects.filter(link_code=code).select_related('user').first()
    now = timezone.now()
    if profile is None or (profile.link_code_expires_at and profile.link_code_expires_at < now):
        telegram_api.send_message(chat_id, 'Код неверный или просрочен. Возьмите новый в профиле CRM.')
        return
    clash = (
        TelegramProfile.objects.filter(telegram_user_id=tg_from['id'])
        .exclude(pk=profile.pk)
        .first()
    )
    if clash is not None:
        clash.telegram_user_id = None
        clash.save(update_fields=['telegram_user_id'])
    profile.telegram_user_id = tg_from['id']
    profile.telegram_username = tg_from.get('username') or ''
    profile.link_code = ''
    profile.link_code_expires_at = None
    profile.linked_at = now
    profile.save()
    telegram_api.send_message(
        chat_id,
        f'Готово, аккаунт {profile.user.username} привязан. Теперь пишите в группе диспетчерской.',
    )


# --------------------------------------------------------------------------- entry points

def handle_update(update: dict):
    message = update.get('message')
    if not message:
        return
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    tg_from = message.get('from') or {}
    if tg_from.get('is_bot'):
        return

    dispatch_id = int(getattr(settings, 'TELEGRAM_DISPATCH_CHAT_ID', 0) or 0)

    if chat.get('type') == 'private':
        _handle_private(message)
        return

    if chat_id != dispatch_id:
        log.info(
            'сообщение из чужого чата chat_id=%s (title=%r), ожидаю TELEGRAM_DISPATCH_CHAT_ID=%s — игнор',
            chat_id, chat.get('title'), dispatch_id,
        )
        return  # чужая группа — игнор

    log.info('группа диспетчерской: from=%s text=%r', tg_from.get('id'), (message.get('text') or message.get('caption') or '')[:80])

    _group_title_cache[chat_id] = chat.get('title') or ''
    text = message.get('text') or message.get('caption') or ''
    if text.startswith('/'):
        return  # команды в группе боссам не нужны

    user = _resolve_user(tg_from['id'])
    if user is None:
        try:
            telegram_api.send_message(chat_id, NOT_LINKED_TEXT, reply_to=message['message_id'])
        except telegram_api.TelegramError:
            pass
        return

    _name_cache[(chat_id, message['message_id'])] = _display_name(tg_from)
    media = _pick_media(message)
    group_id = message.get('media_group_id')

    if group_id:
        bucket = _albums.setdefault(group_id, {
            'chat_id': chat_id,
            'reply_to': message['message_id'],
            'user_id': user.id,
            'text': '',
            'media': [],
            'ts': time.monotonic(),
        })
        if text:
            bucket['text'] = text
        if media:
            bucket['media'].append(media)
        bucket['ts'] = time.monotonic()
        return

    _ask_and_reply(
        chat_id=chat_id,
        reply_to=message['message_id'],
        user=user,
        text=text,
        media_specs=[media] if media else [],
    )


def flush_stale_albums(force: bool = False):
    """Собранные альбомы (несколько фото одним сообщением) отправляем одним запросом умнику."""
    from django.contrib.auth import get_user_model

    now = time.monotonic()
    ready = [gid for gid, b in _albums.items() if force or now - b['ts'] >= ALBUM_FLUSH_SECONDS]
    for gid in ready:
        bucket = _albums.pop(gid)
        user = get_user_model().objects.filter(pk=bucket['user_id'], is_active=True).first()
        if user is None:
            continue
        _name_cache.setdefault((bucket['chat_id'], bucket['reply_to']), user.get_full_name() or user.username)
        try:
            _ask_and_reply(
                chat_id=bucket['chat_id'],
                reply_to=bucket['reply_to'],
                user=user,
                text=bucket['text'],
                media_specs=bucket['media'],
            )
        except Exception:  # noqa: BLE001 - один битый альбом не должен ронять цикл
            log.exception('album flush failed')
