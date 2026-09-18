"""Комнаты: найти/создать беседу, сообщения, вложения, вызов умника."""
from __future__ import annotations

import base64
import logging
import mimetypes
import re
import threading
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from accounts.events import create_notification, push_user_event
from accounts.models import Notification
from accounts.permissions import can_use_umnik_chat, staff_users_qs, umnik_capabilities
from deals.services.umnik import ask_umnik_chat
from deals.services.umnik_chat import resolve_server_path

from .models import Room, RoomMember, RoomMessage, RoomMessageAttachment

log = logging.getLogger('rooms')

UMNIK_LABEL = 'Умник'
HISTORY_FOR_MODEL = 20
TITLE_LEN = 72
ADDRESSED_RE = re.compile(r'^\s*(@?умник|@?umnik)\b', re.I)
AVATAR_COLORS = (
    '#e17076',
    '#faa774',
    '#a2d06e',
    '#7bc862',
    '#6ec9cb',
    '#65aadd',
    '#7193e0',
    '#a695e7',
    '#ee7aae',
    '#e5ca77',
)
ROLE_RU = {
    'manager': 'Менеджер',
    'designer': 'Дизайнер',
    'production': 'Производство',
    'admin': 'Админ',
    'head': 'Руководитель',
    'superadmin': 'Суперадмин',
}


def display_name(user) -> str:
    if user is None:
        return UMNIK_LABEL
    full = f'{(user.first_name or "").strip()} {(user.last_name or "").strip()}'.strip()
    return full or user.username


def initials(name: str) -> str:
    parts = [item for item in (name or '').replace('.', ' ').split() if item]
    if not parts:
        return '?'
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def avatar_color(key: str) -> str:
    return AVATAR_COLORS[sum(ord(ch) for ch in (key or '')) % len(AVATAR_COLORS)]


def short_time(dt) -> str:
    if not dt:
        return ''
    local = timezone.localtime(dt)
    today = timezone.localdate()
    if local.date() == today:
        return local.strftime('%H:%M')
    if (today - local.date()).days < 7:
        return local.strftime('%d.%m')
    return local.strftime('%d.%m')


def colleague_qs(user):
    return staff_users_qs(get_user_model().objects.filter(is_active=True)).exclude(pk=user.pk).order_by(
        'first_name', 'last_name', 'username'
    )


def member_of(room: Room, user) -> RoomMember | None:
    return RoomMember.objects.filter(room=room, kind=RoomMember.Kind.USER, user=user).first()


def has_umnik(room: Room) -> bool:
    return RoomMember.objects.filter(room=room, kind=RoomMember.Kind.UMNIK).exists()


def human_members(room: Room):
    return list(
        RoomMember.objects.filter(room=room, kind=RoomMember.Kind.USER)
        .select_related('user')
        .order_by('id')
    )


def room_title_for(room: Room, viewer) -> str:
    if (room.title or '').strip():
        return room.title.strip()
    names = []
    for member in human_members(room):
        if member.user_id == getattr(viewer, 'id', None):
            continue
        names.append(display_name(member.user))
    if has_umnik(room):
        names.append(UMNIK_LABEL)
    if not names:
        names.append(UMNIK_LABEL if has_umnik(room) else 'Чат')
    return ', '.join(names)


def visible_rooms(user):
    return (
        Room.objects.filter(status=Room.Status.OPEN, members__kind=RoomMember.Kind.USER, members__user=user)
        .distinct()
        .prefetch_related('members__user')
        .order_by('-updated_at')
    )


def _same_participants(room: Room, user_ids: set[int], with_umnik: bool) -> bool:
    humans = {m.user_id for m in human_members(room) if m.user_id}
    return humans == user_ids and has_umnik(room) == with_umnik


def find_room(user_ids: set[int], with_umnik: bool) -> Room | None:
    qs = Room.objects.filter(status=Room.Status.OPEN)
    for uid in user_ids:
        qs = qs.filter(members__kind=RoomMember.Kind.USER, members__user_id=uid)
    qs = qs.distinct().prefetch_related('members')
    for room in qs:
        if _same_participants(room, user_ids, with_umnik):
            return room
    return None


