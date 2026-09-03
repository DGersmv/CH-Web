"""Единая лента событий для Главной — «что у нас происходит».

Собирает строки из accounts.AuditEvent (их пишет system_settings.events.record_domain_event)
и превращает их в человекочитаемые пункты с иконкой и ссылкой.
"""

from django.urls import reverse

from accounts.models import AuditEvent
from deals.models import Deal, ServiceRequest

# Какие типы событий показываем в ленте (остальные — техническое эхо).
FEED_EVENT_TYPES = (
    'deal.created',
    'deal.status_changed',
    'deal.approvals_passed',
    'deal.design_passed',
    'project_version.imported',
    'project_file.uploaded',
    'task.created',
    'task.completed',
    'client_message.sent',
    'service_request.created',
    'service_request.status_changed',
    'deal.deleted',
)

_ICONS = {
    'deal.created': '🆕',
    'deal.status_changed': '➡️',
    'deal.approvals_passed': '✅',
    'deal.design_passed': '📐',
    'project_version.imported': '📥',
    'project_file.uploaded': '📎',
    'task.created': '🗒️',
    'task.completed': '☑️',
    'client_message.sent': '💬',
    'service_request.created': '🛠️',
    'service_request.status_changed': '🛠️',
    'deal.deleted': '🗑️',
}

_STATUS_RU = dict(Deal.Status.choices)
_SR_STATUS_RU = dict(ServiceRequest.Status.choices)


def _deal_url(deal_id):
    if not deal_id:
        return ''
    return reverse('deal_detail', args=[deal_id])


def _deal_code_map(deal_ids):
    ids = {i for i in deal_ids if i}
    if not ids:
        return {}
    return dict(Deal.objects.filter(pk__in=ids).values_list('id', 'project_code'))


def build_activity_feed(limit=25):
    events = list(
        AuditEvent.objects.select_related('actor')
        .filter(event_type__in=FEED_EVENT_TYPES)
        .order_by('-created_at')[:limit]
    )

    deal_ids = []
    for ev in events:
        payload = ev.payload or {}
        deal_ids.append(payload.get('deal_id'))
        if ev.entity_model == 'Deal':
            deal_ids.append(ev.entity_id)
    codes = _deal_code_map(deal_ids)

    feed = []
    for ev in events:
        payload = ev.payload or {}
        actor = ev.actor.username if ev.actor else 'система'
        deal_id = payload.get('deal_id') or (ev.entity_id if ev.entity_model == 'Deal' else None)
        code = codes.get(deal_id) or payload.get('project_code') or ''
        url = _deal_url(deal_id)
        et = ev.event_type

        if et == 'deal.created':
            text = f'Новый лид: {code or payload.get("project_code", "")}'
        elif et == 'deal.status_changed':
            old = _STATUS_RU.get(payload.get('old_status'), payload.get('old_status', ''))
            new = _STATUS_RU.get(payload.get('new_status'), payload.get('new_status', ''))
            text = f'{code}: статус {old} → {new}'
        elif et == 'deal.approvals_passed':
            text = f'{code}: согласования пройдены'
        elif et == 'deal.design_passed':
            text = f'{code}: проектирование завершено'
        elif et == 'project_version.imported':
            text = f'{code or payload.get("project_code", "")}: пришла версия из ArchiCAD'
        elif et == 'project_file.uploaded':
            name = payload.get('original_name', 'файл')
            text = f'{code + ": " if code else ""}загружен файл «{name}»'
        elif et == 'task.created':
            text = f'{code + ": " if code else ""}задача «{payload.get("title", "")}»'
        elif et == 'task.completed':
            text = f'{code + ": " if code else ""}задача выполнена'
        elif et == 'client_message.sent':
            text = f'{code + ": " if code else ""}сообщение клиенту'
        elif et == 'service_request.created':
            text = f'Сервис SR-{payload.get("number", "")}: {payload.get("title", "")}'
            if ev.entity_id:
                url = reverse('service_detail', args=[ev.entity_id])
        elif et == 'service_request.status_changed':
            old = _SR_STATUS_RU.get(payload.get('old_status'), '')
            new = _SR_STATUS_RU.get(payload.get('new_status'), '')
            text = f'Сервис SR-{payload.get("number", "")}: {old} → {new}'
            if ev.entity_id:
                url = reverse('service_detail', args=[ev.entity_id])
        elif et == 'deal.deleted':
            text = f'Удалена сделка {payload.get("project_code", "")}'
            url = ''
        else:
            text = et

        feed.append({
            'icon': _ICONS.get(et, '•'),
            'text': text,
            'url': url,
            'actor': actor,
            'when': ev.created_at,
        })
    return feed
