"""Кто дал указание по сделке: чат, карточка, задача в производство."""

from __future__ import annotations

from deals.models import DealInstruction


def person_label(user) -> str:
    """Логин того, кто писал. ФИО из профиля не подставляем."""
    if user is None:
        return ''
    return getattr(user, 'username', '') or ''


def record_instruction(
    *,
    deal,
    user,
    text: str,
    kind: str,
    source: str = DealInstruction.Source.CHAT,
    approval=None,
    design_section=None,
    task=None,
    actor_username: str = '',
):
    """Пишет отдельную запись «кто / когда / что просил». Повтор той же строки тем же человеком не дублируется."""
    body = (text or '').strip()
    if deal is None or not body:
        return None
    login = (actor_username or '').strip() or getattr(user, 'username', '') or ''
    filters = {'deal': deal, 'kind': kind}
    if approval is not None:
        filters['approval'] = approval
    if design_section is not None:
        filters['design_section'] = design_section
    if task is not None:
        filters['task'] = task
    latest = (
        DealInstruction.objects.filter(**filters)
        .order_by('-requested_at', '-id')
        .first()
    )
    if (
        latest is not None
        and latest.requested_by_id == getattr(user, 'pk', None)
        and (latest.actor_username or '') == login
        and (latest.text or '').strip().casefold() == body.casefold()
    ):
        return latest
    return DealInstruction.objects.create(
        deal=deal,
        kind=kind,
        source=source,
        approval=approval,
        design_section=design_section,
        task=task,
        requested_by=user if getattr(user, 'pk', None) else None,
        actor_username=login,
        text=body,
    )


def attach_latest_instructions(deal, items, kind: str) -> None:
    """Вешает last_instruction на пункты чек-листа / разделы / задачи."""
    if not items:
        return
    id_attr = {
        DealInstruction.Kind.APPROVAL: 'approval_id',
        DealInstruction.Kind.DESIGN: 'design_section_id',
        DealInstruction.Kind.PRODUCTION: 'task_id',
    }.get(kind)
    if not id_attr:
        return
    ids = [item.id for item in items]
    lookup = f'{id_attr}__in'
    rows = (
        DealInstruction.objects.filter(deal=deal, kind=kind, **{lookup: ids})
        .select_related('requested_by')
        .order_by('-requested_at', '-id')
    )
    latest = {}
    for row in rows:
        key = getattr(row, id_attr)
        if key not in latest:
            latest[key] = row
    for item in items:
        item.last_instruction = latest.get(item.id)


def serialize_instruction(row) -> dict | None:
    if row is None:
        return None
    return {
        'id': row.id,
        'kind': row.kind,
        'source': row.source,
        'source_label': row.get_source_display(),
        'text': row.text,
        'requested_by': row.requested_by_label,
        'requested_at': row.requested_at.isoformat() if row.requested_at else None,
    }
