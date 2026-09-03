"""Сохранённые диалоги умника: общие и по сделке."""
from __future__ import annotations

import base64
import mimetypes
import re
from pathlib import Path

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from deals.models import Deal, UmnikChatAttachment, UmnikChatMessage, UmnikChatThread

DEFAULT_TITLE = 'Новый чат'
HISTORY_FOR_MODEL = 12
TITLE_LEN = 72
ATTACH_TITLE = 'Вложение'


def _files_root() -> Path:
    return Path(settings.CRM_FILES_ROOT)


def _chat_dir(thread: UmnikChatThread) -> Path:
    return _files_root() / 'umnik_chat' / str(thread.id)


def _safe_name(name: str) -> str:
    name = (name or 'file').strip().replace('\\', '/').split('/')[-1]
    name = re.sub(r'[^\w.\- ()Ѐ-ӿ]+', '_', name).strip('_ ') or 'file'
    return name[:180]


def resolve_server_path(raw: str) -> Path | None:
    """Windows-путь из настроек -> реальный путь (внутри контейнера). None, если вне разрешённых корней."""
    text = (raw or '').strip().strip('"').replace('/', '\\')
    if not text:
        return None
    for prefix, mounted in (getattr(settings, 'UMNIK_CHAT_SOURCE_MAP', {}) or {}).items():
        pfx = prefix.rstrip('\\')
        if text.lower() == pfx.lower() or text.lower().startswith(pfx.lower() + '\\'):
            tail = text[len(pfx):].strip('\\').replace('\\', '/')
            base = Path(mounted).resolve()
            candidate = (base / tail).resolve()
            try:
                candidate.relative_to(base)
            except ValueError:
                return None
            return candidate if candidate.is_file() else None
    return None


def _store_bytes(thread: UmnikChatThread, name: str, chunks_iter) -> tuple[str, str, int]:
    target_dir = _chat_dir(thread)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    safe = _safe_name(name)
    dest = target_dir / f'{stamp}__{safe}'
    n = 1
    while dest.exists():
        dest = target_dir / f'{stamp}_{n}__{safe}'
        n += 1
    size = 0
    with dest.open('wb') as fh:
        for chunk in chunks_iter:
            fh.write(chunk)
            size += len(chunk)
    rel = str(dest.relative_to(_files_root())).replace('\\', '/')
    mime = mimetypes.guess_type(safe)[0] or ''
    return rel, mime, size


def save_upload(thread: UmnikChatThread, uploaded, user) -> UmnikChatAttachment:
    rel, mime, size = _store_bytes(thread, uploaded.name, uploaded.chunks())
    return UmnikChatAttachment.objects.create(
        thread=thread,
        origin=UmnikChatAttachment.Origin.UPLOAD,
        relative_path=rel,
        original_name=_safe_name(uploaded.name),
        mime_type=getattr(uploaded, 'content_type', '') or mime,
        size_bytes=size,
        uploaded_by=user if getattr(user, 'is_authenticated', False) else None,
    )


def save_bytes(thread: UmnikChatThread, name: str, data: bytes, *, mime: str = '', origin: str = UmnikChatAttachment.Origin.UPLOAD, user=None) -> UmnikChatAttachment:
    """Сохранить готовые байты (например, файл из телеграма) как вложение чата."""
    rel, guessed_mime, size = _store_bytes(thread, name, [data])
    return UmnikChatAttachment.objects.create(
        thread=thread,
        origin=origin,
        relative_path=rel,
        original_name=_safe_name(name),
        mime_type=mime or guessed_mime,
        size_bytes=size,
        uploaded_by=user if getattr(user, 'is_authenticated', False) else None,
    )


def save_server_file(thread: UmnikChatThread, src: Path, raw_path: str, user) -> UmnikChatAttachment:
    def _chunks():
        with src.open('rb') as fh:
            while True:
                block = fh.read(1024 * 1024)
                if not block:
                    break
                yield block

    rel, mime, size = _store_bytes(thread, src.name, _chunks())
    return UmnikChatAttachment.objects.create(
        thread=thread,
        origin=UmnikChatAttachment.Origin.SERVER,
        relative_path=rel,
        original_name=_safe_name(src.name),
        mime_type=mime,
        size_bytes=size,
        source_path=(raw_path or '')[:600],
        uploaded_by=user if getattr(user, 'is_authenticated', False) else None,
    )


def pending_attachments(thread: UmnikChatThread, ids):
    try:
        wanted = {int(x) for x in (ids or [])}
    except (TypeError, ValueError):
        wanted = set()
    if not wanted:
        return []
    return list(
        UmnikChatAttachment.objects.filter(thread=thread, message__isnull=True, pk__in=wanted)
    )


def link_attachments(message: UmnikChatMessage, attachments) -> None:
    for att in attachments or []:
        att.message = message
        att.save(update_fields=['message'])


def serialize_attachment(att: UmnikChatAttachment) -> dict:
    return {
        'id': att.id,
        'name': att.original_name,
        'mime': att.mime_type,
        'size': att.size_bytes,
        'origin': att.origin,
        'is_image': att.is_image,
        'is_pdf': att.is_pdf,
        'url': reverse('umnik_chat_attachment', args=[att.id]),
    }


def serialize_thread(thread: UmnikChatThread) -> dict:
    return {
        'id': thread.id,
        'kind': thread.kind,
        'deal_id': thread.deal_id,
        'deal_code': thread.deal.project_code if thread.deal_id else '',
        'title': thread.title or DEFAULT_TITLE,
        'updated_at': thread.updated_at.isoformat() if thread.updated_at else '',
    }


