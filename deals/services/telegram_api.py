"""Тонкий клиент Telegram Bot API на urllib (в проекте нет requests).

Работает через long polling (getUpdates) — не нужен белый IP, вебхук и сертификат.
Падения телеграма не должны ронять процесс: сетевые ошибки прокидываем наверх,
цикл в management-команде их гасит и повторяет.
"""
from __future__ import annotations

import http.client
import json
import socket
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

API_ROOT = 'https://api.telegram.org'


class TelegramError(RuntimeError):
    pass


def _create_connection_ipv4(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None):
    """Как socket.create_connection, но только по IPv4.

    Docker-мост по умолчанию без IPv6-маршрута. Если DNS отдаёт AAAA-запись
    api.telegram.org раньше A, urllib пытается IPv6 и падает с
    [Errno 101] Network is unreachable. Резолвим адрес только в IPv4.
    """
    host, port = address
    exceptions = []
    for af, socktype, proto, _canon, sa in socket.getaddrinfo(
        host, port, socket.AF_INET, socket.SOCK_STREAM
    ):
        sock = None
        try:
            sock = socket.socket(af, socktype, proto)
            if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                sock.settimeout(timeout)
            if source_address:
                sock.bind(source_address)
            sock.connect(sa)
            return sock
        except OSError as exc:
            exceptions.append(exc)
            if sock is not None:
                sock.close()
    if exceptions:
        raise exceptions[0]
    raise OSError('getaddrinfo вернул пустой список для IPv4')


class _IPv4HTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _create_connection_ipv4


class _IPv4HTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        # В 3.12 HTTPSHandler не всегда кладёт _check_hostname на инстанс.
        kwargs = {}
        context = getattr(self, '_context', None)
        if context is not None:
            kwargs['context'] = context
        if hasattr(self, '_check_hostname'):
            kwargs['check_hostname'] = self._check_hostname
        return self.do_open(_IPv4HTTPSConnection, req, **kwargs)


_cached_opener = None


def _proxy_url() -> str:
    return (
        (getattr(settings, 'TELEGRAM_PROXY', '') or '').strip()
        or ''
    )


def _get_opener():
    """Прямой IPv4 — если Telegram открыт. Иначе HTTP-прокси (TELEGRAM_PROXY)."""
    global _cached_opener
    if _cached_opener is not None:
        return _cached_opener
    proxy = _proxy_url()
    if proxy:
        _cached_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({'http': proxy, 'https': proxy}),
        )
    else:
        _cached_opener = urllib.request.build_opener(_IPv4HTTPSHandler())
    return _cached_opener


def _token() -> str:
    token = (getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
    if not token:
        raise TelegramError('TELEGRAM_BOT_TOKEN не задан в .env')
    return token


def _call(method: str, params: dict | None = None, *, timeout: float = 60.0) -> dict:
    url = f'{API_ROOT}/bot{_token()}/{method}'
    data = json.dumps(params or {}, ensure_ascii=False).encode('utf-8')
    request = urllib.request.Request(
        url, data=data, headers={'Content-Type': 'application/json'}, method='POST'
    )
    try:
        with _get_opener().open(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode('utf-8'))
            desc = body.get('description') or exc.code
            migrated = (body.get('parameters') or {}).get('migrate_to_chat_id')
            if migrated:
                desc = f'{desc}; новый id супергруппы: {migrated}'
            raise TelegramError(f'{method}: {desc}') from exc
        except TelegramError:
            raise
        except (ValueError, AttributeError):
            raise TelegramError(f'{method}: HTTP {exc.code}') from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f'{method}: {exc.reason}') from exc
    except TimeoutError as exc:
        raise TelegramError(f'{method}: timeout') from exc
    if not payload.get('ok'):
        raise TelegramError(f'{method}: {payload.get("description")}')
    return payload.get('result')


def get_updates(offset: int, timeout: int) -> list[dict]:
    return _call(
        'getUpdates',
        {
            'offset': offset,
            'timeout': timeout,
            'allowed_updates': ['message'],
        },
        timeout=timeout + 15,
    )