def create_room(*, creator, user_ids: set[int], with_umnik: bool) -> Room:
    room = Room.objects.create(created_by=creator)
    RoomMember.objects.create(room=room, user=creator, kind=RoomMember.Kind.USER, role=RoomMember.Role.HOST)
    for uid in user_ids:
        if uid == creator.id:
            continue
        RoomMember.objects.create(room=room, user_id=uid, kind=RoomMember.Kind.USER, role=RoomMember.Role.MEMBER)
    if with_umnik:
        RoomMember.objects.create(room=room, user=None, kind=RoomMember.Kind.UMNIK, role=RoomMember.Role.MEMBER)
        RoomMessage.objects.create(
            room=room,
            author=None,
            author_kind=RoomMessage.AuthorKind.SYSTEM,
            kind=RoomMessage.Kind.SYSTEM,
            body='Умник добавлен в чат. Можно писать ему напрямую или приложить файл — он разложит его по сделке.',
        )
    room.title = room_title_for(room, creator)
    room.save(update_fields=['title', 'updated_at'])
    return room


def get_or_create_room(*, creator, user_ids, with_umnik: bool) -> Room:
    ids = {int(uid) for uid in user_ids if uid}
    ids.add(creator.id)
    existing = find_room(ids, with_umnik)
    if existing:
        return existing
    allowed = set(colleague_qs(creator).values_list('pk', flat=True))
    allowed.add(creator.id)
    cleaned = {uid for uid in ids if uid in allowed}
    if creator.id not in cleaned:
        cleaned.add(creator.id)
    if not with_umnik and cleaned == {creator.id}:
        raise ValueError('no_participants')
    return create_room(creator=creator, user_ids=cleaned, with_umnik=with_umnik)


def add_umnik(room: Room, actor) -> bool:
    if has_umnik(room):
        return False
    RoomMember.objects.create(room=room, user=None, kind=RoomMember.Kind.UMNIK, role=RoomMember.Role.MEMBER)
    RoomMessage.objects.create(
        room=room,
        author=actor,
        author_kind=RoomMessage.AuthorKind.SYSTEM,
        kind=RoomMessage.Kind.SYSTEM,
        body=f'{display_name(actor)} добавил Умника в чат.',
    )
    if not (room.title or '').strip():
        room.title = room_title_for(room, actor)
    room.save(update_fields=['title', 'updated_at'])
    _notify_room(room, actor, 'Умник в чате', f'{display_name(actor)} добавил Умника')
    return True


def remove_umnik(room: Room, actor) -> bool:
    deleted, _ = RoomMember.objects.filter(room=room, kind=RoomMember.Kind.UMNIK).delete()
    if not deleted:
        return False
    RoomMessage.objects.create(
        room=room,
        author=actor,
        author_kind=RoomMessage.AuthorKind.SYSTEM,
        kind=RoomMessage.Kind.SYSTEM,
        body=f'{display_name(actor)} убрал Умника из чата.',
    )
    room.save(update_fields=['updated_at'])
    _notify_room(room, actor, 'Умник вышел', f'{display_name(actor)} убрал Умника')
    return True


def _files_root() -> Path:
    return Path(settings.CRM_FILES_ROOT)


def _safe_name(name: str) -> str:
    name = (name or 'file').strip().replace('\\', '/').split('/')[-1]
    name = re.sub(r'[^\w.\- ()Ѐ-ӿ]+', '_', name).strip('_ ') or 'file'
    return name[:180]