def serialize_message(message: UmnikChatMessage) -> dict:
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'created_at': message.created_at.isoformat() if message.created_at else '',
        'attachments': [serialize_attachment(att) for att in message.attachments.all()],
    }


def visible_deals():
    return (
        Deal.objects.exclude(status__in=[Deal.Status.DELIVERED, Deal.Status.LOST])
        .order_by('-updated_at')
        .values('id', 'project_code', 'status')[:150]
    )


def user_threads(user):
    return (
        UmnikChatThread.objects.filter(user=user)
        .select_related('deal')
        .order_by('-updated_at')[:100]
    )


def get_thread(user, thread_id) -> UmnikChatThread | None:
    if thread_id in (None, ''):
        return None
    try:
        pk = int(thread_id)
    except (TypeError, ValueError):
        return None
    return UmnikChatThread.objects.filter(user=user, pk=pk).select_related('deal').first()


def create_thread(user, *, kind: str, deal: Deal | None = None) -> UmnikChatThread:
    if kind == UmnikChatThread.Kind.DEAL:
        if deal is None:
            raise ValueError('deal_required')
        return UmnikChatThread.objects.create(
            user=user,
            kind=UmnikChatThread.Kind.DEAL,
            deal=deal,
            title=deal.project_code[:TITLE_LEN] or DEFAULT_TITLE,
        )
    return UmnikChatThread.objects.create(
        user=user,
        kind=UmnikChatThread.Kind.GENERAL,
        deal=None,
        title=DEFAULT_TITLE,
    )


def ensure_deal_thread(user, deal: Deal) -> UmnikChatThread:
    existing = (
        UmnikChatThread.objects.filter(user=user, kind=UmnikChatThread.Kind.DEAL, deal=deal)
        .order_by('-updated_at')
        .first()
    )
    if existing:
        return existing
    return create_thread(user, kind=UmnikChatThread.Kind.DEAL, deal=deal)


def thread_history(thread: UmnikChatThread, limit: int = HISTORY_FOR_MODEL) -> list[dict]:
    rows = list(
        thread.messages.order_by('-created_at', '-id').prefetch_related('attachments')[:limit]
    )
    rows.reverse()
    out = []
    for row in rows:
        text = row.content[:4000]
        names = [att.original_name for att in row.attachments.all()]
        if names:
            text = (text + '\n' if text else '') + '[вложения: ' + ', '.join(names) + ']'
        out.append({'role': row.role, 'content': text})
    return out


def _crm_base_url() -> str:
    return (getattr(settings, 'UMNIK_CRM_BASE_URL', '') or '').strip().rstrip('/')


def _inline_limit_bytes() -> int:
    mb = getattr(settings, 'UMNIK_CHAT_INLINE_MAX_MB', 15) or 0
    try:
        return int(float(mb) * 1024 * 1024)
    except (TypeError, ValueError):
        return 15 * 1024 * 1024


def model_attachments(attachments) -> list[dict]:
    """Вложения для умника: сам файл (base64) + ссылка на скачивание с токеном.

    Умник живёт на другой машине, container-путь ему недоступен — поэтому мелкие
    файлы кладём прямо в payload (``content_b64``), крупные он тянет по
    ``download_url`` с ``Authorization: Bearer <UMNIK_TOKEN>``.
    """
    base = _crm_base_url()
    limit = _inline_limit_bytes()
    shared_root = (getattr(settings, 'UMNIK_SHARED_ROOT', '') or '').strip().rstrip('/\\')
    rel_url = ''
    payload = []
    for att in attachments or []:
        try:
            rel_url = reverse('umnik_chat_attachment_download', args=[att.id])
        except Exception:  # noqa: BLE001 - url может быть не сконфигурирован в тестах
            rel_url = ''
        item = {
            'id': att.id,
            'name': att.original_name,
            'mime': att.mime_type,
            'size': att.size_bytes,
            'is_image': att.is_image,
            'is_pdf': att.is_pdf,
            'path': str(att.absolute_path),
            'url': rel_url,
            'download_url': f'{base}{rel_url}' if base and rel_url else rel_url,
        }
        if shared_root:
            tail = (att.relative_path or '').replace('/', '\\').lstrip('\\')
            item['shared_path'] = f'{shared_root}\\{tail}'
        try:
            path = att.absolute_path
            if path.is_file() and path.stat().st_size <= limit:
                item['content_b64'] = base64.b64encode(path.read_bytes()).decode('ascii')
                item['encoding'] = 'base64'
        except OSError:
            pass
        payload.append(item)
    return payload


def append_message(thread: UmnikChatThread, role: str, content: str, *, has_attachments: bool = False) -> UmnikChatMessage:
    text = (content or '').strip()
    message = UmnikChatMessage.objects.create(thread=thread, role=role, content=text)
    updates = ['updated_at']
    thread.updated_at = timezone.now()
    if role == UmnikChatMessage.Role.USER and (thread.title == DEFAULT_TITLE or not thread.title):
        new_title = ' '.join(text.split())[:TITLE_LEN]
        if not new_title and has_attachments:
            new_title = ATTACH_TITLE
        thread.title = new_title or DEFAULT_TITLE
        updates.append('title')
    thread.save(update_fields=updates)
    return message
