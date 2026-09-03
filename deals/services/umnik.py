"""Клиент архива планировок (умник на LAN). Падения архива карточку сделки не ломают."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings


MD_PREFIX = re.compile(r'(?i)^\d+\s*мд\s*[-–—_\s]*')
ATTACH_FILE_RE = re.compile(r'^ATTACH_FILE:\s*(.+?)\s*$', re.M)


def archive_query_for_deal(deal) -> str:
    client = ' '.join((getattr(deal, 'code_client_name', None) or '').split())
    site = ' '.join((getattr(deal, 'code_site_name', None) or '').split())
    if client and site:
        return f'{client} {site}'
    if client:
        return client
    if site:
        return site
    code = (getattr(deal, 'project_code', None) or '').replace('_', ' ').replace('-', ' ')
    stripped = MD_PREFIX.sub('', code).strip()
    return stripped or (getattr(deal, 'project_code', None) or '').strip()


def split_attach_files(answer: str) -> tuple[str, list[str]]:
    """Достаёт пути из строк ATTACH_FILE: и вычищает их из текста ответа."""
    paths: list[str] = []
    seen: set[str] = set()
    for match in ATTACH_FILE_RE.finditer(answer or ''):
        raw = match.group(1).strip().strip('`"\'')
        key = raw.lower()
        if raw and key not in seen:
            seen.add(key)
            paths.append(raw)
    text = ATTACH_FILE_RE.sub('', answer or '')
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    return text, paths


def _lookup_url(base: str) -> str:
    base = (base or '').rstrip('/')
    if base.endswith('/crm/lookup'):
        return base
    if base.endswith('/crm'):
        return f'{base}/lookup'
    return f'{base}/crm/lookup'


def empty_archive(query: str = '', error: str = '') -> dict:
    payload = {'ok': False, 'query': query, 'layouts': []}
    if error:
        payload['error'] = error
    return payload


def fetch_archive(query: str, limit: int | None = None) -> dict:
    q = (query or '').strip()
    base = (getattr(settings, 'UMNIK_URL', '') or '').strip()
    if not base:
        return empty_archive(q, 'not_configured')
    params = {'query': q}
    if limit:
        params['limit'] = str(int(limit))
    url = f'{_lookup_url(base)}?{urllib.parse.urlencode(params)}'
    headers = {'Accept': 'application/json'}
    token = (getattr(settings, 'UMNIK_TOKEN', '') or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    timeout = float(getattr(settings, 'UMNIK_TIMEOUT', 3) or 3)
    request = urllib.request.Request(url, headers=headers, method='GET')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return empty_archive(q, f'http_{exc.code}')
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return empty_archive(q, 'unreachable')
    if not isinstance(payload, dict):
        return empty_archive(q, 'bad_payload')
    layouts = payload.get('layouts')
    if not isinstance(layouts, list):
        layouts = []
    return {
        'ok': bool(payload.get('ok')),
        'query': payload.get('query') or q,
        'layouts': layouts,
        'error': payload.get('error') or '',
    }


def lookup_deal_archive(deal) -> dict:
    query = archive_query_for_deal(deal)
    result = fetch_archive(query)
    result['query'] = result.get('query') or query
    return result


def _chat_url(base: str) -> str:
    base = (base or '').rstrip('/')
    if base.endswith('/crm/chat'):
        return base
    if base.endswith('/crm'):
        return f'{base}/chat'
    return f'{base}/crm/chat'


def ask_umnik_chat(*, message: str, history: list, actor: str, deal_id=None, deal_code: str = '', capabilities: dict | None = None, attachments: list | None = None) -> dict:
    base = (getattr(settings, 'UMNIK_URL', '') or '').strip()
    if not base:
        return {'ok': False, 'error': 'not_configured', 'answer': 'Умник не подключён: задайте UMNIK_URL в .env.'}
    payload = {
        'message': (message or '').strip(),
        'history': history or [],
        'actor': actor,
        'deal_id': deal_id,
        'deal_code': deal_code or '',
        'capabilities': capabilities or {},
        'attachments': attachments or [],
    }
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    token = (getattr(settings, 'UMNIK_TOKEN', '') or '').strip()
    if token:
        headers['Authorization'] = f'Bearer {token}'
    timeout = float(getattr(settings, 'UMNIK_CHAT_TIMEOUT', 180) or 180)
    request = urllib.request.Request(_chat_url(base), data=body, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        return {'ok': False, 'error': f'http_{exc.code}', 'answer': 'Умник не ответил. Проверьте, что архив на :7861 запущен.'}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {'ok': False, 'error': 'unreachable', 'answer': 'Умник недоступен. Карточка CRM при этом работает как обычно.'}
    if not isinstance(data, dict):
        return {'ok': False, 'error': 'bad_payload', 'answer': 'Умник вернул непонятный ответ.'}
    answer = (data.get('answer') or '').strip()
    answer, attach_paths = split_attach_files(answer)
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(data.get('attachments') or []) + attach_paths:
        raw = item.get('path') or item.get('server_path') if isinstance(item, dict) else str(item)
        path = (raw or '').strip()
        key = path.lower()
        if path and key not in seen:
            seen.add(key)
            merged.append(path)
    if not answer:
        answer = 'Пустой ответ.' if not merged else ''
    return {
        'ok': bool(data.get('ok', True)),
        'answer': answer or 'Файл во вложении.',
        'changed': bool(data.get('changed')),
        'error': data.get('error') or '',
        'attachments': merged,
    }