def save_upload(message: RoomMessage, uploaded) -> RoomMessageAttachment:
    target_dir = _files_root() / 'rooms' / str(message.room_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    safe = _safe_name(getattr(uploaded, 'name', '') or 'file')
    dest = target_dir / f'{stamp}__{safe}'
    n = 1
    while dest.exists():
        dest = target_dir / f'{stamp}_{n}__{safe}'
        n += 1
    size = 0
    with dest.open('wb') as fh:
        for chunk in uploaded.chunks():
            fh.write(chunk)
            size += len(chunk)
    rel = str(dest.relative_to(_files_root())).replace('\\', '/')
    mime = getattr(uploaded, 'content_type', '') or mimetypes.guess_type(safe)[0] or ''
    return RoomMessageAttachment.objects.create(
        message=message,
        relative_path=rel,
        original_name=safe,
        mime_type=mime,
        size_bytes=size,
    )


def attachment_abs(att: RoomMessageAttachment) -> Path:
    return _files_root() / att.relative_path


def serialize_attachment(att: RoomMessageAttachment, url_namespace: str = 'rooms') -> dict:
    return {
        'id': att.id,
        'name': att.original_name,
        'mime': att.mime_type,
        'size': att.size_bytes,
        'is_image': att.is_image,
        'is_pdf': att.is_pdf,
        'is_audio': att.is_audio,
        'url': reverse(f'{url_namespace}:file', args=[att.message.room_id, att.id]),
    }


def serialize_message(message: RoomMessage, url_namespace: str = 'rooms') -> dict:
    author = message.author
    if message.author_kind == RoomMessage.AuthorKind.UMNIK:
        author_name = UMNIK_LABEL
    elif message.author_kind == RoomMessage.AuthorKind.SYSTEM:
        author_name = ''
    else:
        author_name = display_name(author)
    return {
        'id': message.id,
        'author_kind': message.author_kind,
        'author_id': message.author_id,
        'author_name': author_name,
        'body': message.body,
        'kind': message.kind,
        'created_at': message.created_at.isoformat() if message.created_at else '',
        'attachments': [serialize_attachment(att, url_namespace) for att in message.attachments.all()],
    }


def unread_count(room: Room, member: RoomMember | None) -> int:
    if member is None or member.last_read_at is None:
        return room.messages.exclude(author_kind=RoomMessage.AuthorKind.SYSTEM).count()
    return room.messages.filter(created_at__gt=member.last_read_at).exclude(author=member.user).count()


def serialize_room(room: Room, viewer, url_namespace: str = 'rooms') -> dict:
    last = room.messages.exclude(kind=RoomMessage.Kind.SYSTEM).order_by('-created_at', '-id').first()
    member = member_of(room, viewer)
    people = [display_name(m.user) for m in human_members(room)]
    title = room_title_for(room, viewer)
    return {
        'id': room.id,
        'title': title,
        'has_umnik': has_umnik(room),
        'participants': people,
        'updated_at': room.updated_at.isoformat() if room.updated_at else '',
        'time': short_time(room.updated_at),
        'unread': unread_count(room, member),
        'last_body': (
            'Голосовое сообщение'
            if last and last.kind == RoomMessage.Kind.VOICE_NOTE
            else (
                (last.body or (last.attachments.first().original_name if last and last.attachments.exists() else ''))
                if last
                else ''
            )
        ),
        'url': reverse(f'{url_namespace}:detail', args=[room.id]),
        'deal_id': room.deal_id,
        'deal_code': room.deal.project_code if room.deal_id else '',
        'folder': 'clients' if room.deal_id else 'work',
        'initials': initials(title),
        'color': avatar_color(str(room.id)),
    }


def filter_rooms(rooms: list[dict], folder: str) -> list[dict]:
    if folder == 'new':
        return [item for item in rooms if item.get('unread')]
    if folder == 'work':
        return [item for item in rooms if not item.get('deal_id')]
    if folder == 'clients':
        return [item for item in rooms if item.get('deal_id')]
    return rooms


def serialize_person(user, url_namespace: str = 'rooms') -> dict:
    name = display_name(user)
    return {
        'id': user.id,
        'name': name,
        'username': user.username,
        'role': ROLE_RU.get(getattr(user, 'role', ''), ''),
        'initials': initials(name),
        'color': avatar_color(str(user.id)),
        'url': reverse(f'{url_namespace}:with_user', args=[user.id]),
    }


def mark_read(room: Room, user) -> None:
    RoomMember.objects.filter(room=room, kind=RoomMember.Kind.USER, user=user).update(last_read_at=timezone.now())


def addresses_umnik(text: str) -> bool:
    return bool(ADDRESSED_RE.match(text or ''))


def only_umnik_chat(room: Room) -> bool:
    humans = human_members(room)
    return has_umnik(room) and len(humans) == 1


def should_ask_umnik(room: Room, body: str, has_files: bool, kind: str = '') -> bool:
    if not has_umnik(room):
        return False
    if kind == RoomMessage.Kind.VOICE_NOTE:
        return True
    if only_umnik_chat(room):
        return True
    if addresses_umnik(body):
        return True
    if has_files and not (body or '').strip():
        return True
    return False


def transcribe_room_voice(message: RoomMessage) -> str:
    """Расшифровывает голосовые вложения, чтобы умник слышал речь, а не «немой» файл."""
    from deals.services.transcribe import TranscribeError, is_configured, transcribe

    if not is_configured():
        return ''
    texts = []
    for att in message.attachments.all():
        if not att.is_audio:
            continue
        path = attachment_abs(att)
        if not path.is_file():
            continue
        try:
            text = transcribe(
                path.read_bytes(),
                filename=att.original_name or 'voice.webm',
                mime=att.mime_type or 'audio/webm',
            )
        except (TranscribeError, OSError):
            log.exception('voice transcribe failed for attachment %s', att.id)
            continue
        if (text or '').strip():
            texts.append(text.strip())
    return '\n'.join(texts)


def _history(room: Room) -> list[dict]:
    rows = list(room.messages.order_by('-created_at', '-id').prefetch_related('attachments')[:HISTORY_FOR_MODEL])
    rows.reverse()
    out = []
    for row in rows:
        if row.author_kind == RoomMessage.AuthorKind.SYSTEM:
            continue
        role = 'assistant' if row.author_kind == RoomMessage.AuthorKind.UMNIK else 'user'
        text = (row.body or '')[:4000]
        names = [att.original_name for att in row.attachments.all()]
        if names:
            text = (text + '\n' if text else '') + '[вложения: ' + ', '.join(names) + ']'
        if row.author_kind == RoomMessage.AuthorKind.USER and row.author_id:
            text = f'{display_name(row.author)}: {text}' if text else display_name(row.author)
        out.append({'role': role, 'content': text})
    return out


def _inline_limit_bytes() -> int:
    mb = getattr(settings, 'UMNIK_CHAT_INLINE_MAX_MB', 15) or 0
    try:
        return int(float(mb) * 1024 * 1024)
    except (TypeError, ValueError):
        return 15 * 1024 * 1024


def model_attachments(attachments, url_namespace: str = 'rooms') -> list[dict]:
    base = (getattr(settings, 'UMNIK_CRM_BASE_URL', '') or '').strip().rstrip('/')
    limit = _inline_limit_bytes()
    shared_root = (getattr(settings, 'UMNIK_SHARED_ROOT', '') or '').strip().rstrip('/\\')
    payload = []
    for att in attachments or []:
        try:
            rel_url = reverse(f'{url_namespace}:file', args=[att.message.room_id, att.id])
        except Exception:
            rel_url = ''
        path = attachment_abs(att)
        item = {
            'id': att.id,
            'name': att.original_name,
            'mime': att.mime_type,
            'size': att.size_bytes,
            'is_image': att.is_image,
            'is_pdf': att.is_pdf,
            'path': str(path),
            'url': rel_url,
            'download_url': f'{base}{rel_url}' if base and rel_url else rel_url,
        }
        if shared_root:
            tail = (att.relative_path or '').replace('/', '\\').lstrip('\\')
            item['shared_path'] = f'{shared_root}\\{tail}'
        try:
            if path.is_file() and path.stat().st_size <= limit:
                item['content_b64'] = base64.b64encode(path.read_bytes()).decode('ascii')
                item['encoding'] = 'base64'
        except OSError:
            pass
        payload.append(item)
    return payload


def _notify_room_sync(room_id: int, actor_id, title: str, body: str) -> None:
    from django.db import close_old_connections

    close_old_connections()
    try:
        room = Room.objects.filter(pk=room_id).first()
        actor = get_user_model().objects.filter(pk=actor_id).first() if actor_id else None
        if room is None:
            return
        for member in human_members(room):
            if member.user_id == actor_id or member.user_id is None:
                continue
            try:
                push_user_event(
                    user_id=member.user_id,
                    payload={
                        'type': 'room.message.created',
                        'room_id': room.id,
                        'title': title,
                        'body': body[:240],
                    },
                )
            except Exception:
                pass
            try:
                create_notification(
                    user=member.user,
                    actor=actor,
                    notification_type=Notification.Type.MESSAGE_RECEIVED,
                    title=title,
                    body=body[:240],
                    related_model='Room',
                    related_id=room.id,
                )
            except Exception:
                pass
    finally:
        close_old_connections()


def _notify_room(room: Room, actor, title: str, body: str) -> None:
    threading.Thread(
        target=_notify_room_sync,
        args=(room.id, getattr(actor, 'id', None), title, body),
        daemon=True,
    ).start()


def run_umnik_reply(room: Room, user_message: RoomMessage, author, url_namespace: str = 'rooms'):
    attachments = list(user_message.attachments.all())
    question = (user_message.body or '').strip()
    transcript = transcribe_room_voice(user_message)
    if transcript:
        heard = 'Расшифровка голосового: ' + transcript
        question = f'{question}\n\n{heard}'.strip() if question else heard
        if 'Расшифровка голосового:' not in (user_message.body or ''):
            user_message.body = question
            user_message.save(update_fields=['body'])
    if not question:
        if any(att.is_audio for att in attachments):
            question = 'Голосовое сообщение: речь распознать не удалось. Скажи, что не расслышал, и попроси повторить.'
        elif attachments:
            question = '(файл без комментария)'
        else:
            question = '(пустое сообщение)'
    result = ask_umnik_chat(
        message=question,
        history=_history(room),
        actor=author.username,
        deal_id=room.deal_id,
        deal_code=room.deal.project_code if room.deal_id else '',
        capabilities=umnik_capabilities(author),
        attachments=model_attachments(attachments, url_namespace),
    )
    answer = (result.get('answer') or '').strip() or 'Пустой ответ.'
    umnik_message = RoomMessage.objects.create(
        room=room,
        author=None,
        author_kind=RoomMessage.AuthorKind.UMNIK,
        kind=RoomMessage.Kind.UMNIK,
        body=answer,
    )
    for item in result.get('attachments') or []:
        raw = item.get('path') or item.get('server_path') if isinstance(item, dict) else str(item)
        src = resolve_server_path(raw or '')
        if src is None or not src.is_file():
            continue

        class _File:
            name = src.name
            content_type = mimetypes.guess_type(src.name)[0] or ''

            def chunks(self, chunk_size=1024 * 1024):
                with src.open('rb') as fh:
                    while True:
                        block = fh.read(chunk_size)
                        if not block:
                            break
                        yield block

        save_upload(umnik_message, _File())
    room.save(update_fields=['updated_at'])
    return umnik_message


def schedule_umnik_reply(room_id: int, message_id: int, author_id: int, url_namespace: str) -> None:
    def _run():
        from django.db import close_old_connections

        close_old_connections()
        try:
            room = Room.objects.select_related('deal').filter(pk=room_id).first()
            message = RoomMessage.objects.filter(pk=message_id, room_id=room_id).first()
            author = get_user_model().objects.filter(pk=author_id).first()
            if room is None or message is None or author is None:
                return
            run_umnik_reply(room, message, author, url_namespace)
        except Exception:
            log.exception('umnik reply failed for room %s message %s', room_id, message_id)
        finally:
            close_old_connections()

    threading.Thread(target=_run, daemon=True).start()


def _is_voice_upload(uploaded) -> bool:
    mime = (getattr(uploaded, 'content_type', None) or '').lower()
    name = (getattr(uploaded, 'name', None) or '').lower()
    return mime.startswith('audio/') or name.endswith(('.ogg', '.webm', '.m4a', '.mp3', '.wav', '.aac'))


def post_message(*, room: Room, author, body: str, uploads, url_namespace: str = 'rooms', wait_umnik: bool = False) -> dict:
    text = (body or '').strip()
    files = [item for item in (uploads or []) if item and getattr(item, 'size', 1)]
    if not text and not files:
        raise ValueError('empty')
    if files and not text and all(_is_voice_upload(item) for item in files):
        kind = RoomMessage.Kind.VOICE_NOTE
    elif files and not text:
        kind = RoomMessage.Kind.FILE
    else:
        kind = RoomMessage.Kind.TEXT
    message = RoomMessage.objects.create(
        room=room,
        author=author,
        author_kind=RoomMessage.AuthorKind.USER,
        kind=kind,
        body=text,
    )
    attachments = [save_upload(message, uploaded) for uploaded in files]
    room.updated_at = timezone.now()
    if (room.title or '').strip() in {'', UMNIK_LABEL, 'Чат'} and text:
        room.title = ' '.join(text.split())[:TITLE_LEN]
    room.save(update_fields=['title', 'updated_at'])
    preview = text or (
        'Голосовое сообщение' if kind == RoomMessage.Kind.VOICE_NOTE else (attachments[0].original_name if attachments else 'Сообщение')
    )
    _notify_room(room, author, room_title_for(room, author), preview)

    asked = bool(should_ask_umnik(room, text, bool(attachments), kind=kind) and can_use_umnik_chat(author))
    umnik_message = None
    if asked:
        if wait_umnik:
            umnik_message = run_umnik_reply(room, message, author, url_namespace)
        else:
            schedule_umnik_reply(room.id, message.id, author.id, url_namespace)

    return {
        'message': serialize_message(message, url_namespace),
        'umnik_message': serialize_message(umnik_message, url_namespace) if umnik_message else None,
        'asked_umnik': asked,
    }