def send_message(chat_id: int, text: str, *, reply_to: int | None = None) -> dict:
    # Telegram режет сообщения длиннее 4096 символов.
    text = (text or '').strip() or '—'
    params = {
        'chat_id': chat_id,
        'text': text[:4096],
        'disable_web_page_preview': True,
    }
    if reply_to:
        params['reply_to_message_id'] = reply_to
        params['allow_sending_without_reply'] = True
    return _call('sendMessage', params)


def send_document(
    chat_id: int,
    file_path,
    *,
    filename: str = '',
    caption: str = '',
    reply_to: int | None = None,
) -> dict:
    """Отправить файл в чат (sendDocument). Telegram режет ботов на ~50 МБ."""
    from pathlib import Path
    import mimetypes
    import uuid

    src = Path(file_path)
    if not src.is_file():
        raise TelegramError(f'sendDocument: нет файла {src}')
    max_mb = int(getattr(settings, 'TELEGRAM_MAX_FILE_MB', 45) or 45)
    size = src.stat().st_size
    if size > max_mb * 1024 * 1024:
        raise TelegramError(f'sendDocument: файл больше {max_mb} МБ')
    name = (filename or src.name or 'file').replace('"', '').replace('\r', '').replace('\n', '')
    mime = mimetypes.guess_type(name)[0] or 'application/octet-stream'
    payload = src.read_bytes()
    boundary = '----crmtg' + uuid.uuid4().hex
    fields = {'chat_id': str(chat_id)}
    if caption:
        fields['caption'] = caption[:1024]
    if reply_to:
        fields['reply_to_message_id'] = str(reply_to)
        fields['allow_sending_without_reply'] = 'true'
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.append(
            (
                f'--{boundary}\r\n'
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f'{value}\r\n'
            ).encode('utf-8')
        )
    ascii_name = name.encode('ascii', 'replace').decode('ascii') or 'file'
    header = (
        f'--{boundary}\r\n'
        f'Content-Disposition: form-data; name="document"; filename="{ascii_name}"\r\n'
        f'Content-Type: {mime}\r\n\r\n'
    ).encode('utf-8')
    chunks.append(header + payload + b'\r\n')
    chunks.append(f'--{boundary}--\r\n'.encode('ascii'))
    body = b''.join(chunks)
    url = f'{API_ROOT}/bot{_token()}/sendDocument'
    request = urllib.request.Request(
        url,
        data=body,
        headers={'Content-Type': f'multipart/form-data; boundary={boundary}'},
        method='POST',
    )
    try:
        with _get_opener().open(request, timeout=180) as response:
            payload_json = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        try:
            err = json.loads(exc.read().decode('utf-8'))
            raise TelegramError(f'sendDocument: {err.get("description") or exc.code}') from exc
        except TelegramError:
            raise
        except (ValueError, AttributeError):
            raise TelegramError(f'sendDocument: HTTP {exc.code}') from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f'sendDocument: {exc.reason}') from exc
    if not payload_json.get('ok'):
        raise TelegramError(f'sendDocument: {payload_json.get("description")}')
    return payload_json.get('result')


def send_chat_action(chat_id: int, action: str = 'typing') -> None:
    try:
        _call('sendChatAction', {'chat_id': chat_id, 'action': action}, timeout=10)
    except TelegramError:
        pass


def get_file_path(file_id: str) -> str:
    result = _call('getFile', {'file_id': file_id}, timeout=30)
    path = (result or {}).get('file_path')
    if not path:
        raise TelegramError('getFile: пустой file_path')
    return path


def download_file(file_path: str, *, max_bytes: int) -> bytes:
    url = f'{API_ROOT}/file/bot{_token()}/{file_path}'
    request = urllib.request.Request(url, method='GET')
    try:
        with _get_opener().open(request, timeout=120) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise TelegramError(f'download: HTTP {exc.code}') from exc
    except urllib.error.URLError as exc:
        raise TelegramError(f'download: {exc.reason}') from exc
    if len(data) > max_bytes:
        raise TelegramError('файл больше лимита TELEGRAM_MAX_FILE_MB')
    return data
